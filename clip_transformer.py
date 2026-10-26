#!/usr/bin/env python3
"""Create a premium vertical clip with isolated speech and replacement captions.

External executables required: ffmpeg and the Demucs CLI (installed by `pip install
demucs`). The first Demucs/Whisper run downloads model weights, so an Internet
connection is needed once. Example:

    python clip_transformer.py input.mp4 --output output_premium.mp4

Suggested Python packages:
    pip install demucs easyocr openai-whisper opencv-python pillow numpy torch
"""

from __future__ import annotations

import argparse
import logging
import math
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LOGGER = logging.getLogger("clip_transformer")


@dataclass(frozen=True)
class Word:
    """A transcribed word and its timing in seconds."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Caption:
    """One readable group of timed transcript words."""

    words: tuple[Word, ...]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def run(command: list[str]) -> None:
    """Run a child process while preserving useful failure output."""
    LOGGER.info("Running: %s", " ".join(command))
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"Required executable not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Command failed ({error.returncode}): {' '.join(command)}") from error


def extract_audio(source: Path, audio_path: Path) -> None:
    """Decode the source audio to WAV, preserving a Demucs-friendly sample rate."""
    run(["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100", str(audio_path)])


def isolate_vocals(audio_path: Path, work_dir: Path, model: str, device: str) -> Path:
    """Use Demucs' two-stem model and return the isolated vocals WAV path."""
    demucs_output = work_dir / "demucs"
    run([
        sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", model,
        "-d", device, "-o", str(demucs_output), str(audio_path),
    ])
    candidates = list(demucs_output.rglob("vocals.wav"))
    if not candidates:
        raise RuntimeError("Demucs completed but did not produce vocals.wav.")
    return candidates[0]


def transcribe_words(vocals_path: Path, model_name: str, language: str | None) -> list[Word]:
    """Transcribe with Whisper and return word timestamps, with segment fallback."""
    try:
        import whisper
    except ImportError as error:
        raise RuntimeError("Install openai-whisper to generate new captions.") from error

    LOGGER.info("Loading Whisper model '%s'", model_name)
    model = whisper.load_model(model_name)
    result = model.transcribe(str(vocals_path), word_timestamps=True, language=language, verbose=False)
    words: list[Word] = []
    for segment in result.get("segments", []):
        timed_words = segment.get("words") or []
        if timed_words:
            words.extend(
                Word(item["word"].strip(), float(item["start"]), float(item["end"]))
                for item in timed_words if item.get("word", "").strip()
            )
            continue
        text_words = segment.get("text", "").split()
        start, end = float(segment["start"]), float(segment["end"])
        duration = (end - start) / max(1, len(text_words))
        words.extend(Word(text, start + index * duration, start + (index + 1) * duration)
                     for index, text in enumerate(text_words))
    if not words:
        raise RuntimeError("Whisper did not find speech in the isolated vocals track.")
    return words


def make_captions(words: Iterable[Word], max_words: int) -> list[Caption]:
    """Chunk words into fast, easy-to-read Hormozi-style caption groups."""
    captions: list[Caption] = []
    group: list[Word] = []
    for word in words:
        group.append(word)
        pause_after = len(group) > 1 and word.start - group[-2].end > 0.35
        terminal = word.text.rstrip().endswith((".", "!", "?", ",", ";", ":"))
        if len(group) >= max_words or pause_after or terminal:
            captions.append(Caption(tuple(group)))
            group = []
    if group:
        captions.append(Caption(tuple(group)))
    return captions


