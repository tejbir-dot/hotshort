import pytest
from pydantic import ValidationError
from editing_intelligence.schema import EditBlueprint, MetaBlock, NarrativeBlock, AudioBlock, CaptionsBlock, TimeWindow

def test_valid_schema():
    data = {
        "meta": {
            "clip_id": "c_0042",
            "source_video": "s5r4wdOWLjk.mp4",
            "target_ratio": "9:16",
            "export_fps": 30
        },
        "narrative": {
            "archetype": "contradiction_reversal",
            "pace_profile": "high_dynamic",
            "hook_window": { "start": 0.0, "end": 2.8 },
            "payoff_window": { "start": 24.5, "end": 29.2 }
        },
        "cuts": [
            { "source_start": 45.2, "source_end": 74.8, "target_start": 0.0 }
        ],
        "speed_ramps": [
            { "start": 0.0, "end": 2.8, "multiplier": 1.08, "curve": "ease-in-out" }
        ],
        "color_presets": [
            { "start": 0.0, "end": 29.6, "preset": "cinematic_warm", "contrast": 1.12, "saturation": 1.08 }
        ],
        "audio": {
            "volume_curve": [
                { "time": 0.0, "gain_db": 0.0 },
                { "time": 24.5, "gain_db": 1.5 }
            ],
            "filters": ["highpass", "dynamic_normalize", "limiter"]
        },
        "camera_moves": [
            {
                "start": 0.0,
                "end": 2.8,
                "type": "zoom_push",
                "start_zoom": 1.0,
                "end_zoom": 1.12,
                "center_x": "lerp(0.48, 0.52)",
                "center_y": 0.45,
                "curve": "smooth"
            },
            {
                "start": 12.4,
                "end": 12.6,
                "type": "whip_pan",
                "target_x": 0.32,
                "target_y": 0.45,
                "curve": "exponential"
            }
        ],
        "captions": {
            "style_profile": "neon_dynamic",
            "font_name": "Montserrat",
            "base_size": 80,
            "alignment": 2,
            "margin_v": 250,
            "lines": [
                {
                    "start": 0.0,
                    "end": 2.2,
                    "text": "Most people learn coding wrong",
                    "words": [
                        { "word": "Most", "start": 0.0, "end": 0.3, "size_multiplier": 1.0, "style": "ghost" },
                        { "word": "wrong", "start": 1.4, "end": 2.2, "size_multiplier": 1.8, "style": "danger" }
                    ]
                }
            ]
        },
        "overlays": [
            {
                "type": "image_watermark",
                "path": "static/branding/logo_icon.png",
                "x": "W-w-30",
                "y": "H-h-120",
                "opacity": 0.85
            }
        ]
    }
    
    blueprint = EditBlueprint(**data)
    assert blueprint.meta.clip_id == "c_0042"
    assert blueprint.narrative.archetype == "contradiction_reversal"
    assert len(blueprint.camera_moves) == 2
    assert blueprint.camera_moves[0].center_x == "lerp(0.48, 0.52)"
    assert blueprint.captions.lines[0].words[1].word == "wrong"
