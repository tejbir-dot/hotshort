import os
import math
import shutil
import subprocess
import tempfile
from typing import List, Dict, Optional

# -- imports from effect modules (assumed to exist in effects/)
from effects.face_crop import build_face_crop
from effects.jump_stitch import build_jump_blocks
from effects.energy_map import build_energy_curve
from effects.speaker_zoom import build_zoom_filter
from effects.silence_jump import detect_silence_spans
from effects.caption import build_captions, captions_to_srt
from effects.broll_detector import detect_broll
from effects.camera_switch import detect_camera_zone
from viral_finder.ignition_deep import generate_punch_clips
from viral_finder.idea_graph import get_video_duration


# -----------------------------
# Helpers
# -----------------------------
def emotion_based_silence_config(emotion: float):
    if emotion >= 0.75:
        return None  # disable silence jump
    elif emotion >= 0.5:
        return {"min_len": 1.5}
    else:
        return {"min_len": 0.9}

def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)


def _duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    p = _run(cmd, check=False)
    try:
        return float(p.stdout.strip())
    except Exception:
        try:
            return float(p.stderr.strip())
        except Exception:
            return 0.0


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# -----------------------------
# Main ultron editor (orchestrator)
# -----------------------------
MIN_FINAL_DURATION = 15.0  # seconds
def extend_until_sentence_complete(
    clip_start: float,
    clip_end: float,
    transcript: list,
    max_extend: float = 6.0
):
    """
    Extends clip end if transcript sentence is cut mid-thought
    """

    for seg in transcript:
        ts, te = seg["start"], seg["end"]
        text = seg.get("text", "").strip()

        if ts < clip_end < te:
            # sentence cut in middle
            extra = min(te - clip_end, max_extend)
            return round(clip_end + extra, 2)

    return clip_end
from viral_finder.ignition_deep import generate_punch_clips
from viral_finder.idea_graph import get_video_duration

def ultron_core_editor(
    video_path: str,
    moment: Dict,
    out_path: str,
    transcript: Optional[List[Dict]] = None,
    temp_dir: Optional[str] = None,
    keep_temp: bool = False,
    bitrate_k: int = 3500
) -> bool:
    """
    Orchestrates the full Ultron pipeline using the modular effects.

    Steps (high level):
      1. Build jump blocks from raw "moments" (or single moment)
      2. Detect silence spans and remove them (collapse silence)
      3. Extract selected segments (fast copy)
      4. Concat segments into a single temp file
      5. Compute face crop, energy curve, zoom filter, camera signal, b-roll
      6. Render final single-pass encode using tuned bitrate controls
      7. Bake captions if transcript provided

    Returns True on success.
    """
        # ===============================
    # 🔒 RESPECT ANALYZE-LEVEL ENDING
    # ===============================
    

    start = float(moment.get("start", 0))
    base_end = float(moment.get("end", start + 5))

    # If analyze layer decided the ending semantically,
    # Ultron must NOT recompute duration
    lock_end = bool(moment.get("lock_end", False))
    
    # When lock_end is True, use base_end as the final boundary
    # (analyze_video has already applied all semantic logic)
    final_end = base_end if lock_end else base_end

    # --- setup temp dir
    if temp_dir is None:
        tdir = tempfile.mkdtemp(prefix="ultron_")
    else:
        tdir = temp_dir
        _ensure_dir(tdir)

    # try:
        # --- 0. normalize input "moment" into list of segments
        raw_segments = []
        if isinstance(moment, dict) and "start" in moment:
            raw_segments = [{
    "start": float(moment.get("start", 0)),
    "end": float(moment.get("end", moment.get("start", 0) + 5)),
    "score": float(moment.get("emotion", 0.5)),
    "lock_end": bool(moment.get("lock_end", False))
}]

        elif isinstance(moment, list):
            raw_segments = moment
        else:
            raise ValueError("moment must be dict or list of segments")
        # --------------------------------------------------
