"""
Patch 2: Wire new _analyze_video_format into enhance_pretrimmed_clip,
update _caption_segments to assign speaker_side, and update _write_ass
to emit per-event \an ASS alignment tags.
"""
import re
import os

SRC = os.path.join(os.path.dirname(__file__), "..", "effects", "world_class_editor.py")
content = open(SRC, encoding="utf-8").read()

# ── Patch 1: Replace the old face detection block in enhance_pretrimmed_clip ──
# Lines 1209-1219 (old numbering) — replace _detect_primary_focus_x call
OLD_FACE = """            if cfg.enable_active_speaker:
                t0 = time.perf_counter()
                focus_x = self._detect_primary_focus_x(work_b)
                t_face += time.perf_counter() - t0
            else:
                focus_x = 0.5

            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            vf = self._build_reframe_filter(work_meta, target_wh, focus_x, cfg, boring_mode)
            t_reframe += time.perf_counter() - t0"""

NEW_FACE = """            video_fmt = None
            if cfg.enable_active_speaker and cfg.enable_format_detection:
                t0 = time.perf_counter()
                video_fmt = self._analyze_video_format(work_b)
                t_face += time.perf_counter() - t0
                metadata["video_format"] = video_fmt.format_type
                metadata["speaker_positions"] = video_fmt.speaker_positions
                log.info(
                    "[WCE-FORMAT] format=%s avg_faces=%.2f speakers=%s",
                    video_fmt.format_type, video_fmt.face_count_avg, video_fmt.speaker_positions,
                )
            elif cfg.enable_active_speaker:
                # Legacy: no format detection, use monologue mode only
                t0 = time.perf_counter()
                video_fmt = self._analyze_video_format(work_b)
                t_face += time.perf_counter() - t0

            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg)
            else:
                focus_x = 0.5
            vf = self._build_reframe_filter(work_meta, target_wh, focus_x, cfg, boring_mode)
            t_reframe += time.perf_counter() - t0"""

assert OLD_FACE in content, "ERROR: OLD_FACE block not found!"
content = content.replace(OLD_FACE, NEW_FACE, 1)
print("Patch 1 (face detect wiring): OK")

# ── Patch 2: _caption_segments — attach speaker_side per segment ──
OLD_CAP_SIGNATURE = """    def _caption_segments(
        self,
        transcript_window: List[Dict[str, Any]],
        source_start: float,
        trim_in: float,
        trim_out: float,
        config: ClipEditConfig,
        ramp_window: float,
    ) -> List[CaptionSegment]:"""

NEW_CAP_SIGNATURE = """    def _caption_segments(
        self,
        transcript_window: List[Dict[str, Any]],
        source_start: float,
        trim_in: float,
        trim_out: float,
        config: ClipEditConfig,
        ramp_window: float,
        video_fmt: "VideoFormat" = None,
    ) -> List[CaptionSegment]:"""

assert OLD_CAP_SIGNATURE in content, "ERROR: OLD_CAP_SIGNATURE not found!"
content = content.replace(OLD_CAP_SIGNATURE, NEW_CAP_SIGNATURE, 1)
print("Patch 2a (_caption_segments signature): OK")

# Add speaker_side logic before the append
OLD_CAP_APPEND = """                c_txt = self._decorate_caption(chunk, config.add_emojis)
                cap_segments.append(CaptionSegment(start=c_s, end=c_e, text=c_txt))"""

NEW_CAP_APPEND = """                c_txt = self._decorate_caption(chunk, config.add_emojis)
                # Speaker-side assignment: map caption time to active speaker cluster
                seg_side = "center"
                if config.speaker_aware_captions and video_fmt is not None and len(video_fmt.speaker_positions) >= 2:
                    spk = sorted(video_fmt.speaker_positions[:2])
                    # Find which speaker cluster was visible closest to caption start
                    closest_faces = []
                    best_dt = float("inf")
                    for t_samp, faces in video_fmt.samples:
                        dt = abs(t_samp - c_s)
                        if dt < best_dt:
                            best_dt = dt
                            closest_faces = faces
                    if len(closest_faces) == 1:
                        seg_side = "left" if closest_faces[0] < 0.5 else "right"
                    elif len(closest_faces) >= 2:
                        seg_side = "left" if (sum(closest_faces) / len(closest_faces)) < 0.5 else "right"
                cap_segments.append(CaptionSegment(start=c_s, end=c_e, text=c_txt, speaker_side=seg_side))"""

assert OLD_CAP_APPEND in content, "ERROR: OLD_CAP_APPEND not found!"
content = content.replace(OLD_CAP_APPEND, NEW_CAP_APPEND, 1)
print("Patch 2b (_caption_segments speaker_side): OK")

