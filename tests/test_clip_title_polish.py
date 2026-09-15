import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.clip_builder import ClipBuilder


def test_title_is_more_user_friendly_and_short():
    builder = ClipBuilder()
    clip = builder.build_clip(
        clip_id="clip_1",
        start_time=12.0,
        end_time=27.0,
        text="Most people think they need more motivation, but the real secret is building systems that make action automatic.",
        hook_score=0.9,
        retention_score=0.85,
        clarity_score=0.8,
        emotion_score=0.75,
        rank=1,
        is_best=True,
    )

    assert clip.title.startswith("Most people")
    assert len(clip.title) <= 72
    assert "..." not in clip.title
    assert clip.title.endswith((".", "!", "?")) is False
    assert clip.selection_reason.primary.lower().startswith("exceptional") or "hook" in clip.selection_reason.primary.lower()
