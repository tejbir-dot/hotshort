# ⚡ Project BOLT — The Performance Operating System

> **MISSION**
> BOLT is HotShort's Performance Operating System.
> It governs every expensive resource:
> • **Video**
> • **Frames**
> • **Compute**
> • **Memory**
> • **Encoding**
> • **Disk I/O**
>
> No expensive operation may enter the codebase without being measured, justified, and assigned an owner.
> **If work cannot be justified, it must not exist.**

---

## 🏛️ Resource Ownership

Every resource in HotShort is strictly owned by an authoritative Gatekeeper. No module may access or manipulate a resource bypassing its owner.

| Resource | Gatekeeper Owner | Access Rule |
| :--- | :--- | :--- |
| **Video Stream** | Decode Detective | No module may open a video directly (`VideoCapture`, `av.open`). Must request via `VideoContext`. |
| **Decoded Frames** | Decode Detective | Decoded frames live in the shared ring buffer. Never decode the same frame timestamp twice. |
| **Encoded Output** | Encode Killer | No module may spawn an FFmpeg encode or write temporary video files to disk independently. |
| **Performance Metrics** | Pipeline Profiler | Every stage must wrap execution in BOLT telemetry. Invisible execution is forbidden. |
| **Computed Features** | Waste Hunter | Face positions, audio RMS, embeddings, and scene cuts are immutable once computed. Must be shared via cache. |

---

## ⚖️ BOLT LAWS (Non-Negotiable)

These are enforceable architectural laws. Any pull request or code change violating these laws is automatically rejected by BOLT CI.

### LAW 1 — Single Decoder Ownership
Only one module (`VideoContext` governed by Decode Detective) may own video decoding.
* **Violation:** Any new `VideoCapture()`, `av.open()`, or decoder instance outside `VideoContext`.
* **Result:** PR REJECTED.

### LAW 2 — Prohibition of Reopening
No algorithm may reopen a video file or stream. It must request frames or metadata from `VideoContext`.
* **Violation:** Second open call on the same file path.
* **Result:** PR REJECTED.

### LAW 3 — Feature Immutability & Reuse
Computed features are immutable and public. If `FaceTracker` or `local_worker` computes face coordinates or audio energy, downstream algorithms (`CropPlanner`, `ThumbnailGenerator`) must consume from cache. They may never recompute.
* **Violation:** Re-running Haar cascade, embedding generation, or audio RMS on previously analyzed timestamps.
* **Result:** PR REJECTED.

### LAW 4 — Explicit Computation Contracts
Every expensive computation or model must declare in its header/config:
* **Owner:** (Responsible module)
* **Consumers:** (Downstream modules reading it)
* **Cache Policy:** (RAM ring buffer / VRAM / Disk persistence)
* **Invalidation Policy:** (When it expires)

### LAW 5 — Encoding Justification & Filtergraph Consolidation
Every FFmpeg encode must justify its existence. If a filtergraph can merge cropping, ASS subtitles, overlays, and concats into an existing pass, an additional encode or temporary disk render is strictly forbidden.
* **Violation:** Multi-pass encoding or intermediate video disk writes (`wce_work/wc_cut_*.mp4`).
* **Result:** PR REJECTED.

### LAW 6 — Mandatory Telemetry
Every pipeline stage must expose telemetry via the Bolt Runtime (`with bolt.stage(...)`). No invisible work is allowed.
* **Violation:** Unmonitored execution blocks exceeding 100ms.
* **Result:** PR REJECTED.

---

## 🤖 Gatekeeper Agents (Active Enforcement)

BOLT agents are not passive advisors; they are active automated gatekeepers with pass/fail decision authority on every commit.

### 1. Decode Detective 🔍 (Owner: Video & Frames)
- **Role:** Enforces LAW 1 and LAW 2.
- **Enforcement Action:** Scans AST and runtime execution traces for unauthorized video opens or redundant frame decoding.
- **Gatekeeper Decision Example:**
  ```text
  DECISION     : REJECTED ❌
  Reason       : Introduced one unauthorized cv2.VideoCapture() in crop_planner.py
  Violation    : LAW 2 (Prohibition of Reopening)
  Owner        : Decode Detective
  Required Fix : Remove open call; consume frames via VideoContext.get_frame().
  ```

