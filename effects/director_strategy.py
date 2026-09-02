from enum import Enum
from typing import List, Dict, Optional, Any

class DirectorMode(Enum):
    SINGLE_CENTERED = "SINGLE_CENTERED"
    PODCAST = "PODCAST"
    LEGACY = "LEGACY"

class DirectorContext:
    def __init__(self):
        self.mode: DirectorMode = DirectorMode.LEGACY
        self.anchors: List[Dict[str, Any]] = []
        self.active_speaker: str = "center"  # "left", "right", "center"
        self.crop_x: float = 0.5
        self.confidence: float = 0.0

class BaseDirectorStrategy:
    """Base strategy that computes state and updates the context."""
    def update_state(self, ctx: DirectorContext, current_frame_idx: int, l_motion_ema: float, r_motion_ema: float, talk_threshold: float) -> None:
        pass

class SingleCenteredStrategy(BaseDirectorStrategy):
    def update_state(self, ctx: DirectorContext, current_frame_idx: int, l_motion_ema: float, r_motion_ema: float, talk_threshold: float) -> None:
        # Fixed center crop, zero Haar calls.
        ctx.active_speaker = "center"
        ctx.crop_x = 0.5

class PodcastStrategy(BaseDirectorStrategy):
    def update_state(self, ctx: DirectorContext, current_frame_idx: int, l_motion_ema: float, r_motion_ema: float, talk_threshold: float) -> None:
        # Visual-motion-driven switching based on pre-locked anchors.
        if not ctx.anchors:
            return

        # Find the active anchor for the current frame
        active_anchor = next(
            (a for a in ctx.anchors if a["frame_range"][0] <= current_frame_idx <= a["frame_range"][1]),
            ctx.anchors[-1] if ctx.anchors else None
        )

        if not active_anchor:
            return

        left_x = active_anchor.get("left_x", 0.3)
        right_x = active_anchor.get("right_x", 0.7)

        if l_motion_ema > talk_threshold and r_motion_ema <= talk_threshold:
            ctx.active_speaker = "left"
            ctx.crop_x = left_x
        elif r_motion_ema > talk_threshold and l_motion_ema <= talk_threshold:
            ctx.active_speaker = "right"
            ctx.crop_x = right_x
        # Else: keep previous active_speaker (tie-break logic)

class LegacyStrategy(BaseDirectorStrategy):
    def update_state(self, ctx: DirectorContext, current_frame_idx: int, l_motion_ema: float, r_motion_ema: float, talk_threshold: float) -> None:
        # Existing per-frame Haar logic will handle crop assignment elsewhere.
        pass

def get_strategy(mode: DirectorMode) -> BaseDirectorStrategy:
    if mode == DirectorMode.SINGLE_CENTERED:
        return SingleCenteredStrategy()
    elif mode == DirectorMode.PODCAST:
        return PodcastStrategy()
    return LegacyStrategy()
