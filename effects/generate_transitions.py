"""
effects/generate_transitions.py
===============================
Dynamically generates high-quality visual transition assets and sound effects
locally. This ensures 100% offline robustness without external network dependency.
"""

import os
import cv2
import numpy as np
import wave
import struct
import logging

log = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRANSITIONS_DIR = os.path.join(BASE_DIR, "assets", "transitions")


def generate_light_leak(out_path: str, width: int = 1080, height: int = 1920, fps: int = 30, duration: float = 1.0):
    """
    Generates a 1080x1920 cinematic warm light leak transition.
    Colors: true warm gold / amber / orange — NOT pink.
    Peaks at 0.5s with soft flare and fades cleanly to black.
    """
    log.info(f"[TRANSITION] Generating Light Leak overlay video -> {out_path}")
    total_frames = int(fps * duration)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

    try:
        for i in range(total_frames):
            t = i / max(total_frames - 1, 1)
            intensity = 1.0 - 2.0 * abs(t - 0.5)  # 0 -> 1 -> 0

            frame = np.zeros((height, width, 3), dtype=np.uint8)

            if intensity > 0.01:
                scale = 4
                sw, sh = width // scale, height // scale
                small_frame = np.zeros((sh, sw, 3), dtype=np.float32)

                # --- SOURCE 1: Bottom-Left Warm Gold Leak ---
                # True warm gold in OpenCV BGR: B=20, G=160, R=255
                cx1 = int(width * (0.1 + 0.3 * t))
                cy1 = int(height * (0.65 + 0.15 * t))
                radius1 = int(width * (0.6 + 0.9 * intensity))
                color1 = np.array([20.0, 160.0, 255.0]) * intensity  # BGR: warm gold
                cv2.circle(small_frame, (cx1 // scale, cy1 // scale), radius1 // scale, color1.tolist(), -1)

                if intensity > 0.4:
                    core_i = (intensity - 0.4) * 1.67
                    # Bright yellow-white core
                    color_core = np.array([80.0, 220.0, 255.0]) * core_i  # BGR: sunny yellow
                    cx2 = cx1 + int(width * 0.04)
                    cy2 = cy1 - int(height * 0.04)
                    radius2 = int(width * 0.30 * core_i)
                    cv2.circle(small_frame, (cx2 // scale, cy2 // scale), radius2 // scale, color_core.tolist(), -1)

                # --- SOURCE 2: Top-Right Amber/Orange Leak ---
                # True amber in OpenCV BGR: B=10, G=110, R=255
                cx3 = int(width * (0.88 - 0.18 * t))
                cy3 = int(height * (0.15 + 0.1 * t))
                radius3 = int(width * (0.4 + 0.55 * intensity))
                color3 = np.array([10.0, 110.0, 255.0]) * intensity  # BGR: amber orange
                cv2.circle(small_frame, (cx3 // scale, cy3 // scale), radius3 // scale, color3.tolist(), -1)

                if intensity > 0.5:
                    core_i2 = (intensity - 0.5) * 2.0
                    # Slightly cooler golden white for top highlight
                    color_core2 = np.array([60.0, 200.0, 255.0]) * core_i2  # BGR: golden white
                    cx4 = cx3 - int(width * 0.04)
                    cy4 = cy3 + int(height * 0.04)
                    radius4 = int(width * 0.20 * core_i2)
                    cv2.circle(small_frame, (cx4 // scale, cy4 // scale), radius4 // scale, color_core2.tolist(), -1)

                # --- SOURCE 3: Subtle center warm glow ---
                if intensity > 0.3:
                    center_i = (intensity - 0.3) * 1.43
                    cx5 = width // 2
                    cy5 = int(height * 0.45)
                    radius5 = int(width * 0.5 * center_i)
                    color5 = np.array([5.0, 80.0, 200.0]) * center_i  # BGR: dim warm orange
                    cv2.circle(small_frame, (cx5 // scale, cy5 // scale), radius5 // scale, color5.tolist(), -1)

                # Heavy blur for organic softness
                blur_size = int(sw * 0.75)
                if blur_size % 2 == 0:
                    blur_size += 1
                blurred = cv2.GaussianBlur(small_frame, (blur_size, blur_size), 0)
                frame = cv2.resize(np.clip(blurred, 0, 255).astype(np.uint8), (width, height))

            writer.write(frame)
    finally:
        writer.release()
    log.info("[TRANSITION] Light Leak generated successfully ✓")


def generate_camera_click(out_path: str, sample_rate: int = 44100):
    """
    Generates a highly realistic DSLR camera shutter click sound effect.
    Simulates the double-action mechanical shutter:
      1. Mirror slaps up (crisp attack + resonance)
      2. 45ms gap
      3. Mirror slaps down (lower pitch, slightly longer resonance)
    Total duration: ~0.18 seconds.
    """
    log.info(f"[TRANSITION] Generating Ultra-Realistic Camera Click SFX -> {out_path}")
    duration = 0.18
    total_samples = int(sample_rate * duration)
    y = np.zeros(total_samples, dtype=np.float64)
    t = np.arange(total_samples) / sample_rate

    def add_click(start_s, click_len_s, noise_env_decay, tone_freqs, tone_amps, overall_amp):
        start_idx = int(start_s * sample_rate)
        length = int(click_len_s * sample_rate)
        if start_idx + length > total_samples:
            length = total_samples - start_idx
        local_t = np.arange(length) / sample_rate
        
        # Noise burst for mechanical slap
        noise = np.random.uniform(-1.0, 1.0, length)
        noise_env = np.exp(-local_t * noise_env_decay)
        
        # Tonal resonances for camera body and aperture rings
        tone = np.zeros(length, dtype=np.float64)
        for freq, amp in zip(tone_freqs, tone_amps):
            tone += np.sin(2 * np.pi * freq * local_t) * amp
            
        tone_env = np.exp(-local_t * (noise_env_decay / 2.0))
        
        click = (noise * noise_env * 0.55 + tone * tone_env * 0.45) * overall_amp
        y[start_idx:start_idx+length] += click

    # 1st Click (Mirror Up): Sharp, high frequency snap
    add_click(start_s=0.0, click_len_s=0.04, noise_env_decay=400, 
              tone_freqs=[3200, 4500, 180], tone_amps=[1.0, 0.6, 0.8], overall_amp=1.0)
    
    # Tiny internal mechanical rattle just before mirror down
    add_click(start_s=0.035, click_len_s=0.015, noise_env_decay=600, 
              tone_freqs=[5000], tone_amps=[0.2], overall_amp=0.2)

    # 2nd Click (Mirror Down): Heavier, lower frequency thud
    add_click(start_s=0.055, click_len_s=0.06, noise_env_decay=300, 
              tone_freqs=[2800, 150, 80], tone_amps=[0.8, 1.2, 0.9], overall_amp=0.9)
    
    # Normalize
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.95

    # Write mono 16-bit WAV
    with wave.open(out_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for val in y:
            sample = int(max(-32768, min(32767, val * 32767)))
            wav.writeframes(struct.pack('<h', sample))
    log.info("[TRANSITION] Camera Click SFX generated successfully ✓")


def generate_swoosh_sfx(out_path: str, duration: float = 1.0, sample_rate: int = 44100):
    """
    Generates a 1-second professional high-frequency swoosh transition sound effect.
    Uses bandpass sweeping white noise with a smooth parabolic volume envelope.
    """
    log.info(f"[TRANSITION] Generating Swoosh sound effect -> {out_path}")
    total_samples = int(sample_rate * duration)

    noise = np.random.uniform(-1.0, 1.0, total_samples)
    y = np.zeros(total_samples, dtype=np.float32)

    prev = 0.0
    for i in range(total_samples):
        t = i / (total_samples - 1)
        progress = 1.0 - 2.0 * abs(t - 0.5)
        cutoff = 80.0 + 1720.0 * (progress ** 2)
        a = min(1.0, max(0.0, 2.0 * np.pi * cutoff / sample_rate))
        val = a * noise[i] + (1.0 - a) * prev
        y[i] = val
        prev = val

    envelope = np.sin(np.pi * np.arange(total_samples) / (total_samples - 1)) ** 2
    y = y * envelope * 0.45

    with wave.open(out_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for val in y:
            sample = int(np.clip(val * 32767.0, -32768, 32767))
            wav.writeframes(struct.pack('<h', sample))
    
    try:
        for i in range(total_frames):
            t = i / (total_frames - 1)
            intensity = 1.0 - 2.0 * abs(t - 0.5)  # 0 -> 1 -> 0
            
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            
            if intensity > 0.01:
                # Downscale drawing to apply massive gaussian blur efficiently
                scale = 4
                sw, sh = width // scale, height // scale
                small_frame = np.zeros((sh, sw, 3), dtype=np.float32)
                
                # --- SOURCE 1: Left-Bottom Golden Leak ---
                cx1 = int(width * (0.1 + 0.3 * t))
                cy1 = int(height * (0.6 + 0.2 * t))
                radius1 = int(width * (0.6 + 0.9 * intensity))
                # Swapped BGR format to counteract FFmpeg channel swap:
                # Target FFmpeg BGR: [10, 160, 255] (Warm Gold) -> OpenCV BGR: [160.0, 10.0, 255.0]
                color1 = np.array([160.0, 10.0, 255.0]) * intensity
                cv2.circle(small_frame, (cx1 // scale, cy1 // scale), radius1 // scale, color1.tolist(), -1)
                
                if intensity > 0.4:
                    core_intensity = (intensity - 0.4) * 1.67
                    cx2 = cx1 + int(width * 0.05)
                    cy2 = cy1 - int(height * 0.05)
                    radius2 = int(width * 0.35 * core_intensity)
                    # Target FFmpeg BGR: [100, 220, 255] (Sunny Yellow) -> OpenCV BGR: [220.0, 100.0, 255.0]
                    color2 = np.array([220.0, 100.0, 255.0]) * core_intensity
                    cv2.circle(small_frame, (cx2 // scale, cy2 // scale), radius2 // scale, color2.tolist(), -1)
                
                # --- SOURCE 2: Right-Top Amber Leak ---
                cx3 = int(width * (0.9 - 0.2 * t))
                cy3 = int(height * (0.2 + 0.1 * t))
                radius3 = int(width * (0.4 + 0.6 * intensity))
                # Target FFmpeg BGR: [10, 120, 255] (Amber Orange) -> OpenCV BGR: [120.0, 10.0, 255.0]
                color3 = np.array([120.0, 10.0, 255.0]) * intensity
                cv2.circle(small_frame, (cx3 // scale, cy3 // scale), radius3 // scale, color3.tolist(), -1)
                
                if intensity > 0.5:
                    core_intensity2 = (intensity - 0.5) * 2.0
                    cx4 = cx3 - int(width * 0.05)
                    cy4 = cy3 + int(height * 0.05)
                    radius4 = int(width * 0.25 * core_intensity2)
                    # Target FFmpeg BGR: [140, 240, 255] (Golden White) -> OpenCV BGR: [240.0, 140.0, 255.0]
                    color4 = np.array([240.0, 140.0, 255.0]) * core_intensity2
                    cv2.circle(small_frame, (cx4 // scale, cy4 // scale), radius4 // scale, color4.tolist(), -1)
                
                # Apply heavy blur to blend colors smoothly
                blur_size = int(sw * 0.7)
                if blur_size % 2 == 0:
                    blur_size += 1
                blurred = cv2.GaussianBlur(small_frame, (blur_size, blur_size), 0)
                
                # Upscale back to target resolution
                frame = cv2.resize((np.clip(blurred, 0, 255)).astype(np.uint8), (width, height))
                
            writer.write(frame)
    finally:
        writer.release()
    log.info("[TRANSITION] Light Leak generated successfully ✓")


def generate_swoosh_sfx(out_path: str, duration: float = 1.0, sample_rate: int = 44100):
    """
    Generates a 1-second professional high-frequency swoosh transition sound effect.
    Uses bandpass sweeping white noise with a smooth parabolic volume envelope.
    """
    log.info(f"[TRANSITION] Generating Swoosh sound effect -> {out_path}")
    total_samples = int(sample_rate * duration)
    
    # Generate white noise
    noise = np.random.uniform(-1.0, 1.0, total_samples)
    y = np.zeros(total_samples, dtype=np.float32)
    
    # Sweep filter logic (low -> high -> low frequency sweep)
    prev = 0.0
    for i in range(total_samples):
        t = i / (total_samples - 1)
        progress = 1.0 - 2.0 * abs(t - 0.5)  # 0 -> 1 -> 0
        cutoff = 80.0 + 1720.0 * (progress ** 2)
        
        # Simple IIR filter coefficient
        a = min(1.0, max(0.0, 2.0 * np.pi * cutoff / sample_rate))
        val = a * noise[i] + (1.0 - a) * prev
        y[i] = val
        prev = val
        
    # Amplitude envelope to rise and fall smoothly
    envelope = np.sin(np.pi * np.arange(total_samples) / (total_samples - 1)) ** 2
    y = y * envelope * 0.45  # Volume scale
    
    # Write mono 16-bit PCM WAV
    with wave.open(out_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for val in y:
            sample = int(np.clip(val * 32767.0, -32768, 32767))
            wav.writeframes(struct.pack('<h', sample))
    log.info("[TRANSITION] Swoosh sound effect generated successfully ✓")


def ensure_transition_assets() -> tuple:
    """Ensure transition assets exist, generating them on-demand if missing."""
    os.makedirs(TRANSITIONS_DIR, exist_ok=True)

    leak_path   = os.path.join(TRANSITIONS_DIR, "light_leak_1080x1920_v3.mp4")
    swoosh_path = os.path.join(TRANSITIONS_DIR, "swoosh.wav")
    click_path  = os.path.join(TRANSITIONS_DIR, "camera_click.wav")

    # Force-regenerate light leak — earlier versions had wrong BGR colors (pink).
    # Delete stale asset so it gets rebuilt with correct warm gold colors.
    if os.path.exists(leak_path):
        try:
            import cv2 as _cv2_check
            cap = _cv2_check.VideoCapture(leak_path)
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                # Check if the peak color is pink (B > 180, G < 50, R > 200)
                peak_b = int(frame[:, :, 0].max())
                peak_g = int(frame[:, :, 1].max())
                peak_r = int(frame[:, :, 2].max())
                is_pink = peak_b > 180 and peak_g < 50 and peak_r > 200
                if is_pink:
                    log.info("[TRANSITION] Stale pink light_leak detected — forcing regeneration")
                    os.remove(leak_path)
        except Exception:
            pass  # If check fails, keep existing

    if not os.path.exists(leak_path):
        generate_light_leak(leak_path)
    if not os.path.exists(swoosh_path):
        generate_swoosh_sfx(swoosh_path)
    if not os.path.exists(click_path):
        generate_camera_click(click_path)

    return leak_path, swoosh_path, click_path