# PUNCH MODE: expand ignitions into short clips
# --------------------------------------------------
    if moment.get("type") == "punch" and "ignitions" in moment:
        from viral_finder.ignition_deep import generate_punch_clips
        from viral_finder.idea_graph import get_video_duration

        video_duration = get_video_duration(video_path)

        punch_clips = generate_punch_clips(
        ignitions=moment["ignitions"],
        video_duration=video_duration
    )

        for idx, clip in enumerate(punch_clips):
            sub_out = out_path.replace(".mp4", f"_punch_{idx}.mp4")

            ultron_core_editor(
                video_path=video_path,
                moment={
                "start": clip["start"],
                "end": clip["end"],
                "lock_end": True
            },
            out_path=sub_out,
            transcript=transcript,
            temp_dir=temp_dir,
            keep_temp=keep_temp,
            bitrate_k=bitrate_k
        )

       

        # 1) build stitched blocks
        blocks = build_jump_blocks(raw_segments)
        if not blocks:
            print("[ULTRON] No blocks to render")
            return False

        # 2) detect silence spans for the whole video (fast)
        # silences = detect_silence_spans(video_path)
        # print(f"[ULTRON] Detected silences: {silences}")
        cfg = emotion_based_silence_config(moment.get("emotion", 0.5))

        if cfg is None:
           silences = []   # do NOT remove silence
        else:
           silences = detect_silence_spans(
        video_path,
        min_len=cfg["min_len"]
    )

        # 3) cut out silence within blocks -> produce final subsegments
        def subtract_silences_from_block(block_start, block_end, silences_list):
            pieces = []
            cur = block_start
            for s, e in silences_list:
                if e <= cur or s >= block_end:
                    continue
                # silence overlaps current block
                if s > cur:
                    pieces.append((cur, min(s, block_end)))
                cur = max(cur, e)
                if cur >= block_end:
                    break
            if cur < block_end:
                pieces.append((cur, block_end))
            return pieces

        final_segments = []
        for b in blocks:
            parts = subtract_silences_from_block(b["start"], b["end"], silences)
            for p in parts:
                # skip tiny pieces
                if p[1] - p[0] < 0.8:
                    continue
                final_segments.append({"start": round(p[0], 3), "end": round(p[1], 3), "score": b.get("energy", b.get("energy", 0.5))})

        if not final_segments:
            print("[ULTRON] After silence collapse nothing left — falling back to original blocks")
            final_segments = [{"start": b["start"], "end": b["end"], "score": b.get("energy", 0.5)} for b in blocks]
            # 🧠 END-OF-CLIP SENSE COMPLETE LOGIC
            if transcript and final_segments:
               last = final_segments[-1]

            for seg in transcript:
               ts, te = seg.get("start", 0), seg.get("end", 0)

        # agar clip sentence ke beech cut ho rahi hai
               if last["start"] < ts < last["end"] < te:
                  extend_by = min(te - last["end"], 6.0)  # max 6 sec extend
                  print(f"[ULTRON SENSE] Extending clip by {round(extend_by,2)}s to finish sentence")
                  last["end"] = round(last["end"] + extend_by, 2)
                  break

        # 4) fast-extract segments (copy) to temp files
        seg_files = []
        for idx, s in enumerate(final_segments):
            seg_path = os.path.join(tdir, f"seg_{idx}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(s["start"]),
                "-to", str(s["end"]),
                "-i", video_path,
                "-c", "copy",
                seg_path
            ]
            print("[ULTRON] Extracting segment:", cmd)
            _run(cmd)
            if os.path.exists(seg_path):
                seg_files.append(seg_path)

        if not seg_files:
            print("[ULTRON] No segment files created")
            return False

        # 5) concat segments using ffmpeg concat demuxer (fast)
        list_path = os.path.join(tdir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in seg_files:
                f.write(f"file '{os.path.abspath(p)}'\n")

        concat_path = os.path.join(tdir, "concat.mp4")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", concat_path
        ]
        print("[ULTRON] Concatenating segments")
        _run(cmd)

        tot_dur = _duration(concat_path)
        print(f"[ULTRON] Concatenated duration: {tot_dur}s")

        

        # 6) compute visual/audio intelligence on the concatenated clip
        face_vf = build_face_crop(concat_path, 0.0, tot_dur)
        energy = build_energy_curve(concat_path)
        zoom_vf = build_zoom_filter(energy)
        cam = detect_camera_zone(concat_path)

        # b-roll signal for the first transcript chunk if exists
        broll_signal = None
        if transcript and len(transcript) > 0:
            broll_signal = detect_broll(transcript[0].get("text", ""))

        # build final vf chain (face crop -> zoom -> color)
        vf_parts = []
        if face_vf:
            vf_parts.append(face_vf)

        if zoom_vf:
            # zoom_vf might be something like "zoompan=..." which needs careful placement
            vf_parts.append(zoom_vf)

        if srt_path:
            vf_parts.append(f"subtitles='{srt_path}'")


        # captions: adjust and build srt aligned to new timeline
        srt_path = None
        if transcript:
            # map original transcript to the new timeline
            new_transcript = []
            cum = 0.0
            for seg in final_segments:
                s0, e0 = seg["start"], seg["end"]
                for t in transcript:
                    if transcript:
                       last = final_segments[-1]
                       last["end"] = extend_until_sentence_complete(
        last["start"],
        last["end"],
        transcript
    )

                    ts, te = t.get("start", 0.0), t.get("end", 0.0)
                    if te <= s0 or ts >= e0:
                        continue
                    # overlap
                    nts = max(0.0, ts - s0)
                    nte = min(e0 - s0, te - s0)
                    new_transcript.append({
                        "start": round(cum + nts, 2),
                        "end": round(cum + nte, 2),
                        "text": t.get("text", "")
                    })
                cum += (e0 - s0)

            if new_transcript:
                srt_path = os.path.join(tdir, "caps.srt")
                captions_to_srt(new_transcript, srt_path)
                print(f"[ULTRON] captions written -> {srt_path}")

        # 7) Final render (single encode pass)
        final_vf = ",".join(vf_parts)

        # build ffmpeg command
        cmd = [
            "ffmpeg", "-y",
            "-i", concat_path,
            "-vf", final_vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-b:v", f"{bitrate_k}k",
            "-maxrate", f"{int(bitrate_k*1.15)}k",
            "-bufsize", f"{int(bitrate_k*2)}k",
            "-c:a", "aac",
            "-b:a", "128k",
        ]

        # subtitles overlay (burn-in)
        if srt_path:
            # subtitles filter must be appended to vf chain
            cmd[cmd.index("-vf") + 1] = final_vf + f",subtitles='{srt_path}'"

        # final output
        cmd.append(out_path)

        print("[ULTRON] Final render cmd:", " ".join(cmd))
        p = _run(cmd, check=False)
        if p.returncode != 0:
            print("[ULTRON] Final render failed, stderr:\n", p.stderr)
            # fallback: try a simpler render without subtitles
            try:
                fallback_cmd = [
                    "ffmpeg", "-y", "-i", concat_path,
                    "-vf", final_vf,
                    "-c:v", "libx264", "-preset", "veryfast",
                    "-b:v", f"{bitrate_k}k",
                    "-c:a", "aac", "-b:a", "128k",
                    out_path
                ]
                _run(fallback_cmd)
            except Exception as e:
                print("[ULTRON] Fallback failed:", e)
                return False

        print("[ULTRON] Render complete ->", out_path)

        # optionally expose some meta
        return True

   # ----------------------------
# TEMP CLEANUP (SAFE)
# ----------------------------
    if not keep_temp:
        try:
          shutil.rmtree(tdir)
        except Exception:
          pass

    return True
