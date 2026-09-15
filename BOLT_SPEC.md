# ⚡ BOLT Runtime Specification v1 (`BOLT_SPEC.md`)

> **Contract:** The BOLT Runtime is library-agnostic. It does not know about OpenCV, PyAV, FFmpeg, or NumPy. It observes **events**, tracks **resources**, derives **mathematical metrics**, and enforces **data-driven laws**.
> Any backend, module, or algorithm in HotShort must emit these standardized events to be compliant with BOLT Governance.

---

## 🏛️ 1. Architecture

```
HotShort Pipeline & Algorithms
       │  (emits standardized events)
       ▼
⚡ BOLT Runtime (`bolt_runtime.py`)
  ├── 📬 Event Bus (Lightweight synchronous pub/sub)
  ├── 🗂️ Resource Registry (Authoritative gatekeeper mapping)
  ├── 🧮 Metrics Collector (Aggregates raw counts & wall-time)
  └── ⏱️ Timeline Recorder (Stage execution & concurrency tracking)
       │
       ▼
⚡ BOLT Report Engine (`bolt_report.py`)
  ├── 📐 Derived Metrics Calculator (Efficiency ratios & deltas)
  ├── ⚖️ Data-Driven Law Evaluator (Evaluates YAML violation triggers)
  └── 📑 Gatekeeper Decision Generator (APPROVED / REJECTED)
       │
       ▼
`bolt_report.json` & CI Summary Output
```

---

## 📇 2. Standardized Event Vocabulary

Every module must interact with observability exclusively through `bolt.emit(event_name, **payload)`.

| Event Name | Required Payload Fields | Description |
| :--- | :--- | :--- |
| `stage_enter` | `stage_name`, `owner` | Marked when an execution stage begins (via context manager). |
| `stage_exit` | `stage_name`, `duration_ms` | Marked when an execution stage completes. |
| `video_open` | `resource_id`, `file_path`, `owner` | Emitted whenever a video file is opened by any backend. |
| `video_close` | `resource_id`, `file_path` | Emitted when a video stream handle is closed/released. |
| `frame_decoded` | `resource_id`, `count`, `timestamp_ms` | Emitted when a video frame is decoded into memory. |
| `frame_consumed` | `resource_id`, `consumer_module` | Emitted when an algorithm actually evaluates a frame. |
| `frame_cached` | `resource_id`, `cache_key`, `bytes` | Emitted when a frame is written to a ring buffer or cache. |
| `cache_hit` | `cache_id`, `key`, `consumer_module` | Emitted when a module successfully reads from cache instead of recomputing. |
| `cache_miss` | `cache_id`, `key`, `consumer_module` | Emitted when a requested feature/frame is not found in cache. |
| `feature_computed`| `feature_name`, `owner`, `duration_ms`| Emitted when an expensive analytical feature (Haar, RMS) is generated. |
| `feature_reused` | `feature_name`, `consumer_module` | Emitted when a downstream module consumes an existing feature. |
| `encode_started` | `encoder`, `output_path` | Emitted when an encoding pass or video rendering job begins. |
| `encode_finished` | `encoder`, `output_path`, `duration_ms` | Emitted when an encoding job finishes. |
| `disk_read` | `file_path`, `bytes` | Emitted on disk file reads (excluding initial stream mapping). |
| `disk_write` | `file_path`, `bytes`, `is_temp` | Emitted whenever data or video is written to disk. |

---

## 📦 3. Authoritative Resource Registry

Every resource emitted in an event must map to an authoritative Gatekeeper.

```yaml
resources:
  video_stream:
    owner: "Decode Detective"
    description: "Raw video demuxing and stream reader handles."
    allowed_producers: ["VideoContext", "FrameProvider"]
  
  decoded_frames:
    owner: "Decode Detective"
    description: "Uncompressed YUV/BGR frame buffers in RAM or VRAM."
    allowed_producers: ["FrameProvider", "PyAVBackend", "OpenCVBackend"]
  
  face_cache:
    owner: "Waste Hunter"
    description: "Bounding boxes, cluster IDs, and coordinates for detected faces."
    allowed_producers: ["FaceTracker", "ChunkWorker"]
  
  audio_features:
    owner: "Waste Hunter"
    description: "RMS energy, speech VAD timestamps, and transcript alignments."
    allowed_producers: ["AudioAnalyzer", "TranscriptEngine"]
  
  encoder_pipeline:
    owner: "Encode Killer"
    description: "Video rendering, concat, filtergraphs, and muxing jobs."
    allowed_producers: ["LightningRenderer", "FFmpegExecutor"]
  
  telemetry_timeline:
    owner: "Pipeline Profiler"
    description: "Stage execution wall-time, memory deltas, and IPC metrics."
    allowed_producers: ["BoltRuntime"]
```

---

## 📐 4. Derived Mathematical Metrics

The Report Engine computes intelligence from raw event counts and timings:

