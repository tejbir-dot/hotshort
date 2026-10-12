"""
GENIUS EDITZ BUILDER - Uses OpenRouter (existing key) for Gemini Flash ranking
Scans TJR Output clips -> Gemini ranks them -> Top 14 -> Viral 30s edits
"""
import os, sys, json, time, subprocess, re, io
from pathlib import Path
from typing import List, Dict, Optional

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

FACTORY_DIR  = os.path.dirname(os.path.abspath(__file__))
TJR_OUTPUT   = os.path.join(FACTORY_DIR, "Output", "TJR_trader")
GENIUS_OUT   = os.path.join(TJR_OUTPUT,  "Genius_Editz")
TOP_N        = 14
TARGET_DUR   = 30.0
# Use Gemini via OpenRouter (uses existing OPENROUTER_API_KEY)
LLM_MODEL    = "google/gemini-2.0-flash-001"
LLM_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

def _load_env():
    """Load .env and .env.local from project root into os.environ"""
    project_root = os.path.dirname(FACTORY_DIR)
    for env_file in [".env", ".env.local", ".env.worker"]:
        env_path = os.path.join(project_root, env_file)
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k not in os.environ:
                        os.environ[k.strip()] = v.strip().strip('"')

def _get_api_key() -> Optional[str]:
    _load_env()
    return (os.environ.get("OPENROUTER_API_KEY") or
            os.environ.get("GPT_API") or
            os.environ.get("GEMINI_API_KEY"))

def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_entries", "format=duration", path], capture_output=True, text=True, timeout=10)
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0

def _get_video_dims(path: str):
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", path], capture_output=True, text=True, timeout=10)
        s = json.loads(r.stdout)["streams"][0]
        return int(s["width"]), int(s["height"])
    except Exception:
        return 1080, 1920

def scan_clips(output_dir: str) -> List[Dict]:
    clips = []
    for f in sorted(Path(output_dir).glob("*.mp4")):
        caption_path = f.with_name(f.stem + "_caption.txt")
        caption_text, tiktok_caption = "", ""
        if caption_path.exists():
            try:
                caption_text = caption_path.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"TIKTOK CAPTION:\s*\n(.+?)(?=---|$)", caption_text, re.DOTALL)
                tiktok_caption = match.group(1).strip() if match else caption_text[:400]
            except Exception:
                pass
        dur = _probe_duration(str(f))
        if dur < 5.0:
            continue
        clips.append({
            "path": str(f), "name": f.stem, "duration": dur,
            "caption": tiktok_caption or caption_text[:300],
            "caption_path": str(caption_path) if caption_path.exists() else "",
        })
    print(f"\n[SCAN] Found {len(clips)} valid clips in {output_dir}")
    return clips

GEMINI_PROMPT = """You are an ELITE VIRAL CONTENT STRATEGIST for TikTok trading clips (creator: TJR).
Rank ALL {n} clips by viral potential. Return a JSON array with exactly {n} entries, each:
{{"name":"<stem>","hook_strength":<1-10>,"thumb_stop":<1-10>,"payoff_strength":<1-10>,"viral_rank":<1 is best>,"edit_style":"FAST_BURN|PUNCHY|REVELATION|RAMP","one_line_hook":"<strongest hook sentence>","reject_reason":"<leave blank if good>"}}
EDIT_STYLE guide:
- FAST_BURN = shock claims, impossible stats ("90% of traders")
- PUNCHY = lists, tips, step-by-step content
- REVELATION = forbidden secrets, hidden info, "what banks don't want you to know"
- RAMP = emotional mindset, transformation stories
CLIPS TO RANK:
{clips_json}
Return ONLY a valid JSON array. No markdown. No explanation."""