def cover_resize(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Scale and center-crop a frame to the exact vertical delivery size."""
    source_height, source_width = frame.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized = cv2.resize(frame, (round(source_width * scale), round(source_height * scale)), interpolation=cv2.INTER_LANCZOS4)
    offset_x = (resized.shape[1] - width) // 2
    offset_y = (resized.shape[0] - height) // 2
    return resized[offset_y:offset_y + height, offset_x:offset_x + width]


def apply_premium_zoom(frame: np.ndarray, seconds: float, amount: float) -> np.ndarray:
    """Add a gentle Ken-Burns punch-in without distracting camera movement.

    ``amount=.08`` produces a 4-8% zoom that changes slowly enough to feel like
    a second camera angle rather than a digital crop.
    """
    if amount <= 0:
        return frame
    zoom = 1.0 + amount * (0.75 + 0.25 * math.sin(seconds * math.tau / 5.5))
    height, width = frame.shape[:2]
    crop_width = max(2, round(width / zoom))
    crop_height = max(2, round(height / zoom))
    # A barely perceptible vertical drift prevents a static digital-zoom look.
    center_x = width // 2
    center_y = round(height * (0.52 + 0.012 * math.sin(seconds * math.tau / 8.0)))
    left = min(max(0, center_x - crop_width // 2), width - crop_width)
    top = min(max(0, center_y - crop_height // 2), height - crop_height)
    crop = frame[top:top + crop_height, left:left + crop_width]
    return cv2.resize(crop, (width, height), interpolation=cv2.INTER_LANCZOS4)


def apply_smart_crop(frame: np.ndarray, scale: float) -> np.ndarray:
    """Top-anchor a stronger crop to remove bottom-burned source subtitles.

    This is intentionally static: it is a reframing choice, not a censor effect.
    The normal subtle camera motion can still be applied afterward.
    """
    height, width = frame.shape[:2]
    crop_width = max(2, round(width / scale))
    crop_height = max(2, round(height / scale))
    left = (width - crop_width) // 2
    # Holding the crop at the top cuts the lower burned-in subtitle region.
    crop = frame[0:crop_height, left:left + crop_width]
    return cv2.resize(crop, (width, height), interpolation=cv2.INTER_LANCZOS4)


def lens_maps(width: int, height: int, strength: float) -> tuple[np.ndarray, np.ndarray]:
    """Build a mild barrel-distortion remap; strength around .035 looks premium."""
    grid_x, grid_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    normalized_x = (grid_x - width / 2) / (width / 2)
    normalized_y = (grid_y - height / 2) / (height / 2)
    radius_squared = normalized_x * normalized_x + normalized_y * normalized_y
    factor = 1.0 + strength * radius_squared
    map_x = (normalized_x * factor + 1.0) * width / 2
    map_y = (normalized_y * factor + 1.0) * height / 2
    return map_x.astype(np.float32), map_y.astype(np.float32)


def detect_text_boxes(reader, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find text only in the bottom half, returning padded, clamped rectangles."""
    height, width = frame.shape[:2]
    bottom = frame[height // 2:]
    # Detection-only avoids recognition work and is noticeably faster on long clips.
    detections = reader.readtext(bottom, detail=1, paragraph=False, text_threshold=0.45, low_text=0.25)
    boxes: list[tuple[int, int, int, int]] = []
    for polygon, _text, confidence in detections:
        if confidence < 0.30:
            continue
        points = np.asarray(polygon, dtype=np.int32)
        left, top = points.min(axis=0)
        right, lower = points.max(axis=0)
        pad_x, pad_y = int(width * 0.018), int(height * 0.012)
        boxes.append((max(0, left - pad_x), max(height // 2, top + height // 2 - pad_y),
                      min(width, right + pad_x), min(height, lower + height // 2 + pad_y)))
    return boxes


def blur_old_captions(frame: np.ndarray, boxes: list[tuple[int, int, int, int]]) -> np.ndarray:
    """Blur detected legacy captions and give each region a restrained glass panel."""
    output = frame.copy()
    overlay = output.copy()
    for left, top, right, bottom in boxes:
        if right <= left or bottom <= top:
            continue
        region = output[top:bottom, left:right]
        region = cv2.GaussianBlur(region, (0, 0), sigmaX=18, sigmaY=18)
        output[top:bottom, left:right] = region
        cv2.rectangle(overlay, (left, top), (right, bottom), (20, 20, 20), -1)
    if boxes:
        output = cv2.addWeighted(overlay, 0.20, output, 0.80, 0)
    return output


def locate_font(font_path: str | None) -> Path | None:
    if font_path:
        path = Path(font_path)
        if not path.is_file():
            raise FileNotFoundError(f"Caption font does not exist: {path}")
        return path
    candidates = [
        Path("fonts/Montserrat-Black.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def caption_for_time(captions: list[Caption], seconds: float, index: int) -> tuple[Caption | None, int]:
    while index < len(captions) and seconds > captions[index].end + 0.08:
        index += 1
    if index < len(captions) and captions[index].start - 0.08 <= seconds <= captions[index].end + 0.12:
        return captions[index], index
    return None, index


def draw_caption(frame: np.ndarray, caption: Caption | None, seconds: float, font_path: Path | None,
                 vertical_position: float) -> np.ndarray:
    """Paint centered uppercase text with a black stroke and timed yellow emphasis."""
    if caption is None:
        return frame
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    font_size = max(42, round(frame.shape[1] * 0.075))
    font = ImageFont.truetype(str(font_path), font_size) if font_path else ImageFont.load_default()
    active_index = min(len(caption.words) - 1, next(
        (index for index, word in enumerate(caption.words) if word.start <= seconds <= word.end), 0))
    tokens = [word.text.upper() for word in caption.words]
    widths = [draw.textbbox((0, 0), token, font=font, stroke_width=3)[2] for token in tokens]
    spacing = font_size // 3
    total_width = sum(widths) + spacing * (len(tokens) - 1)
    x = (frame.shape[1] - total_width) // 2
    # Reels/TikTok reserve much of the bottom quarter for UI. Keep captions in
    # the lower-middle safe zone instead of the source subtitle area.
    y = int(frame.shape[0] * vertical_position)
    for index, token in enumerate(tokens):
        color = (255, 218, 0, 255) if index == active_index else (255, 255, 255, 255)
        draw.text((x, y), token, font=font, fill=color, stroke_width=6, stroke_fill=(0, 0, 0, 255))
        x += widths[index] + spacing
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def process_video(source: Path, silent_output: Path, captions: list[Caption], font_path: Path | None,
                  width: int, height: int, lens_strength: float,
                  zoom_amount: float, smart_crop_scale: float | None, legacy_mask: str,
                  caption_y: float, ocr_interval: float, ocr_gpu: bool) -> None:
    """Apply visual effects and draw captions into a H.264-ready silent MP4."""
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {source}")
    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    # Preserve the source duration here. FFmpeg performs a duration-preserving
    # frame-rate conversion during the final H.264 encode.
    writer = cv2.VideoWriter(str(silent_output), cv2.VideoWriter_fourcc(*"mp4v"), source_fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Could not create temporary video. Check codec support.")
    reader = None
    if legacy_mask == "glass":
        try:
            import easyocr
        except ImportError as error:
            raise RuntimeError("Install easyocr to mask legacy subtitles.") from error
        reader = easyocr.Reader(["en"], gpu=ocr_gpu, verbose=False)
    map_x, map_y = lens_maps(width, height, lens_strength)
    frame_number, written, caption_index = 0, 0, 0
    last_ocr_time, boxes = -ocr_interval, []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            seconds = frame_number / source_fps
            frame_number += 1
            frame = cover_resize(frame, width, height)
            if smart_crop_scale:
                frame = apply_smart_crop(frame, smart_crop_scale)
            frame = apply_premium_zoom(frame, seconds, zoom_amount)
            frame = cv2.remap(frame, map_x, map_y, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT101)
            if reader is not None and seconds - last_ocr_time >= ocr_interval:
                boxes = detect_text_boxes(reader, frame)
                last_ocr_time = seconds
            if legacy_mask == "glass":
                frame = blur_old_captions(frame, boxes)
            caption, caption_index = caption_for_time(captions, seconds, caption_index)
            writer.write(draw_caption(frame, caption, seconds, font_path, caption_y))
            written += 1
            if written % int(max(1, source_fps * 10)) == 0:
                LOGGER.info("Rendered %.1f seconds", seconds)
    finally:
        capture.release()
        writer.release()
    if not written:
        raise RuntimeError("No video frames were rendered.")


def mux_video_and_audio(silent_video: Path, vocals: Path, output: Path, fps: float) -> None:
    """Encode the final deliverable with broadly compatible H.264/AAC settings."""
    run([
        "ffmpeg", "-y", "-i", str(silent_video), "-i", str(vocals), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(output),
    ])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Source MP4 clip")
    parser.add_argument("--output", type=Path, default=Path("output_premium.mp4"))
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--fps", type=float, default=30, choices=(30, 60))
    parser.add_argument("--demucs-model", default="htdemucs")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--whisper-model", default="small", help="tiny, base, small, medium, large")
    parser.add_argument("--language", default=None, help="Optional Whisper language code, e.g. en or hi")
    parser.add_argument("--font", default=None, help="Path to a Montserrat Black TTF/OTF file")
    parser.add_argument("--max-caption-words", type=int, default=4)
    parser.add_argument("--lens-strength", type=float, default=0.035)
    parser.add_argument("--zoom", type=float, default=0.08,
                        help="Maximum subtle punch-in amount (0.08 = 4-8%% zoom; use 0 to disable)")
    parser.add_argument("--smart-crop", action="store_true",
                        help="Top-anchor a strong crop to cut burned-in bottom captions off-screen")
    parser.add_argument("--smart-crop-scale", type=float, default=1.36,
                        help="Static scale used by --smart-crop; 1.36 is tuned for bottom subtitles")
    parser.add_argument("--legacy-mask", choices=("glass", "none"), default="glass",
                        help="How to handle old captions that remain in-frame")
    parser.add_argument("--caption-y", type=float, default=0.61,
                        help="Caption vertical position as frame height (default 0.61 is Reels/TikTok safe)")
    parser.add_argument("--ocr-interval", type=float, default=0.5, help="Seconds between OCR scans")
    parser.add_argument("--ocr-gpu", action="store_true", help="Use CUDA for EasyOCR")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(f"Input video does not exist: {args.input}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg must be installed and available on PATH.")
    if args.lens_strength < 0 or args.lens_strength > 0.12:
        raise ValueError("--lens-strength must be between 0 and 0.12 for a subtle result.")
    if args.zoom < 0 or args.zoom > 0.20:
        raise ValueError("--zoom must be between 0 and 0.20.")
    if args.smart_crop_scale < 1.0 or args.smart_crop_scale > 1.6:
        raise ValueError("--smart-crop-scale must be between 1.0 and 1.6.")
    if args.caption_y < 0.35 or args.caption_y > 0.75:
        raise ValueError("--caption-y must be between 0.35 and 0.75.")
    if args.max_caption_words < 1:
        raise ValueError("--max-caption-words must be at least 1.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    font_path = locate_font(args.font)
    if font_path is None:
        LOGGER.warning("Montserrat was not found; using Pillow's basic fallback font.")
    with tempfile.TemporaryDirectory(prefix="clip_transformer_") as temp:
        work_dir = Path(temp)
        extracted_audio = work_dir / "source.wav"
        silent_video = work_dir / "visuals.mp4"
        extract_audio(args.input, extracted_audio)
        vocals = isolate_vocals(extracted_audio, work_dir, args.demucs_model, args.device)
        captions = make_captions(transcribe_words(vocals, args.whisper_model, args.language), args.max_caption_words)
        process_video(args.input, silent_video, captions, font_path, args.width, args.height,
                      args.lens_strength, args.zoom,
                      args.smart_crop_scale if args.smart_crop else None,
                      "none" if args.smart_crop else args.legacy_mask,
                      args.caption_y, args.ocr_interval, args.ocr_gpu)
        mux_video_and_audio(silent_video, vocals, args.output, args.fps)
    LOGGER.info("Premium clip written to %s", args.output.resolve())
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        raise SystemExit(main())
    except Exception as error:
        LOGGER.error("%s", error)
        raise SystemExit(1)
