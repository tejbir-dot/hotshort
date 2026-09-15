import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = '''            # --- START CAPTION THREAD (Parallel Processing) ---
            import threading
            class CaptionThread(threading.Thread):
                def __init__(self, editor, tw, ss, ti, to, cfg, rw, vf):
                    super().__init__()
                    self.editor = editor
                    self.tw = tw; self.ss = ss; self.ti = ti; self.to = to; self.cfg = cfg; self.rw = rw; self.vf = vf
                    self.captions = []
                def run(self):
                    self.captions = self.editor._caption_segments(
                        transcript_window=self.tw,
                        source_start=self.ss,
                        trim_in=self.ti,
                        trim_out=self.to,
                        config=self.cfg,
                        ramp_window=self.rw,
                        video_fmt=self.vf,
                    )
            
            cap_thread = None
            if cfg.add_captions:
                cap_thread = CaptionThread(self, transcript_window, source_start, trim_in, trim_out, cfg, ramp_window, video_fmt)
                cap_thread.start()
            # --- END CAPTION THREAD ---'''

replacement1 = '''            # --- START CAPTION THREAD (Parallel Processing) ---
            import threading
            class CaptionThread(threading.Thread):
                def __init__(self, editor, tw, ss, ti, to, cfg, rw, vf):
                    super().__init__()
                    self.editor = editor
                    self.tw = tw; self.ss = ss; self.ti = ti; self.to = to; self.cfg = cfg; self.rw = rw; self.vf = vf
                    self.captions = []
                def run(self):
                    self.captions = self.editor._caption_segments(
                        transcript_window=self.tw,
                        source_start=self.ss,
                        trim_in=self.ti,
                        trim_out=self.to,
                        config=self.cfg,
                        ramp_window=self.rw,
                        video_fmt=self.vf,
                    )
            
            cap_thread = None
            if cfg.add_captions and precomputed_ass_path is None:
                cap_thread = CaptionThread(self, transcript_window, source_start, trim_in, trim_out, cfg, ramp_window, video_fmt)
                cap_thread.start()
            # --- END CAPTION THREAD ---'''

target2 = '''            if has_any_overlay:
                ass_path = os.path.join(self.work_dir, f"wc_subs_{uuid.uuid4().hex}.ass")
                tmp_files.append(ass_path)
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
                    speaker_side=speaker_side,
                )
                fonts_dir_esc = _ffmpeg_filter_path(_FONTS_DIR)
                ass_esc = _ffmpeg_filter_path(ass_path)'''

replacement2 = '''            if has_any_overlay or precomputed_ass_path:
                ass_path = precomputed_ass_path
                if not ass_path:
                    ass_path = os.path.join(self.work_dir, f"wc_subs_{uuid.uuid4().hex}.ass")
                    tmp_files.append(ass_path)
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
                        speaker_side=speaker_side,
                    )
                fonts_dir_esc = _ffmpeg_filter_path(_FONTS_DIR)
                ass_esc = _ffmpeg_filter_path(ass_path)'''

target3 = '''            if is_complex_graph:
                # If we added subtitles, the last pad is [v_subs], otherwise [v_reframe]
                last_pad = "[v_subs]" if has_any_overlay else "[v_reframe]"'''

replacement3 = '''            if is_complex_graph:
                # If we added subtitles, the last pad is [v_subs], otherwise [v_reframe]
                last_pad = "[v_subs]" if (has_any_overlay or precomputed_ass_path) else "[v_reframe]"'''

if target1 in text and target2 in text and target3 in text:
    new_text = text.replace(target1, replacement1).replace(target2, replacement2).replace(target3, replacement3)
    with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced successfully!")
else:
    print("Targets not found.")