# ── Patch 3: _write_ass — remove hardcoded alignment, add per-event \an tag ──
OLD_ASS_DISABLED = """        # ── Speaker-aware caption positioning ──────────────────────────────
        # ─ Speaker-aware logic disabled. Always use uniform bottom-center ─
        # Alignment codes in ASS: 1=bottom-left, 2=bottom-center, 3=bottom-right
        caption_alignment = 2
        margin_l, margin_r, margin_v = 40, 40, 250
        log.info("[WCE-CAPTION] speaker-aware disabled → forced bottom-center (alignment=2) to guarantee alignment")"""

NEW_ASS_ACTIVE = """        # ── Speaker-aware caption positioning ──────────────────────────────
        # Global style baseline = bottom-center (alignment=2). Per-event \\an tags
        # override alignment for individual captions when speaker_side is set.
        # Alignment codes in ASS: 1=bottom-left, 2=bottom-center, 3=bottom-right
        caption_alignment = 2
        margin_l, margin_r, margin_v = 40, 40, 250
        log.info("[WCE-CAPTION] per-event speaker-side \\\\an alignment: ACTIVE")"""

assert OLD_ASS_DISABLED in content, "ERROR: OLD_ASS_DISABLED not found!"
content = content.replace(OLD_ASS_DISABLED, NEW_ASS_ACTIVE, 1)
print("Patch 3a (_write_ass comment): OK")

# Update karaoke word events to inject \an tag based on seg.speaker_side
OLD_KARAOKE_EVENT = """                    events.append(f\"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{line_text}\")
            else:
                # Single-word segment — just highlight it
                highlighted_text = self._highlight_text(escaped_text)
                events.append(f\"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Caption,,0,0,0,,{highlighted_text}\")"""

NEW_KARAOKE_EVENT = """                    an_tag = {"left": "{\\\\an1}", "right": "{\\\\an3}"}.get(getattr(seg, "speaker_side", "center"), "")
                    events.append(f\"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{an_tag}{line_text}\")
            else:
                # Single-word segment — just highlight it
                highlighted_text = self._highlight_text(escaped_text)
                an_tag = {"left": "{\\\\an1}", "right": "{\\\\an3}"}.get(getattr(seg, "speaker_side", "center"), "")
                events.append(f\"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Caption,,0,0,0,,{an_tag}{highlighted_text}\")"""

assert OLD_KARAOKE_EVENT in content, "ERROR: OLD_KARAOKE_EVENT not found!"
content = content.replace(OLD_KARAOKE_EVENT, NEW_KARAOKE_EVENT, 1)
print("Patch 3b (_write_ass per-event an tag): OK")

# ── Patch 4: Update _caption_segments call to pass video_fmt ──
OLD_CAP_CALL = """                captions = self._caption_segments(
                    transcript_window=transcript_window,
                    source_start=source_start,
                    trim_in=trim_in,
                    trim_out=trim_out,
                    config=cfg,
                    ramp_window=ramp_window,
                )"""

NEW_CAP_CALL = """                captions = self._caption_segments(
                    transcript_window=transcript_window,
                    source_start=source_start,
                    trim_in=trim_in,
                    trim_out=trim_out,
                    config=cfg,
                    ramp_window=ramp_window,
                    video_fmt=video_fmt,
                )"""

assert OLD_CAP_CALL in content, "ERROR: OLD_CAP_CALL not found!"
content = content.replace(OLD_CAP_CALL, NEW_CAP_CALL, 1)
print("Patch 4 (_caption_segments call): OK")

# ── Patch 5: Update speaker_side derivation to use video_fmt ──
OLD_SPK_SIDE = """            # Derive speaker side for caption positioning
            if isinstance(focus_x, str):
                speaker_side = "center"
            elif focus_x < 0.42:
                speaker_side = "left"
            elif focus_x > 0.58:
                speaker_side = "right"
            else:
                speaker_side = "center\""""

NEW_SPK_SIDE = """            # Derive global speaker_side for hook/CTA positioning (captions use per-event side)
            if video_fmt is not None and video_fmt.format_type == "podcast" and len(video_fmt.speaker_positions) >= 1:
                # Podcast: use the position of the first detected cluster
                dom_x = video_fmt.speaker_positions[0]
                speaker_side = "left" if dom_x < 0.45 else ("right" if dom_x > 0.55 else "center")
            elif isinstance(focus_x, float) and focus_x < 0.42:
                speaker_side = "left"
            elif isinstance(focus_x, float) and focus_x > 0.58:
                speaker_side = "right"
            else:
                speaker_side = "center\""""

assert OLD_SPK_SIDE in content, "ERROR: OLD_SPK_SIDE not found!"
content = content.replace(OLD_SPK_SIDE, NEW_SPK_SIDE, 1)
print("Patch 5 (speaker_side derivation): OK")

open(SRC, "w", encoding="utf-8").write(content)
print("\nAll patches applied successfully.")
print("New file size: %d bytes" % len(content))