### 2. Encode Killer ⚔️ (Owner: Encoding & Disk I/O)
- **Role:** Enforces LAW 5.
- **Enforcement Action:** Intercepts subprocess calls and checks if intermediate MP4 files or secondary encodes are spawned.
- **Gatekeeper Decision Example:**
  ```text
  DECISION     : REJECTED ❌
  Reason       : Spawned secondary FFmpeg encode for branding watermark.
  Violation    : LAW 5 (Encoding Justification)
  Owner        : Encode Killer
  Required Fix : Merge watermark overlay into the primary crop/subtitle filtergraph.
  ```

### 3. Pipeline Profiler 📈 (Owner: Performance Metrics & Telemetry)
- **Role:** Enforces LAW 6 and monitors latency KPIs.
- **Enforcement Action:** Measures empirical wall-clock time, RAM/VRAM deltas, and IPC overhead. Rejects commits that cause unexplained regressions without architectural justification.

### 4. Waste Hunter 🗑️ (Owner: Computed Features & Memory)
- **Role:** Enforces LAW 3 and LAW 4.
- **Enforcement Action:** Monitors feature caches (`FaceCache`, audio RMS). Rejects duplicate feature extractions or un-cached analytical loops.

---

## 🧠 Persistent Performance Memory (Knowledge Base)

BOLT maintains a permanent database of empirical investigations and solved architectural problems. Before launching any optimization investigation, BOLT checks Performance Memory to ensure teams never repeat past work.

### Record Schema:
```yaml
Optimization_ID: OPT-001
Title: "Replace OpenCV VideoCapture with PyAV in FrameProvider"
Measured_Date: "2026-07-26"
Gain: "3.85x decode throughput (64.5 FPS → 248.6 FPS)"
Evidence: "3-way isolation benchmark on 10,000 consecutive 1080p frames"
Status: "Verified / Ready for Integration in Phase 3"
Owner: "Decode Detective"
Reference_Log: "scratch/benchmark_3way.py"
```

---

## 🗺️ The Project BOLT Roadmap (Observability Before Surgery)

Never change architecture without a baseline. You must measure before surgery so you can objectively prove every delta.

```
Phase 0: Bolt Runtime (Telemetry & Observability Layer) 👈 [CURRENT FOCUS]
  ↓
Phase 1: VideoContext (Eliminate Duplicate Opens — Verified by Bolt)
  ↓
Phase 2: FrameProvider (Acquisition Abstraction Layer)
  ↓
Phase 3: PyAV Backend Integration (Multi-Threaded Decode — Verified against OPT-001)
  ↓
Phase 4: Shared Feature Cache (Waste Hunter — Eliminate Duplicate Face/Audio Computes)
  ↓
Phase 5: Unified FFmpeg Filtergraph (Single Encode Pass)
  ↓
Phase 6: Zero-Copy GPU NVDEC Direct-to-Tensor Decode
```

---

## 📊 Hierarchical BOLT Report & Decision Template

Every CI run produces a hierarchical resource health evaluation followed by an enforceable gatekeeper decision:

```text
============================================================
⚡ BOLT REPORT — Upload → Export Latency
Current: [X.X s] | Target: 25.0 s | Baseline Delta: [+/- X.X s]
============================================================

RESOURCE HEALTH

Video        : [ 🔴 / 🟠 / 🟡 / 🟢 ]
Reason       : [e.g., Opened four times across local_worker and WCE]

Frames       : [ 🔴 / 🟠 / 🟡 / 🟢 ]
Reason       : [e.g., 88.6% of decoded frames discarded without reuse]

Compute      : [ 🔴 / 🟠 / 🟡 / 🟢 ]
Reason       : [e.g., Duplicate Haar face detection on identical timestamps]

Encoding     : [ 🔴 / 🟠 / 🟡 / 🟢 ]
Reason       : [e.g., Two sequential FFmpeg encodes with intermediate disk write]

Telemetry    : [ 🔴 / 🟠 / 🟡 / 🟢 ]
Reason       : [e.g., Complete 100% stage coverage]

============================================================
GATEKEEPER DECISION

DECISION     : [ APPROVED 🟢 / REJECTED ❌ ]
Violation    : [ LAW X / NONE ]
Owner        : [ Responsible Gatekeeper ]
Required Fix : [ Actionable engineering instructions ]
============================================================
```
