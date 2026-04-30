# viral_finder/transcription_router.py
"""
🚀 Intelligent Transcription Engine Router

Chooses optimal transcription engine based on:
- Video duration
- Segment count
- Silence ratio  
- Speech density
- Arc complexity

SaaS-optimized economics: Fast for short, Cheap for medium, GPU-accelerated for long
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple
from viral_finder.pipeline_context import PipelineContext

log = logging.getLogger("transcription_router")

# ===================================
# CONFIGURATION
# ===================================

# Override via env vars if needed
TRANSCRIPTION_ROUTER_ENABLED = os.getenv("HS_TRANSCRIPTION_ROUTER_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
TRANSCRIPTION_ROUTER_DEBUG = os.getenv("HS_TRANSCRIPTION_ROUTER_DEBUG", "0").strip().lower() in ("1", "true", "yes", "on")
FORCE_RUNPOD_TRANSCRIPTION = os.getenv("HS_TRANSCRIPTION_FORCE_RUNPOD", "1").strip().lower() in ("1", "true", "yes", "on")

# Duration thresholds (seconds)
DURATION_SHORT_MAX = float(os.getenv("HS_TRANSCRIPTION_SHORT_MAX", "180") or 180)      # 3 min
DURATION_MEDIUM_MAX = float(os.getenv("HS_TRANSCRIPTION_MEDIUM_MAX", "600") or 600)   # 10 min
DURATION_LONG_MIN = float(os.getenv("HS_TRANSCRIPTION_LONG_MIN", "600") or 600)       # 10 min

# Signal-based override thresholds
SEGMENT_COUNT_RUNPOD_THRESHOLD = int(os.getenv("HS_SEGMENT_COUNT_RUNPOD", "120") or 120)
SILENCE_RATIO_CPU_THRESHOLD = float(os.getenv("HS_SILENCE_RATIO_CPU", "0.02") or 0.02)  # 2% silence
SPEECH_DENSITY_HIGH_THRESHOLD = float(os.getenv("HS_SPEECH_DENSITY_HIGH", "0.75") or 0.75)  # 75%

# Model selection
MODEL_TINY = "tiny"
MODEL_BASE = "base"
MODEL_SMALL = "small"

# Engine types
ENGINE_CPU_TINY = "cpu_tiny"
ENGINE_CPU_BASE = "cpu_base"
ENGINE_CPU_BASE_PARALLEL = "cpu_base_parallel"
ENGINE_RUNPOD_GPU = "runpod_gpu_medium"
ENGINE_LEGACY = "legacy"


# ===================================
# DECISION LOGIC
# ===================================

def choose_transcription_engine(
    duration: float,
    segment_count: Optional[int] = None,
    silence_ratio: Optional[float] = None,
    speech_density: Optional[float] = None,
) -> str:
    """
    Intelligent routing based on computational complexity.
    
    Decision tree (priority order):
    1. Duration > 600s → GPU (long videos need speed)
    2. Segment count > 120 → GPU (complex content)
    3. Speech density > 75% → GPU (more tokens = more compute)
    4. Silence ratio < 2% → CPU tiny (mostly speech, simple model)
    5. Else → CPU base parallel (balanced)
    
    Args:
        duration: Video duration in seconds
        segment_count: Number of transcribed segments (optional)
        silence_ratio: Proportion of silence (optional)
        speech_density: High speech density indicator (optional)
        
    Returns:
        Engine choice: "cpu_tiny", "cpu_base_parallel", "runpod_gpu_medium", etc.
    """
    if not TRANSCRIPTION_ROUTER_ENABLED:
        return ENGINE_LEGACY

    # The business decision is no longer optional: route transcription to RunPod GPU
    # unless explicitly disabled for local development/testing.
    if FORCE_RUNPOD_TRANSCRIPTION:
        log.info("[ROUTER] -> GPU (forced RunPod transcription)")
        return ENGINE_RUNPOD_GPU
    
    # Rule 1: Long videos → GPU (need speed)
    if duration > DURATION_LONG_MIN:
        log.info(
            "[ROUTER] → GPU (duration=%.1fs > %.1fs)",
            duration,
            DURATION_LONG_MIN,
        )
        return ENGINE_RUNPOD_GPU
    
    # Rule 2: Many segments → GPU (complex content)
    if segment_count is not None and segment_count > SEGMENT_COUNT_RUNPOD_THRESHOLD:
        log.info(
            "[ROUTER] → GPU (segment_count=%d > %d)",
            segment_count,
            SEGMENT_COUNT_RUNPOD_THRESHOLD,
        )
        return ENGINE_RUNPOD_GPU
    
    # Rule 3: HIGH SPEECH DENSITY → GPU (more tokens = more compute)
    # This is the KEY: speech_density > 0.75 means expensive processing
    if speech_density is not None and speech_density > SPEECH_DENSITY_HIGH_THRESHOLD:
        log.info(
            "[ROUTER] → GPU (speech_density=%.2f > %.2f means high compute complexity)",
            speech_density,
            SPEECH_DENSITY_HIGH_THRESHOLD,
        )
        return ENGINE_RUNPOD_GPU
    
    # Rule 4: Very low silence ratio → CPU tiny (mostly speech, simple model OK)
    if silence_ratio is not None and silence_ratio < SILENCE_RATIO_CPU_THRESHOLD:
        log.info(
            "[ROUTER] → CPU tiny (silence_ratio=%.2f < %.2f, mostly speech)",
            silence_ratio,
            SILENCE_RATIO_CPU_THRESHOLD,
        )
        return ENGINE_CPU_TINY
    
    # Rule 5: Default → CPU base parallel (balanced)
    log.info(
        "[ROUTER] → CPU base parallel (balanced default | duration=%.1fs, silence=%.2f, speech=%.2f)",
        duration,
        silence_ratio if silence_ratio is not None else 0.0,
        speech_density if speech_density is not None else 0.0,
    )
    return ENGINE_CPU_BASE_PARALLEL


def get_transcription_config(engine: str) -> Dict[str, Any]:
    """
    Get engine-specific configuration (model, compute_type, etc).
    
    Args:
        engine: Engine choice from choose_transcription_engine()
        
    Returns:
        Dict with model, device, compute_type, num_workers, etc.
    """
    config = {
        ENGINE_LEGACY: {
            "model": MODEL_BASE,
            "device": "cpu",
            "compute_type": "int8",
            "num_workers": 1,
            "description": "Legacy mode (no routing)",
        },
        ENGINE_CPU_TINY: {
            "model": MODEL_TINY,
            "device": "cpu",
            "compute_type": "int8",
            "num_workers": 1,
            "description": "Tiny model, single-threaded, fastest startup",
        },
        ENGINE_CPU_BASE: {
            "model": MODEL_BASE,
            "device": "cpu",
            "compute_type": "int8",
            "num_workers": 1,
            "description": "Base model, single-threaded, balanced",
        },
        ENGINE_CPU_BASE_PARALLEL: {
            "model": MODEL_BASE,
            "device": "cpu",
            "compute_type": "int8",
            "num_workers": 4,  # Respect HS_ORCH_ENRICH_WORKERS setting
            "description": "Base model, parallel enrichment workers",
        },
        ENGINE_RUNPOD_GPU: {
            "model": MODEL_SMALL,
            "device": "cuda",
            "compute_type": "float16",
            "num_workers": 1,
            "endpoint": os.getenv("RUNPOD_ENDPOINT_ID", ""),
            "description": "RunPod GPU medium, remote processing",
        },
    }
    
    return config.get(engine, config[ENGINE_LEGACY])


def log_routing_decision(
    engine: str,
    duration: float,
    segment_count: Optional[int] = None,
    silence_ratio: Optional[float] = None,
    speech_density: Optional[float] = None,
) -> None:
    """Log transcription routing decision."""
    config = get_transcription_config(engine)
    
    parts = [
        f"engine={engine}",
        f"duration={duration:.1f}s",
    ]
    
    if segment_count is not None:
        parts.append(f"segments={segment_count}")
    if silence_ratio is not None:
        parts.append(f"silence_ratio={silence_ratio:.2%}")
    if speech_density is not None:
        parts.append(f"speech_density={speech_density:.2%}")
    
    log.info("[ROUTER] Transcription routing: %s | %s", " ".join(parts), config["description"])


# ===================================
# CONTEXT HELPERS
# ===================================

def should_use_runpod_for_transcription() -> bool:
    """Check if RunPod should be used based on configuration."""
    runpod_enabled = os.getenv("HS_TRANSCRIPTION_RUNPOD_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
    runpod_endpoint = os.getenv("RUNPOD_ENDPOINT_ID", "").strip()
    runpod_key = os.getenv("RUNPOD_API_KEY", "").strip()
    
    return runpod_enabled and bool(runpod_endpoint and runpod_key)


def get_num_enrichment_workers() -> int:
    """Get number of enrichment workers from config."""
    try:
        return int(os.getenv("HS_ORCH_ENRICH_WORKERS", "4") or 4)
    except Exception:
        return 4


def get_vad_profile() -> str:
    """Get VAD profile (quality | turbo)."""
    return os.getenv("HS_VAD_PROFILE", "quality").strip().lower()


# ===================================
# INTEGRATION POINTS
# ===================================

def apply_transcription_routing(ctx: PipelineContext) -> str:
    """
    Apply intelligent routing to pipeline context.
    
    Updates ctx.transcription_engine based on available signals.
    
    Args:
        ctx: Pipeline context object with duration, segments, etc.
        
    Returns:
        Chosen engine string
    """
    if not TRANSCRIPTION_ROUTER_ENABLED:
        return ENGINE_LEGACY
    
    duration = getattr(ctx, "duration", 0.0)
    segment_count = None
    silence_ratio = None
    speech_density = None
    
    # Try to get VAD signals if available
    if hasattr(ctx, "vad_signals"):
        signals = ctx.vad_signals or {}
        silence_ratio = signals.get("silence_ratio")
        speech_density = signals.get("speech_density")
    
    # Try to get segment count
    if hasattr(ctx, "segments"):
        segments = ctx.segments or []
        segment_count = len(segments)
    
    # Choose engine
    engine = choose_transcription_engine(
        duration=duration,
        segment_count=segment_count,
        silence_ratio=silence_ratio,
        speech_density=speech_density,
    )
    
    # Log decision
    log_routing_decision(
        engine=engine,
        duration=duration,
        segment_count=segment_count,
        silence_ratio=silence_ratio,
        speech_density=speech_density,
    )
    
    # Update context
    ctx.transcription_engine = engine
    ctx.transcription_config = get_transcription_config(engine)
    
    if TRANSCRIPTION_ROUTER_DEBUG:
        log.debug("[ROUTER] Config: %s", ctx.transcription_config)
    
    return engine
