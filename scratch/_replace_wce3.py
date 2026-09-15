import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = '''    def _write_ass(
        self,
        path: str,
        width: int,
        height: int,
        duration: float,'''

replacement = '''    def generate_caption_file(self, input_path: str, source_start: float, source_end: float, transcript: list, config, clip_title: str, cortex_hints: dict, precomputed_narrative: dict = None) -> str:
        """Standalone helper to generate .ass file for a clip before enhancing it."""
        import uuid
        import time
        from utils.clipper import get_video_duration
        
        cfg = config or ClipEditConfig()
        
        _cortex = cortex_hints or {}
        _cortex_active = bool(_cortex.get("cortex_enabled"))
        editing_notes = _cortex.get("editing_notes", {}) if isinstance(_cortex.get("editing_notes"), dict) else {}
        
        pacing_note = str(editing_notes.get("pacing_note", "")).lower().strip()
        subtitle_style = str(editing_notes.get("subtitle_style", "classic")).lower().strip()
        
        if _cortex_active:
            if pacing_note == "fast":
                cfg.max_caption_words = 3
            elif pacing_note == "slow":
                cfg.max_caption_words = 9

        base_meta = self._probe_video(input_path)
        clip_duration = max(0.01, float(base_meta.get("duration") or 0.0))
        
        if precomputed_narrative and isinstance(precomputed_narrative, dict):
            transcript_window = list(precomputed_narrative.get("transcript_window") or [])
            new_win = []
            for x in transcript_window:
                xs = _safe_float(x.get("start"), 0.0)
                xe = _safe_float(x.get("end"), xs)
                seg_offset = xs - source_start
                seg_remapped = {
                    "start": max(0.0, seg_offset),
                    "end": min(clip_duration, xe - source_start),
                    "text": x.get("text", "")
                }
                raw_words = x.get("words", [])
                if raw_words:
                    remapped_words = []
                    for w in raw_words:
                        ws = _safe_float(w.get("start"), xs)
                        we = _safe_float(w.get("end"), xe)
                        remapped_words.append({
                            "word": w.get("word") or w.get("text", ""),
                            "text": w.get("word") or w.get("text", ""),
                            "start": max(0.0, ws - source_start),
                            "end": min(clip_duration, we - source_start),
                        })
                    seg_remapped["words"] = remapped_words
                new_win.append(seg_remapped)
            transcript_window = new_win
            pre_trim = precomputed_narrative.get("trim")
        else:
            transcript_window = self._window_transcript(transcript, source_start, source_end)
            pre_trim = None
            
        if isinstance(pre_trim, dict):
            trim_in = _safe_float(pre_trim.get("in"), 0.0)
            trim_out = _safe_float(pre_trim.get("out"), clip_duration)
            trim_in = _clamp(trim_in, 0.0, max(0.0, clip_duration - 0.2))
            trim_out = _clamp(trim_out, trim_in + 0.2, clip_duration)
        else:
            trim_in = 0.0
            trim_out = clip_duration
            
        ramped_duration = trim_out - trim_in
        if cfg.enable_hook_speed_ramp:
            ramp_window = min(2.5, (trim_out - trim_in) * 0.4)
            ramped_duration = ramp_window / cfg.hook_ramp_speed + (trim_out - trim_in - ramp_window)
        else:
            ramp_window = 0.0
            
        captions = self._caption_segments(
            transcript_window=transcript_window,
            source_start=source_start,
            trim_in=trim_in,
            trim_out=trim_out,
            config=cfg,
            ramp_window=ramp_window,
            video_fmt=None,
        )
        
        if _cortex_active and _cortex.get("opening_caption"):
            hook_line = str(_cortex["opening_caption"]).strip()
        elif _cortex_active and _cortex.get("title"):
            hook_line = str(_cortex["title"]).strip()
        else:
            hook_line = clip_title.strip() if clip_title else (captions[0].text if captions else "")

        if _cortex_active:
            hook_type = str(_cortex.get("hook_type", "")).lower()
            if "curiosity" in hook_type or "mystery" in hook_type:
                cta_line = "Would you do it? Comment below."
            elif "fear" in hook_type or "risk" in hook_type or "danger" in hook_type:
                cta_line = "Share this before it's too late."
            elif "reveal" in hook_type or "twist" in hook_type or "surprise" in hook_type:
                cta_line = "Save this — you'll want to rewatch."
            elif "inspiration" in hook_type or "motivation" in hook_type:
                cta_line = "Follow for more of these moments."
            elif "confession" in hook_type or "personal" in hook_type:
                cta_line = "Drop a reaction below."
            else:
                cta_line = "Follow for more creator breakdowns."
        else:
            cta_line = "Follow for more creator breakdowns"
            
        cortex_hashtags = None
        if _cortex_active:
            ls = _cortex.get("learning_signal_for_hotshort", {})
            meaning_pattern = (ls.get("meaning_pattern") or "").strip() if isinstance(ls, dict) else ""
            topic_tags = [
                w.lower().replace(" ", "")
                for w in meaning_pattern.split(",")
                if len(w.strip()) > 3
            ][:3]
            if topic_tags:
                cortex_hashtags = " ".join(f"#{t}" for t in topic_tags)
        hashtags_line = (cortex_hashtags or self._extract_hashtags(transcript_window)) if cfg.add_hashtags else None
        
        has_any_overlay = (cfg.add_captions and captions) or (cfg.add_dynamic_overlays and hook_line) or (cfg.add_cta and cta_line)
        if not has_any_overlay:
            return ""
            
        ass_path = os.path.join(self.work_dir, f"wc_subs_async_{uuid.uuid4().hex}.ass")
        target_wh = self._resolve_ratio(cfg.target_ratio)
        
        self._write_ass(
            path=ass_path,
            width=target_wh[0],
            height=target_wh[1],
            duration=max(0.1, ramped_duration),
            captions=captions,
            hook_line=hook_line if cfg.add_dynamic_overlays else None,
            cta_line=cta_line if cfg.add_cta else None,
            hashtags_line=hashtags_line,
            subtitle_style=subtitle_style,
            speaker_side="center",
        )
        return ass_path

    def _write_ass(
        self,
        path: str,
        width: int,
        height: int,
        duration: float,'''

if target in text:
    new_text = text.replace(target, replacement)
    with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Added generate_caption_file successfully!")
else:
    print("Target not found.")

