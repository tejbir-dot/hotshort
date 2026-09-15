import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = '''            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg, work_b)'''

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
            if cfg.add_captions:
                cap_thread = CaptionThread(self, transcript_window, source_start, trim_in, trim_out, cfg, ramp_window, video_fmt)
                cap_thread.start()
            # --- END CAPTION THREAD ---

            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg, work_b)'''

target2 = '''            captions: List[CaptionSegment] = []
            if cfg.add_captions:
                captions = self._caption_segments(
                    transcript_window=transcript_window,
                    source_start=source_start,
                    trim_in=trim_in,
                    trim_out=trim_out,
                    config=cfg,
                    ramp_window=ramp_window,
                    video_fmt=video_fmt,
                )'''

replacement2 = '''            captions: List[CaptionSegment] = []
            if cap_thread is not None:
                cap_thread.join()
                captions = cap_thread.captions'''

if target1 in text and target2 in text:
    new_text = text.replace(target1, replacement1).replace(target2, replacement2)
    with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced successfully!")
else:
    print("Targets not found.")