### 1. Decode Efficiency Ratio
$$\text{Decode Efficiency} = \frac{\text{frames\_consumed}}{\text{frames\_decoded}}$$
* **Target:** $\ge 0.95$ (Every decoded frame must be consumed by an algorithm).

### 2. Cache Effectiveness Rate
$$\text{Cache Hit Rate} = \frac{\text{cache\_hit}}{\text{cache\_hit} + \text{cache\_miss}}$$
* **Target:** $\ge 0.85$ across multi-pass pipeline runs.

### 3. Computational Reuse Ratio
$$\text{Reuse Ratio} = \frac{\text{feature\_reused}}{\text{feature\_computed} + \text{feature\_reused}}$$
* **Target:** $\ge 0.50$ (Every expensive feature should be consumed by at least 2 downstream modules).

### 4. Disk Write Overhead (Temp Ratio)
$$\text{Temp Disk Waste} = \frac{\sum \text{disk\_write(is\_temp=True)}}{\sum \text{disk\_write(is\_temp=False)} + 1}$$
* **Target:** $0.00$ (Zero temporary intermediate video writes allowed).

---

## ⚖️ 5. Data-Driven Violation Laws

Laws are evaluated dynamically from aggregated event metrics rather than hardcoded if-statements.

```yaml
laws:
  LAW_1_SINGLE_DECODER:
    name: "Single Decoder Ownership"
    owner: "Decode Detective"
    severity: "CRITICAL"
    trigger: "metrics['video_open'] > 1 and not env.get('BOLT_ALLOW_MULTI_OPEN')"
    rejection_reason: "Video opened multiple times. Must request stream via VideoContext."
    required_fix: "Remove unauthorized video open calls; consume shared VideoContext."

  LAW_2_NO_REOPEN:
    name: "Prohibition of Reopening"
    owner: "Decode Detective"
    severity: "CRITICAL"
    trigger: "any(count > 1 for count in metrics['opens_per_path'].values())"
    rejection_reason: "Same file path opened more than once in pipeline lifecycle."
    required_fix: "Pass existing stream handle or FrameProvider reference."

  LAW_3_FEATURE_REUSE:
    name: "Feature Immutability & Reuse"
    owner: "Waste Hunter"
    severity: "HIGH"
    trigger: "metrics['feature_computed_counts'].get('face_detection', 0) > 1"
    rejection_reason: "Haar face detection computed redundantly on same clip."
    required_fix: "Consume face coordinates from FaceCache; do not re-run cascade."

  LAW_5_SINGLE_ENCODE:
    name: "Encoding Justification"
    owner: "Encode Killer"
    severity: "CRITICAL"
    trigger: "metrics['encode_started'] > 1"
    rejection_reason: "Multiple encoding passes detected on a single output clip."
    required_fix: "Consolidate overlays, subtitles, and concats into one FFmpeg filtergraph."

  LAW_6_MANDATORY_TELEMETRY:
    name: "Mandatory Telemetry"
    owner: "Pipeline Profiler"
    severity: "HIGH"
    trigger: "metrics['unmonitored_stage_time_ms'] > 500"
    rejection_reason: "Pipeline execution exceeded 500ms without an active BOLT stage context."
    required_fix: "Wrap execution blocks in 'with bolt.stage(name, owner):'."
```

---

## 📑 6. Final Report Schema (`bolt_report.json`)

```json
{
  "spec_version": "1.0",
  "pipeline_run_id": "uuid-here",
  "timestamp": "2026-07-26T21:00:00Z",
  "wall_time_ms": 108600,
  "resource_health": {
    "video_stream": { "status": "UNHEALTHY", "color": "RED", "opens": 4 },
    "decoded_frames": { "status": "DEGRADED", "color": "ORANGE", "efficiency_ratio": 0.114 },
    "computed_features": { "status": "DEGRADED", "color": "ORANGE", "reuse_ratio": 0.0 },
    "encoder_pipeline": { "status": "DEGRADED", "color": "ORANGE", "encodes": 2 },
    "telemetry_timeline": { "status": "HEALTHY", "color": "GREEN", "coverage": 1.0 }
  },
  "derived_metrics": {
    "decode_efficiency_ratio": 0.114,
    "cache_hit_rate": 0.00,
    "computational_reuse_ratio": 0.00,
    "temp_disk_waste_ratio": 1.00
  },
  "violations": [
    {
      "law_id": "LAW_1_SINGLE_DECODER",
      "owner": "Decode Detective",
      "severity": "CRITICAL",
      "reason": "Video opened 4 times. Must request stream via VideoContext.",
      "required_fix": "Remove unauthorized video open calls; consume shared VideoContext."
    }
  ],
  "decision": {
    "status": "REJECTED",
    "icon": "❌",
    "primary_violation": "LAW_1_SINGLE_DECODER",
    "gatekeeper_owner": "Decode Detective"
  }
}
```
