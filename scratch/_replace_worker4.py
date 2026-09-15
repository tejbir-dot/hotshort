import sys
import re

replacement = '''def _process_job(job: dict, cloudinary_ok: bool):
    job_id      = job["job_id"]
    youtube_url = job.get("youtube_url") or job.get("video_url", "")
    is_free     = False if os.getenv("HS_UNLIMITED_MODE", "0") == "1" else job.get("is_free_user", False)

    print(f"[LOCAL_WORKER] dYZ Processing job {job_id}: {youtube_url[:80]}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.mp4")

        # "?"? Step 1: Download via RapidAPI or fallback to yt-dlp "?"?
        print(f"[LOCAL_WORKER] Downloading video...", flush=True)
        try:
            _download_via_api(youtube_url, video_path)
        except Exception as e:
            print(f"[LOCAL_WORKER] RapidAPI failed ({e}), falling back to yt-dlp...", flush=True)
            _download_via_ytdlp(youtube_url, video_path)

        if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
            raise RuntimeError("Downloaded file is missing or too small")

        print(f"[LOCAL_WORKER] Download complete: {os.path.getsize(video_path) // (1024*1024)}MB", flush=True)

        # "?"? PIPELINE ARCHITECTURE "?"?
        clip_queue = queue.Queue(maxsize=5)
        results = []
        results_lock = threading.Lock()
        gpu_lock = threading.Semaphore(1)
        
        # Initialize Editor
        _editor_cls = None
        _config_cls = None
        _wce_enabled = os.getenv("HS_WORKER_EDITOR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
        _caption_enabled = os.getenv("HS_CAPTION_WORKER_ENABLED", "0").strip().lower() not in ("0", "false", "no", "off")
        
        if _wce_enabled or _caption_enabled:
            try:
                from effects.world_class_editor import ClipEditor, ClipEditConfig
                _editor_cls = ClipEditor
                _config_cls = ClipEditConfig
                print("[LOCAL_WORKER] world_class_editor loaded o.", flush=True)
            except Exception as e:
                print(f"[LOCAL_WORKER] world_class_editor load failed (raw cuts): {e}", flush=True)

        editor_instance = None
        editor_cfg = None
        if _editor_cls:
            _editor_work_dir = os.path.join(tmp, "wce_work")
            os.makedirs(_editor_work_dir, exist_ok=True)
            editor_instance = _editor_cls(_editor_work_dir)
            editor_cfg = _config_cls()

        # Start Global Face Cache precomputation in the background
        face_cache = FaceCache(video_path)
        face_thread = threading.Thread(target=face_cache.precompute, name="FaceCache")
        face_thread.start()

        # Global precomputed captions
        precomputed_captions = {}

        def run_orchestrator():
            try:
                print(f"[LOCAL_WORKER] Running orchestrator...", flush=True)
                from viral_finder.orchestrator import orchestrate
                
                clips = orchestrate(
                    video_path,
                    top_k=int(os.getenv("HS_ORCH_TOP_K", "8")),
                    prefer_gpu=True,
                    use_cache=True,
                    allow_fallback=False,
                    pipeline_mode=os.getenv("HS_ORCH_PIPELINE_MODE", "staged"),
                )
                
                # Precompute captions async before releasing clips
                if editor_instance and clips:
                    from utils.clipper import get_video_duration
                    print(f"[LOCAL_WORKER] Orchestration done: {len(clips)} clips. Pre-generating captions...", flush=True)
                    
                    _full_transcript = clips[0].get("transcript") or clips[0].get("captions")
                    
                    def gen_cap(clip, idx):
                        start = float(clip.get("start", 0))
                        end   = float(clip.get("end", start + 30))
                        clip_transcript = clip.get("transcript") or clip.get("captions") or _full_transcript or []
                        clip_title = clip.get("opening_caption") or clip.get("title") or clip.get("text", "")
                        cortex_hints = {"cortex_enabled": True} if clip.get("cortex_enabled") else None
                        if cortex_hints:
                            cortex_hints.update({
                                "editing_notes": clip.get("editing_notes", {}),
                                "opening_caption": clip.get("opening_caption", ""),
                                "title": clip.get("title", ""),
                                "hook_type": clip.get("hook_type", ""),
                                "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {})
                            })
                        ass_path = editor_instance.generate_caption_file(
                            input_path=video_path,
                            source_start=start,
                            source_end=end,
                            transcript=clip_transcript,
                            config=editor_cfg,
                            clip_title=clip_title,
                            cortex_hints=cortex_hints,
                            precomputed_narrative=clip.get("precomputed_narrative")
                        )
                        return idx, ass_path

                    with ThreadPoolExecutor(max_workers=4) as ex:
                        futures = [ex.submit(gen_cap, c, i) for i, c in enumerate(clips)]
                        for future in futures:
                            idx, ass_path = future.result()
                            precomputed_captions[idx] = ass_path

                for i, clip in enumerate(clips):
                    clip_queue.put((i, clip))
                    print(f"[PIPELINE] Clip queued: {i}", flush=True)

            except Exception as e:
                import traceback
                print(f"[LOCAL_WORKER] Orchestrator thread failed: {e}\\n{traceback.format_exc()}", flush=True)
            finally:
                clip_queue.put(None) # Signal done

        def run_editor():
            while True:
                item = clip_queue.get()
                if item is None:
                    break
                    
                i, clip = item
                start = float(clip.get("start", 0))
                end   = float(clip.get("end", start + 30))
                clip_res = {**clip, "clip_url": None, "error": None}
                
                try:
                    # CPU: Extract subclip (ffmpeg copy)
                    raw_path = os.path.join(tmp, f"clip_{i}_{int(start)}_{int(end)}.mp4")
                    import subprocess
                    subprocess.run([
                        "ffmpeg", "-y", "-ss", str(start), "-to", str(end),
                        "-i", video_path, "-c", "copy", "-avoid_negative_ts", "make_zero", raw_path
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                    
                    final_path = raw_path
                    
                    # GPU: Enhance Clip
                    if editor_instance:
                        edited_path = os.path.join(tmp, f"edited_{i}_{int(start)}_{int(end)}.mp4")
                        clip_transcript = clip.get("transcript") or clip.get("captions") or []
                        clip_title = clip.get("opening_caption") or clip.get("title") or clip.get("text", "")
                        
                        cortex_hints = None
                        if clip.get("cortex_enabled"):
                            cortex_hints = {
                                "cortex_enabled": True,
                                "editing_notes": clip.get("editing_notes", {}),
                                "opening_caption": clip.get("opening_caption", ""),
                                "title": clip.get("title", ""),
                                "hook_type": clip.get("hook_type", ""),
                                "learning_signal_for_hotshort": clip.get("learning_signal_for_hotshort", {})
                            }
                        
                        # Wait for FaceCache to finish if not already
                        if not face_cache._done:
                            face_thread.join()

                        with gpu_lock:
                            edit_result = editor_instance.enhance_pretrimmed_clip(
                                input_path=raw_path,
                                output_path=edited_path,
                                source_start=start,
                                source_end=end,
                                transcript=clip_transcript,
                                config=editor_cfg,
                                clip_title=clip_title,
                                precomputed_narrative=clip.get("precomputed_narrative"),
                                cortex_hints=cortex_hints,
                                is_free=is_free,
                                precomputed_face_cache=face_cache.cache,
                                precomputed_ass_path=precomputed_captions.get(i)
                            )
                        if edit_result.success:
                            final_path = edited_path
                        
                    # Branding
                    if os.getenv("HS_APPLY_BRANDING", "1") == "1":
                        branded_path = os.path.join(tmp, f"branded_{i}_{int(start)}_{int(end)}.mp4")
                        with gpu_lock:
                            if _apply_distribution_branding(final_path, branded_path):
                                final_path = branded_path

                    # Upload
                    url = None
                    if cloudinary_ok:
                        url = _upload_clip_to_cloudinary(final_path)
                    
                    clip_res["clip_url"] = url
                    with results_lock:
                        results.append(clip_res)
                        
                    print(f"[PIPELINE] Clip done + uploaded: {i}", flush=True)

                except Exception as e:
                    import traceback
                    print(f"[PIPELINE] Clip failed: {i} -> {e}\\n{traceback.format_exc()}", flush=True)
                    clip_res["error"] = str(e)
                    with results_lock:
                        results.append(clip_res)
                finally:
                    clip_queue.task_done()

        producer = threading.Thread(target=run_orchestrator, name="Orchestrator")
        consumer = threading.Thread(target=run_editor, name="Editor")
        
        producer.start()
        consumer.start()
        
        producer.join()
        consumer.join()
        
        # Sort results back to original order by start time
        results.sort(key=lambda x: x.get("start", 0))

        if not results:
            _fail_job(job_id, "All clips failed to process")
        else:
            _complete_job(job_id, results)

'''

with open('local_worker.py', 'r', encoding='utf-8') as f:
    text = f.read()

match = re.search(r'def _process_job\(job: dict, cloudinary_ok: bool\):.*?(?=def main\(\):)', text, re.DOTALL)
if match:
    new_text = text[:match.start()] + replacement + "\n\n" + text[match.end():]
    with open('local_worker.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced _process_job successfully!")
else:
    print("Could not match _process_job")

