import sys

with open('effects/world_class_editor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = '''    def enhance_pretrimmed_clip(
        self,
        input_path: str,
        output_path: str,
        source_start: float,
        source_end: float,
        transcript: Optional[List[Dict[str, Any]]] = None,
        config: Optional[ClipEditConfig] = None,
        clip_title: str = "",
        precomputed_narrative: Optional[Dict[str, Any]] = None,
        write_metadata_file: bool = True,
        is_free: bool = False,
        cortex_hints: Optional[Dict[str, Any]] = None,
    ) -> EditResult:'''

replacement1 = '''    def enhance_pretrimmed_clip(
        self,
        input_path: str,
        output_path: str,
        source_start: float,
        source_end: float,
        transcript: Optional[List[Dict[str, Any]]] = None,
        config: Optional[ClipEditConfig] = None,
        clip_title: str = "",
        precomputed_narrative: Optional[Dict[str, Any]] = None,
        write_metadata_file: bool = True,
        is_free: bool = False,
        cortex_hints: Optional[Dict[str, Any]] = None,
        precomputed_face_cache: Optional[Dict[float, List[Dict[str, float]]]] = None,
        precomputed_ass_path: Optional[str] = None,
    ) -> EditResult:'''

target2 = '''    def _get_crop_expression(self, video_fmt, transcript_window, config, clip_path=None):'''

replacement2 = '''    def _get_crop_expression(self, video_fmt, transcript_window, config, clip_path=None, face_cache=None):'''

target3 = '''                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                if frame_idx % 5 == 0:'''

replacement3 = '''                # 1. Detect raw faces — FaceMesh (preferred) or haarcascade fallback
                if face_cache is not None:
                    # Nearest cached timestamp
                    if face_cache:
                        nearest = min(face_cache.keys(), key=lambda tx: abs(tx - t))
                        raw_faces = face_cache[nearest]
                    else:
                        raw_faces = []
                    last_raw_faces = raw_faces
                elif frame_idx % 5 == 0:'''

target4 = '''            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg, work_b)'''

replacement4 = '''            t0 = time.perf_counter()
            target_wh = self._resolve_ratio(cfg.target_ratio)
            if video_fmt is not None:
                focus_x = self._get_crop_expression(video_fmt, transcript_window, cfg, work_b, face_cache=precomputed_face_cache)'''


if target1 in text and target2 in text and target3 in text and target4 in text:
    new_text = text.replace(target1, replacement1).replace(target2, replacement2).replace(target3, replacement3).replace(target4, replacement4)
    with open('effects/world_class_editor.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Replaced signature successfully!")
else:
    print("Targets not found.")

