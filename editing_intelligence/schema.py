from typing import List, Optional, Any, Union
from pydantic import BaseModel, Field

class MetaBlock(BaseModel):
    clip_id: str
    source_video: str
    target_ratio: str = "9:16"
    export_fps: int = 30

class TimeWindow(BaseModel):
    start: float
    end: float

class NarrativeBlock(BaseModel):
    archetype: str
    pace_profile: str
    hook_window: TimeWindow
    payoff_window: TimeWindow

class CutBlock(BaseModel):
    source_start: float
    source_end: float
    target_start: float

class SpeedRampBlock(BaseModel):
    start: float
    end: float
    multiplier: float
    curve: str

class ColorPresetBlock(BaseModel):
    start: float
    end: float
    preset: str
    contrast: float
    saturation: float

class VolumeCurvePoint(BaseModel):
    time: float
    gain_db: float

class AudioBlock(BaseModel):
    volume_curve: List[VolumeCurvePoint]
    filters: List[str]

class CameraMoveBlock(BaseModel):
    start: float
    end: float
    type: str
    start_zoom: Optional[float] = None
    end_zoom: Optional[float] = None
    center_x: Optional[Union[float, str]] = None
    center_y: Optional[Union[float, str]] = None
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    curve: str

class WordStyle(BaseModel):
    word: str
    start: float
    end: float
    size_multiplier: float
    style: str

class CaptionLine(BaseModel):
    start: float
    end: float
    text: str
    words: List[WordStyle]

class CaptionsBlock(BaseModel):
    style_profile: str
    font_name: str
    base_size: int
    alignment: int
    margin_v: int
    lines: List[CaptionLine]

class OverlayBlock(BaseModel):
    type: str
    path: str
    x: str
    y: str
    opacity: float

class EditBlueprint(BaseModel):
    schema_version: str = Field(alias="$schema", default="https://hotshort.com/schemas/edit-blueprint-v1.json")
    meta: MetaBlock
    narrative: NarrativeBlock
    cuts: List[CutBlock] = Field(default_factory=list)
    speed_ramps: List[SpeedRampBlock] = Field(default_factory=list)
    color_presets: List[ColorPresetBlock] = Field(default_factory=list)
    audio: AudioBlock
    camera_moves: List[CameraMoveBlock] = Field(default_factory=list)
    captions: CaptionsBlock
    overlays: List[OverlayBlock] = Field(default_factory=list)