def rank_clips_with_gemini(clips: List[Dict], api_key: str) -> List[Dict]:
    print(f"\n[GEMINI] Sending {len(clips)} clips to Gemini Flash for viral ranking...")
    # Batch in groups of 30 if more clips
    all_rankings = []
    batch_size = 30
    for batch_start in range(0, len(clips), batch_size):
        batch = clips[batch_start:batch_start+batch_size]
        desc = [{"name":c["name"],"duration":round(c["duration"],1),"caption":c["caption"][:250]} for c in batch]
        prompt = GEMINI_PROMPT.format(n=len(batch), clips_json=json.dumps(desc, ensure_ascii=False))
        import urllib.request, urllib.error
        payload = json.dumps({
            "model": LLM_MODEL,
            "messages": [{"role":"user","content": prompt}],
            "temperature": 0.2,
            "max_tokens": 8192
        }).encode("utf-8")
        req = urllib.request.Request(LLM_BASE_URL, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://hotshort.app",
            "X-Title": "HotShort Genius Editz Builder"
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            raw = result["choices"][0]["message"]["content"]
            print(f"[GEMINI] Batch {batch_start//batch_size+1} response: {len(raw)} chars")
            raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
            batch_rankings = json.loads(raw)
            all_rankings.extend(batch_rankings)
        except Exception as e:
            print(f"[GEMINI ERROR] Batch {batch_start//batch_size+1}: {e}")
    return all_rankings

def select_top_clips(clips, rankings, top_n):
    rank_map = {r["name"]: r for r in rankings}
    scored = []
    for c in clips:
        rd = rank_map.get(c["name"], {})
        if rd.get("reject_reason","").strip():
            print(f"  [REJECT] {c['name']}: {rd['reject_reason']}")
            continue
        hook=float(rd.get("hook_strength",5)); thumb=float(rd.get("thumb_stop",5)); payoff=float(rd.get("payoff_strength",5))
        scored.append({**c, "hook_strength":hook, "thumb_stop":thumb, "payoff_strength":payoff,
            "viral_score":(hook*0.45)+(thumb*0.35)+(payoff*0.20), "viral_rank":int(rd.get("viral_rank",999)),
            "edit_style":rd.get("edit_style","PUNCHY"), "hook_line":rd.get("one_line_hook","")})
    scored.sort(key=lambda x:(x["viral_rank"],-x["viral_score"]))
    top = scored[:top_n]
    print(f"\n[SELECT] Top {len(top)} clips chosen (out of {len(scored)} candidates):")
    for i, c in enumerate(top, 1):
        print(f"  #{i:02d} [{c['edit_style']:12s}] viral_score={c['viral_score']:.1f} | {c['name']}")
        if c["hook_line"]: print(f"        HOOK: \"{c['hook_line'][:80]}\"")
    return top

def build_viral_edit(clip, out_path, target_dur=30.0):
    src, dur, style = clip["path"], clip["duration"], clip.get("edit_style","PUNCHY")
    w, h = _get_video_dims(src)
    trim = min(dur, target_dur)
    fade_out_start = max(0.1, trim - 0.5)
    if style == "FAST_BURN":
        # Crop-based zoom: scale up 8% then crop back → reliable on Windows (no zoompan)
        zw, zh = int(w * 1.08), int(h * 1.08)
        vf = (f"scale={zw}:{zh},"
              f"crop={w}:{h},"
              f"eq=saturation=1.2:contrast=1.1,"
              f"fade=t=in:st=0:d=0.1,"
              f"fade=t=out:st={max(0.1,trim-0.8):.3f}:d=0.8")
    elif style == "PUNCHY":
        vf = (f"scale={w}:{h},"
              f"eq=brightness=0.02:saturation=1.15:contrast=1.05,"
              f"vignette=PI/8,"
              f"fade=t=in:st=0:d=0.15,"
              f"fade=t=out:st={fade_out_start:.3f}:d=0.5")
    elif style == "REVELATION":
        # Crop-based slow zoom: scale 12% bigger then crop → cinematic build effect
        zw, zh = int(w * 1.12), int(h * 1.12)
        vf = (f"scale={zw}:{zh},"
              f"crop={w}:{h},"
              f"eq=saturation=1.2:contrast=1.08,"
              f"fade=t=in:st=0:d=0.4,"
              f"fade=t=out:st={fade_out_start:.3f}:d=0.5")
    elif style == "RAMP":
        ramp_start = max(trim - 7.0, 15.0)
        vf = (f"scale={w}:{h},"
              f"eq=brightness=0.01:saturation=1.1,"
              f"setpts=if(lt(T\\,{ramp_start:.2f})\\,PTS\\,PTS*0.85),"
              f"fade=t=in:st=0:d=0.2,"
              f"fade=t=out:st={fade_out_start:.3f}:d=0.5")
    else:
        vf = f"scale={w}:{h},eq=saturation=1.1:contrast=1.05"
    cmd = ["ffmpeg","-y","-nostdin","-t",f"{trim:.3f}","-i",src,
           "-vf",vf,"-c:v","libx264","-crf","20","-preset","fast",
           "-c:a","aac","-b:a","192k","-movflags","+faststart",out_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"  [FFMPEG ERR] {r.stderr[-300:]}")
            return False
        return True
    except Exception as e:
        print(f"  [FFMPEG EX] {e}"); return False

def write_genius_caption(clip, out_dir, rank):
    stem = os.path.splitext(os.path.basename(clip["path"]))[0]
    path = os.path.join(out_dir, f"genius_{rank:02d}_{stem}_caption.txt")
    lines = [
        f"GENIUS EDITZ #{rank:02d} | EDIT STYLE: {clip.get('edit_style','?')}",
        f"VIRAL SCORES - Hook: {clip.get('hook_strength',0):.0f}/10 | Thumb-Stop: {clip.get('thumb_stop',0):.0f}/10 | Payoff: {clip.get('payoff_strength',0):.0f}/10",
    ]
    if clip.get("hook_line"): lines.append(f"HOOK LINE: \"{clip['hook_line']}\"")
    lines += ["="*60, ""]
    if clip.get("caption_path") and os.path.exists(clip["caption_path"]):
        lines.append(open(clip["caption_path"], encoding="utf-8", errors="replace").read())
    open(path, "w", encoding="utf-8").write("\n".join(lines))

def main():
    print("\n" + "="*60)
    print("  GENIUS EDITZ BUILDER")
    print("  TJR Clips -> Gemini Flash -> Top 14 -> Viral 30s Edits")
    print("="*60)
    api_key = _get_api_key()
    if not api_key:
        print("[ERROR] No API key found (OPENROUTER_API_KEY / GPT_API)!")
        sys.exit(1)
    print(f"[API] Key found ({api_key[:12]}...)")
    clips = scan_clips(TJR_OUTPUT)
    if not clips:
        print("[ERROR] No clips found in", TJR_OUTPUT); sys.exit(1)
    rankings = rank_clips_with_gemini(clips, api_key)
    if not rankings:
        print("[WARN] LLM ranking failed - using fallback sort by duration")
        clips.sort(key=lambda c: abs(c["duration"]-30.0))
        for i, c in enumerate(clips):
            c.update({"viral_rank":i+1,"viral_score":5.0,"edit_style":["PUNCHY","FAST_BURN","REVELATION","RAMP"][i%4],"hook_line":"","hook_strength":5.0,"thumb_stop":5.0,"payoff_strength":5.0})
        top_clips = clips[:TOP_N]
    else:
        top_clips = select_top_clips(clips, rankings, TOP_N)
    if not top_clips:
        print("[ERROR] No clips after filtering"); sys.exit(1)
    os.makedirs(GENIUS_OUT, exist_ok=True)
    print(f"\n[EDITING] Building {len(top_clips)} viral edits -> {GENIUS_OUT}\n")
    ok_count = 0
    for rank, clip in enumerate(top_clips, 1):
        stem = os.path.splitext(os.path.basename(clip["path"]))[0]
        out_path = os.path.join(GENIUS_OUT, f"genius_{rank:02d}_{clip.get('edit_style','EDIT')}_{stem}.mp4")
        print(f"  [{rank:02d}/{len(top_clips)}] {clip.get('edit_style','?'):12s} | {os.path.basename(clip['path'])} ({clip['duration']:.0f}s->30s)")
        t0 = time.time()
        ok = build_viral_edit(clip, out_path)
        if ok:
            mb = os.path.getsize(out_path)/1_000_000
            print(f"         OK in {time.time()-t0:.1f}s -> {os.path.basename(out_path)} ({mb:.1f}MB)")
            write_genius_caption(clip, GENIUS_OUT, rank)
            ok_count += 1
        else:
            print(f"         FAILED -> stream-copy fallback...")
            cmd2 = ["ffmpeg","-y","-nostdin","-t",str(min(clip["duration"],TARGET_DUR)),"-i",clip["path"],"-c","copy",out_path]
            r = subprocess.run(cmd2, capture_output=True, timeout=60)
            if r.returncode == 0:
                write_genius_caption(clip, GENIUS_OUT, rank); ok_count += 1
                print(f"         FALLBACK OK")
    print(f"\n  DONE: {ok_count}/{len(top_clips)} clips built")
    print(f"  Output: {GENIUS_OUT}")
    report = [{"rank":i+1,"file":os.path.basename(c["path"]),"edit_style":c.get("edit_style","?"),"hook_strength":c.get("hook_strength",0),"thumb_stop":c.get("thumb_stop",0),"payoff_strength":c.get("payoff_strength",0),"viral_score":c.get("viral_score",0),"hook_line":c.get("hook_line","")} for i,c in enumerate(top_clips)]
    open(os.path.join(GENIUS_OUT,"genius_ranking_report.json"),"w",encoding="utf-8").write(json.dumps(report,indent=2,ensure_ascii=False))
    print(f"[REPORT] -> {GENIUS_OUT}/genius_ranking_report.json")

if __name__ == "__main__":
    main()


