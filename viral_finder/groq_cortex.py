import os
import json
import logging
import requests
from typing import List, Dict, Any, Optional

log = logging.getLogger("groq_cortex")

def is_groq_enabled() -> bool:
    # Auto-disable during pytest runs to prevent test interference
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("HS_GROQ_CORTEX_ENABLED", "0").strip() == "1"

def _get_groq_api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()

def _get_groq_model() -> str:
    return os.environ.get("HS_GROQ_MODEL", "llama-3.1-8b-instant").strip()

def _get_timeout() -> int:
    try:
        return int(os.environ.get("HS_GROQ_TIMEOUT_SECONDS", "20"))
    except ValueError:
        return 20

def _get_max_clips() -> int:
    try:
        return int(os.environ.get("HS_GROQ_MAX_CLIPS", "10"))
    except ValueError:
        return 10

def _get_min_score() -> int:
    try:
        return int(os.environ.get("HS_GROQ_MIN_SCORE", "72"))
    except ValueError:
        return 72

def _is_fail_open() -> bool:
    return os.environ.get("HS_GROQ_FAIL_OPEN", "1").strip() == "1"

def _is_log_reasoning() -> bool:
    return os.environ.get("HS_GROQ_LOG_REASONING", "1").strip() == "1"

def parse_groq_json_safely(response_text: str) -> dict:
    try:
        # First attempt direct parse
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
    
    # Attempt to extract JSON from markdown block
    if "```json" in response_text:
        try:
            extracted = response_text.split("```json")[1].split("```")[0].strip()
            return json.loads(extracted)
        except Exception:
            pass
    elif "```" in response_text:
        try:
            extracted = response_text.split("```")[1].split("```")[0].strip()
            return json.loads(extracted)
        except Exception:
            pass
    
    # Try finding first { and last }
    start = response_text.find('{')
    end = response_text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(response_text[start:end+1])
        except Exception:
            pass

    return {}

def validate_groq_clips(parsed_json: dict, original_candidates: list) -> list:
    valid_clips = []
    
    if not isinstance(parsed_json, dict):
        return []
    
    clips = parsed_json.get("clips", [])
    if not isinstance(clips, list):
        return []

    original_ids = {str(c.get("id")) for c in original_candidates}
    min_score = _get_min_score()

    for clip in clips:
        if not isinstance(clip, dict):
            continue

        # Accept either candidate_id or id
        cid = str(clip.get("candidate_id") or clip.get("id") or "")
        if not cid or cid not in original_ids:
            continue

        # Flatten nested 'analysis' dict if present (some models wrap fields in it)
        analysis = clip.get("analysis")
        if isinstance(analysis, dict):
            for k, v in analysis.items():
                if k not in clip:
                    clip[k] = v
            
        score = clip.get("viral_score")
        # If Groq didn't return viral_score, use the existing score or assume a passing grade
        if score is None:
            existing = clip.get("existing_score", 0)
            score = float(existing) * 100 if float(existing) <= 1.0 else float(existing)
            clip["viral_score"] = round(score, 2)
        try:
            score = float(score)
        except (ValueError, TypeError):
            continue
            
        # Handle cases where Groq outputs 0.85 instead of 85
        if score <= 1.0 and min_score > 1.0:
            score = score * 100
            
        # Allow the exception rule from the prompt: high usefulness or insight passes even if viral_score < min_score
        scores = clip.get("scores", {})
        is_exceptional = False
        if isinstance(scores, dict):
            try:
                usefulness = float(scores.get("usefulness") or 0)
                insight = float(scores.get("insight_strength") or 0)
                if usefulness >= 80 or insight >= 80:
                    is_exceptional = True
            except (ValueError, TypeError):
                pass
            
        if score < min_score and not is_exceptional:
            continue
            
        # Normalise candidate_id
        clip["candidate_id"] = cid

        # Ensure adjustments are reasonable
        try:
            clip["start_adjustment_seconds"] = float(clip.get("start_adjustment_seconds", 0))
            clip["end_adjustment_seconds"] = float(clip.get("end_adjustment_seconds", 0))
        except (ValueError, TypeError):
            clip["start_adjustment_seconds"] = 0.0
            clip["end_adjustment_seconds"] = 0.0
            
        valid_clips.append(clip)
        
    # Sort by score desc, take top MAX_CLIPS
    valid_clips.sort(key=lambda x: x.get("viral_score", 0), reverse=True)
    max_clips = _get_max_clips()
    return valid_clips[:max_clips]

def merge_groq_results_with_candidates(validated_clips: list, original_candidates: list) -> list:
    merged = []
    # Create mapping of id to original candidate
    orig_map = {str(cand.get("id")): cand for cand in original_candidates}
    
    for v_clip in validated_clips:
        cid = str(v_clip.get("candidate_id", ""))
        orig = orig_map[cid]
        
        new_cand = dict(orig)
        
        # Apply adjustments safely
        orig_start = float(orig.get("start", 0))
        orig_end = float(orig.get("end", orig_start))
        
        adj_start = v_clip.get("start_adjustment_seconds", 0)
        adj_end = v_clip.get("end_adjustment_seconds", 0)
        
        # Keep inside bounds
        new_start = max(0.0, orig_start + adj_start)
        new_end = max(new_start + 0.1, orig_end + adj_end)
        
        new_cand["start"] = round(new_start, 2)
        new_cand["end"] = round(new_end, 2)
        new_cand["duration"] = round(new_end - new_start, 2)
        
        # Attach Groq specific fields
        new_cand["cortex_enabled"] = True
        raw_score = float(v_clip.get("viral_score", 0))
        # Normalise 0-100 to 0.0-1.0 to match pipeline convention
        cortex_score = raw_score / 100.0 if raw_score > 1.0 else raw_score
        new_cand["cortex_score"] = round(cortex_score, 4)
        # Override viral score to ensure ranking
        new_cand["viral_score"] = new_cand["cortex_score"]
        
        new_cand["title"] = v_clip.get("title", "")
        new_cand["opening_caption"] = v_clip.get("opening_caption", "")
        new_cand["why_this_clip_works"] = (
            v_clip.get("why_this_clip_is_valuable", "")
            or v_clip.get("why_dangerous_hook", "")
            + " " + v_clip.get("why_people_keep_watching", "")
        ).strip()
        new_cand["clip_archetype"] = v_clip.get("clip_archetype", "")
        new_cand["payoff"] = v_clip.get("payoff", "")
        new_cand["clip_scores"] = v_clip.get("scores", {})
        new_cand["hook_type"] = v_clip.get("hook_type", "")
        new_cand["completeness_score"] = v_clip.get("completeness_score", 0)
        new_cand["retention_risk"] = v_clip.get("retention_risk", "")
        new_cand["learning_signal_for_hotshort"] = v_clip.get("learning_signal_for_hotshort", {})
        new_cand["editing_notes"] = v_clip.get("editing_notes", {})
        
        merged.append(new_cand)
        
    return merged

def review_candidates_with_groq(candidates: List[Dict], full_transcript: List[Dict]) -> List[Dict]:
    if not is_groq_enabled() or not full_transcript:
        return candidates

    api_key = _get_groq_api_key()
    if not api_key:
        log.warning("[GROQ_CORTEX] API key missing. Falling back to original candidates.")
        return candidates

    if not candidates:
        return candidates

    # Assign IDs if missing
    for i, c in enumerate(candidates):
        if "id" not in c:
            c["id"] = f"c_cand_{i}"

    try:
        max_candidates = int(os.environ.get("HS_GROQ_MAX_CANDIDATES", "30"))
    except ValueError:
        max_candidates = 20

    top_candidates = candidates[:max_candidates]

    def _find_seg_idx(ts: float) -> int:
        target = float(ts or 0.0)
        for i, seg in enumerate(full_transcript):
            ss = float(seg.get("start", 0.0) or 0.0)
            ee = float(seg.get("end", ss) or ss)
            if ss <= target <= max(ss, ee):
                return i
        return max(0, min(len(full_transcript) - 1, 0 if not full_transcript else int(min(range(len(full_transcript)), key=lambda j: abs(float(full_transcript[j].get("start", 0.0) or 0.0) - target)))))

    batch_size = 4
    batches = [top_candidates[i:i + batch_size] for i in range(0, len(top_candidates), batch_size)]
    
    system_prompt = """You are HotShort Cortex: a world-class Narrative Surgeon for video clips.

Your job is NOT to find another interesting sentence.
Your job is to determine whether the hook's tension, question, claim, belief reversal, or curiosity loop becomes resolved.

A valid payoff must:
1. Answer the hook.
2. Explain the hook.
3. Resolve the hook.
4. Complete the idea started by the hook.

A payoff must NOT:
- start a new topic
- start a new example
- start a new analogy
- start a new story
- introduce unrelated information

If no valid payoff exists inside the context window, RETURN REJECT instead of COMPLETE_IDEA.

Available Actions:
- KEEP: The candidate is perfect. The idea is complete.
- MOVE_HOOK: The candidate started too early with filler, or missed the true hook just before it. Move the hook.
- COMPLETE_IDEA: The candidate cuts off before the idea resolves. Extend it to the true payoff.
- REJECT: The candidate is a weak idea, rambling, or never resolves.

FORCED REASONING STEP:
Before you choose COMPLETE_IDEA or KEEP, you must extract the hook's core question and the payoff's direct answer, and rate the resolution strength from 0-10.
Example:
  "hook_question": "Why do successful people appear lucky?",
  "payoff_answer": "Because they stay in the game longer.",
  "resolution_strength": 9

Return JSON ONLY in this exact format:
{
  "surgeon_reports": [
    {
      "candidate_id": "c_cand_0",
      "decision": "COMPLETE_IDEA",
      "confidence": 0.92,
      "hook_segment_index": 12,
      "payoff_segment_index": 15,
      "hook_question": "What is the real cost of startups?",
      "payoff_answer": "Customer acquisition, not product building.",
      "resolution_strength": 9,
      "reason": "The payoff directly answers the question raised in the hook."
    }
  ]
}
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    log.info(f"[SURGEON_ENTER]\ncandidates={len(top_candidates)}")

    for batch_idx, batch in enumerate(batches):
        log.info(f"[SURGEON_BATCH]\nbatch={batch_idx+1}\ncount={len(batch)}")
        
        groq_input = []
        for c in batch:
            s0 = float(c.get("start", 0.0))
            e0 = float(c.get("end", s0))
            
            s_idx = _find_seg_idx(s0)
            e_idx = _find_seg_idx(e0)
            
            # Context window: approx 10s before, 30s after
            window_start = max(0, s_idx - 4)
            window_end = min(len(full_transcript), e_idx + 10)
            
            window_text = []
            for j in range(window_start, window_end):
                text = str(full_transcript[j].get("text", "")).strip()
                window_text.append(f"[{j}] {text}")
                
            groq_input.append({
                "candidate_id": str(c["id"]),
                "transcript_window": "\n".join(window_text)
            })

        payload = {
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(groq_input, indent=2)}
            ]
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                
                if response.status_code == 429:
                    log.warning(f"[GROQ_SURGEON] 429 Too Many Requests (batch {batch_idx+1}, attempt {attempt+1}/{max_retries}). Sleeping 45s...")
                    import time
                    time.sleep(45)
                    continue
                    
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                
                for report in parsed.get("surgeon_reports", []):
                    cid = report.get("candidate_id")
                    for c in top_candidates:
                        if c.get("id") == cid:
                            c["groq_surgeon"] = report
                            break
                            
                break  # Success
                
            except Exception as e:
                if attempt < max_retries - 1:
                    log.warning(f"[GROQ_SURGEON] Batch {batch_idx+1} Attempt {attempt+1} failed: {e}. Retrying in 5s...")
                    import time
                    time.sleep(5)
                else:
                    log.error(f"[GROQ_SURGEON] Failed batch {batch_idx+1}: {e}")
                    
        if batch_idx < len(batches) - 1:
            import time
            time.sleep(1.5)

    return candidates


def _chunk_transcript(segments: list, video_duration: float, window_size: float = 240.0, overlap: float = 30.0) -> list:
    chunks = []
    if not segments:
        return chunks
    
    current_start = 0.0
    # If video is extremely short (e.g. <= window_size), just do one chunk
    if video_duration <= window_size:
        chunks.append({
            "start": 0.0,
            "end": video_duration,
            "segments": segments
        })
        return chunks
        
    while current_start < video_duration:
        current_end = current_start + window_size
        # Gather segments in this window
        chunk_segs = [
            s for s in segments
            if float(s.get("start", 0)) >= current_start
            and float(s.get("start", 0)) < current_end
        ]
        if chunk_segs:
            chunks.append({
                "start": current_start,
                "end": min(current_end, video_duration),
                "segments": chunk_segs
            })
        current_start += (window_size - overlap)
        if window_size <= overlap:
            break
            
    return chunks


def validate_groq_moments(moments: list, video_duration: float) -> list:
    valid_moments = []
    
    # 4. Add env controls: HS_GROQ_DIRECTOR_MIN_SCORE=60
    director_min_score_raw = os.environ.get("HS_GROQ_DIRECTOR_MIN_SCORE")
    if director_min_score_raw:
        try:
            min_score = float(director_min_score_raw)
        except ValueError:
            min_score = 60.0
    else:
        min_score = 60.0

    for idx, m in enumerate(moments):
        if not isinstance(m, dict):
            continue
            
        cid = str(m.get("candidate_id") or m.get("id") or f"moment_{idx}")
        title = str(m.get("title") or "Untitled")
        
        try:
            start = float(m.get("start", -1))
            end = float(m.get("end", -1))
        except (ValueError, TypeError):
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start=-1 end=-1 title={title} viral_score=0 usefulness=0 insight_strength=0 reject_reason=invalid_timestamps")
            continue
            
        if start < 0 or end < 0 or start >= end:
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score=0 usefulness=0 insight_strength=0 reject_reason=negative_or_inverted_timestamps")
            continue
            
        # Ensure it fits within video duration
        if video_duration and end > video_duration + 5.0:  # allow 5s grace
            end = video_duration
            
        dur = end - start
        
        # allow 8s–75s moments
        if dur < 8.0 or dur > 75.0:
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score=0 usefulness=0 insight_strength=0 reject_reason=duration_{round(dur,1)}s_not_between_8_and_75")
            continue
            
        m["start"] = round(start, 2)
        m["end"] = round(end, 2)
        m["duration"] = round(dur, 2)
        
        # Parse score
        score = m.get("viral_score")
        if score is None:
            score = 75.0
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 75.0
            
        # Normalize score
        if score <= 1.0:
            score = score * 100.0
        m["viral_score"] = round(score, 2)
        
        # Extract usefulness and insight_strength
        usefulness = 0.0
        insight_strength = 0.0
        try:
            usefulness = float(m.get("usefulness") or 0)
            if usefulness <= 1.0 and usefulness > 0:
                usefulness *= 100.0
        except (ValueError, TypeError):
            pass
        try:
            insight_strength = float(m.get("insight_strength") or m.get("insight") or 0)
            if insight_strength <= 1.0 and insight_strength > 0:
                insight_strength *= 100.0
        except (ValueError, TypeError):
            pass
            
        m["usefulness"] = round(usefulness, 2)
        m["insight_strength"] = round(insight_strength, 2)
        
        # allow score >= 60 if usefulness >= 75 or insight_strength >= 75
        is_exceptional = (usefulness >= 75.0 or insight_strength >= 75.0)
        
        # check score against relaxed thresholds
        if is_exceptional:
            if m["viral_score"] < 60.0:
                log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=score_below_60_for_exceptional")
                continue
        else:
            if m["viral_score"] < min_score:
                log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=score_below_minimum_{min_score}")
                continue
                
        # allow incomplete payoff if clip_archetype is curiosity_loop, bold_claim, controversy, question, or prediction
        completeness = 100.0
        try:
            completeness = float(m.get("completeness_score") or m.get("completeness") or 100.0)
            if completeness <= 1.0 and completeness > 0:
                completeness *= 100.0
        except (ValueError, TypeError):
            pass
            
        clip_archetype = str(m.get("clip_archetype") or "").strip().lower()
        allowed_incomplete = {"curiosity_loop", "bold_claim", "controversy", "question", "prediction"}
        if completeness < 72.0 and clip_archetype not in allowed_incomplete:
            log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=incomplete_payoff_for_archetype_{clip_archetype}")
            continue

        # do not reject just because context is sparse if hook/usefulness is strong
        text_content = str(m.get("text") or m.get("reason") or m.get("title") or "")
        word_count = len(text_content.split())
        if word_count < 3:
            is_strong = (m["viral_score"] >= 75.0 or usefulness >= 75.0 or insight_strength >= 75.0)
            if not is_strong:
                log.info(f"[GROQ_DIRECTOR_REJECT] candidate_id={cid} start={start} end={end} title={title} viral_score={m['viral_score']} usefulness={usefulness} insight_strength={insight_strength} reject_reason=sparse_context_and_weak_scores")
                continue
                
        valid_moments.append(m)
        
    return valid_moments


def _overlap_ratio(a_start, a_end, b_start, b_end):
    try:
        inter_start = max(a_start, b_start)
        inter_end = min(a_end, b_end)
        inter = max(0.0, inter_end - inter_start)
        union_start = min(a_start, b_start)
        union_end = max(a_end, b_end)
        union = max(0.001, union_end - union_start)
        return inter / union
    except Exception:
        return 0.0


def dedupe_moments(moments: list, threshold=0.70) -> list:
    if not moments:
        return []
    sorted_m = sorted(moments, key=lambda x: float(x.get("viral_score", 0)), reverse=True)
    kept = []
    for m in sorted_m:
        m_start = m["start"]
        m_end = m["end"]
        duplicate = False
        for k in kept:
            ratio = _overlap_ratio(m_start, m_end, k["start"], k["end"])
            if ratio > threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(m)
    return sorted(kept, key=lambda x: x["start"])


def find_moments_from_transcript(transcript_segments: list, video_duration: float, max_clips: int = 8) -> list:
    if not is_groq_enabled():
        return []

    api_key = _get_groq_api_key()
    if not api_key:
        log.warning("[GROQ_CORTEX] API key missing for transcript-first mode.")
        return []

    if not transcript_segments:
        return []

    try:
        chunk_size = float(os.environ.get("HS_GROQ_TRANSCRIPT_CHUNK_SECONDS", "240"))
        overlap_size = float(os.environ.get("HS_GROQ_TRANSCRIPT_OVERLAP_SECONDS", "30"))
    except ValueError:
        chunk_size = 240.0
        overlap_size = 30.0

    # 1. Chunk transcript into rolling windows
    chunks = _chunk_transcript(transcript_segments, video_duration, window_size=chunk_size, overlap=overlap_size)
    
    # Apply MAX_CHUNKS control
    try:
        max_chunks = int(os.environ.get("HS_GROQ_DIRECTOR_MAX_CHUNKS", "3").strip())
    except ValueError:
        max_chunks = 3
    chunks = chunks[:max_chunks]
    
    log.info(f"[GROQ_TRANSCRIPT_FIRST] enabled=True")
    log.info(f"[GROQ_TRANSCRIPT_FIRST] chunks={len(chunks)}")
    
    all_raw_moments = []
    all_unvalidated_moments = []
    
    # 2. Iterate chunks and query Groq
    import time
    try:
        sleep_ms = int(os.environ.get("HS_GROQ_CHUNK_SLEEP_MS", "800").strip())
    except ValueError:
        sleep_ms = 800

    for idx, chunk in enumerate(chunks):
        if idx > 0 and sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        groq_input = []
        for s in chunk["segments"]:
            groq_input.append({
                "start": round(float(s.get("start", 0)), 2),
                "end": round(float(s.get("end", 0)), 2),
                "text": str(s.get("text", "")).strip()
            })
            
        prompt_json = json.dumps(groq_input, indent=2)
        
        system_prompt = """
You are HotShort Moment Director: a world-class short-form content director, retention psychologist, podcast editor, and content research lab.

Your job is to read the provided transcript segments and identify the most valuable complete, standalone short-form moments.
For each valuable moment, identify:
- start (precise time in seconds where the speaker begins the thought/scene, do not cut mid-sentence)
- end (precise time in seconds where the speaker finishes the payoff/takeaway, do not cut mid-sentence)
- viral_score (0 to 100 based on hook, insight, usefulness, and narrative completeness)
- usefulness (0 to 100 based on practical value or how actionable it is)
- insight_strength (0 to 100 based on counterintuitive or deep thoughts)
- completeness_score (0 to 100 score of stand-alone completeness)
- title (a punchy, curiosity-driven title for the clip)
- opening_caption (the very first spoken phrase or a curiosity hook caption)
- clip_archetype (choose from: practical_insight, warning, contrarian_take, story, framework, mistake, case_study, emotional_truth, tactical_steps)
- hook_line (the hook line of the clip)
- build (the build/context text)
- payoff (the core payoff/takeaway of the clip)
- why_valuable (why this clip is insightful, emotional, or practical for the audience)
- why_people_keep_watching (retention driver)
- editing_notes (pacing_note: fast/medium/slow, subtitle_style: classic|neon|beast|retro|minimal, face_priority: center)

MOMENT VALIDITY RULES:
- **CRITICAL: Duration MUST be between 30 and 45 seconds.**
- **NEVER return a moment shorter than 20 seconds.**
- Start must not be mid-sentence if avoidable.
- End must include payoff/takeaway.
- Reject fragments even if hook sounds good.
- Prefer complete insight over aggressive hook.
- For educational/founder podcasts, valuable clips can be:
  practical insight, mistake correction, framework, warning, counterintuitive idea, tactical steps, story payoff.

SCORING SCALE:
- 85-100: Exceptional, viral gold, must-share.
- 72-84: Strong, complete, highly valuable, educational, or emotional. (This is the passing range).
- 60-71: Moderate quality, but perhaps missing a clear payoff or standalone clarity.
- Below 60: Weak or incomplete.

Return 0 to N moments.
Never force moments. If none are strong, return 0 moments.

OUTPUT JSON ONLY.
No markdown. No explanation outside JSON.

Return this exact structure:
{
  "content_diagnosis": {
    "content_mode": "founder/startup | educational | podcast | mixed",
    "overall_clip_density": "low | medium | high",
    "estimated_valuable_clip_count": 0
  },
  "moments": [
    {
      "start": 12.3,
      "end": 45.6,
      "viral_score": 86,
      "usefulness": 88,
      "insight_strength": 85,
      "completeness_score": 84,
      "clip_archetype": "practical_insight",
      "title": "...",
      "opening_caption": "...",
      "reason": "...",
      "editing_notes": {
        "pacing_note": "medium",
        "subtitle_style": "classic",
        "face_priority": "center"
      }
    }
  ],
  "rejected_moments": []
}

Now review these transcript segments:
{{TRANSCRIPT_JSON}}
""".replace("{{TRANSCRIPT_JSON}}", prompt_json)

        response = None
        for attempt in range(2):
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": _get_groq_model(),
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {
                                "role": "user",
                                "content": system_prompt
                            }
                        ]
                    },
                    timeout=_get_timeout()
                )
                if response.status_code == 429:
                    if attempt == 0:
                        log.warning(f"[GROQ_DIRECTOR] window {idx} returned 429. Sleeping 2s before retry.")
                        time.sleep(2.0)
                        continue
                    else:
                        log.error(f"[GROQ_DIRECTOR] window {idx} failed: 429 Too Many Requests after retry.")
                        break
                response.raise_for_status()
                break
            except Exception as e:
                is_429 = False
                if hasattr(e, "response") and e.response is not None:
                    if e.response.status_code == 429:
                        is_429 = True
                if is_429:
                    if attempt == 0:
                        log.warning(f"[GROQ_DIRECTOR] window {idx} raised 429. Sleeping 2s before retry.")
                        time.sleep(2.0)
                        continue
                    else:
                        log.error(f"[GROQ_DIRECTOR] window {idx} failed: 429 Too Many Requests after retry.")
                        break
                if attempt == 0:
                    log.warning(f"[GROQ_DIRECTOR] window {idx} failed attempt 1: {e}. Retrying.")
                    continue
                log.error(f"[GROQ_DIRECTOR] window {idx} failed: {e}")
                break

        if response is None or response.status_code != 200:
            continue

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = parse_groq_json_safely(content)
            
            if parsed and "moments" in parsed:
                chunk_moments = parsed["moments"]
                if not isinstance(chunk_moments, list):
                    chunk_moments = []
                
                # Apply per-chunk limit
                try:
                    max_moments_per_chunk = int(os.environ.get("HS_GROQ_DIRECTOR_MAX_MOMENTS_PER_CHUNK", "5").strip())
                except ValueError:
                    max_moments_per_chunk = 5
                
                chunk_moments = chunk_moments[:max_moments_per_chunk]
                
                # Store unvalidated chunk moments for rescue fallback
                all_unvalidated_moments.extend(chunk_moments)
                
                validated_chunk = validate_groq_moments(chunk_moments, video_duration)
                all_raw_moments.extend(validated_chunk)
                log.info(f"[GROQ_DIRECTOR] window {idx}: found {len(validated_chunk)} valid moments out of {len(chunk_moments)}")
            else:
                log.info(f"[GROQ_DIRECTOR] window {idx}: no moments returned or failed to parse JSON")
        except Exception as e:
            log.error(f"[GROQ_DIRECTOR] window {idx} parse failed: {e}")
            
    # 5. If Groq Director returns raw moments but validation rejects all, inject top 1-2 raw moments as fallback
    if not all_raw_moments and all_unvalidated_moments:
        log.warning("[GROQ_TRANSCRIPT_FIRST] All moments rejected by validation. Rescuing top 1-2 raw moments.")
        
        def get_score(x):
            try:
                s = float(x.get("viral_score", 0))
                return s * 100.0 if s <= 1.0 else s
            except Exception:
                return 0.0
                
        sorted_unval = sorted(all_unvalidated_moments, key=get_score, reverse=True)
        rescued = []
        for m in sorted_unval:
            if len(rescued) >= 2:
                break
            if not isinstance(m, dict):
                continue
            try:
                start = float(m.get("start", -1))
                end = float(m.get("end", -1))
                dur = end - start
                # Enforce basic sanity duration check for rescue (5s to 90s)
                if start >= 0 and end > start and 5.0 <= dur <= 90.0:
                    m["start"] = round(start, 2)
                    m["end"] = round(end, 2)
                    m["duration"] = round(dur, 2)
                    m["viral_score"] = round(get_score(m), 2)
                    m["reason"] = "groq_director_rescue"
                    m["cortex_enabled"] = True
                    m["groq_moment"] = True
                    m["needs_manual_review"] = True
                    
                    # Extract usefulness and insight
                    try:
                        u = float(m.get("usefulness") or 0)
                        m["usefulness"] = round(u * 100.0 if u <= 1.0 and u > 0 else u, 2)
                    except Exception:
                        m["usefulness"] = 0.0
                    try:
                        i = float(m.get("insight_strength") or m.get("insight") or 0)
                        m["insight_strength"] = round(i * 100.0 if i <= 1.0 and i > 0 else i, 2)
                    except Exception:
                        m["insight_strength"] = 0.0
                        
                    rescued.append(m)
            except Exception:
                pass
        all_raw_moments = rescued

    log.info(f"[GROQ_TRANSCRIPT_FIRST] moments_found={len(all_raw_moments)}")
    
    # 3. Dedupe overlapping moments across different windows
    deduped = dedupe_moments(all_raw_moments, threshold=0.70)
    log.info(f"[GROQ_TRANSCRIPT_FIRST] moments_after_dedupe={len(deduped)}")
    
    try:
        max_clips_limit = int(os.environ.get("HS_GROQ_TRANSCRIPT_MAX_CLIPS", str(max_clips)))
    except ValueError:
        max_clips_limit = max_clips

    return deduped[:max_clips_limit]

def analyze_narrative_roles(transcript_segments: List[Dict]) -> Dict[int, str]:
    """
    Experimental Groq-powered Narrative Intelligence pass.
    Analyzes the entire transcript in batches and assigns one of [HOOK, STORY, PROOF, LESSON, PAYOFF, BUILD]
    to each segment by ID.
    Returns a dictionary mapping segment index to role string.
    """
    if not is_groq_enabled() and os.environ.get("HS_GROQ_NARRATIVE_ROLES") != "1":
        return {}

    api_key = _get_groq_api_key()
    if not api_key:
        return {}

    BATCH_SIZE = 40
    master_roles_map = {}
    
    total_segments = len(transcript_segments)
    batches = [transcript_segments[i:i + BATCH_SIZE] for i in range(0, total_segments, BATCH_SIZE)]
    
    log.info(f"[GROQ_NARRATIVE] Analyzing {total_segments} segments across {len(batches)} batches...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    for batch_idx, batch in enumerate(batches):
        # Build input array for this batch
        groq_input = []
        for s in batch:
            # We must use the original index in the full transcript for the ID
            original_idx = transcript_segments.index(s)
            groq_input.append({
                "id": original_idx,
                "text": str(s.get("text", "")).strip()
            })
            
        prompt_json = json.dumps(groq_input, indent=2)
        tokens_est = len(prompt_json) // 4
        
        log.info(f"[GROQ_NARRATIVE] batch={batch_idx+1}/{len(batches)} segments={len(batch)} tokens_est={tokens_est}")
        
        system_prompt = """
You are a world-class Narrative Analyst for short-form video.
Read the following transcript segments and assign EXACTLY ONE narrative role to EACH segment.

Valid roles:
1. HOOK: A question, bold claim, or pattern interrupt that grabs attention.
2. STORY: A personal anecdote, example, or narrative progression.
3. PROOF: Data, evidence, or logical justification for a claim.
4. LESSON: The core teaching, framework, or actionable takeaway.
5. PAYOFF: The final satisfying conclusion, punchline, or "aha!" moment.
6. BUILD: General context or setup that doesn't fit the above.

OUTPUT JSON ONLY.
Return this exact structure:
{
  "segments": [
    {"id": 0, "role": "HOOK"},
    {"id": 1, "role": "STORY"},
    {"id": 2, "role": "BUILD"}
  ]
}

Transcript:
""" + prompt_json
        
        payload = {
            "model": _get_groq_model(),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "user", "content": system_prompt}
            ]
        }
        
        max_retries = 3
        batch_success = False
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                
                if response.status_code == 429:
                    log.warning(f"[GROQ_NARRATIVE] 429 Too Many Requests (batch {batch_idx+1}, attempt {attempt+1}/{max_retries}). Sleeping 45s...")
                    import time
                    time.sleep(45)
                    continue
                    
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                
                for seg in parsed.get("segments", []):
                    try:
                        sid = int(seg.get("id", -1))
                        role = str(seg.get("role", "BUILD")).upper()
                        if sid >= 0:
                            master_roles_map[sid] = role
                    except Exception:
                        pass
                
                batch_success = True
                break  # break retry loop on success
                
            except Exception as e:
                if attempt < max_retries - 1:
                    log.warning(f"[GROQ_NARRATIVE] Batch {batch_idx+1} Attempt {attempt+1} failed: {e}. Retrying in 5s...")
                    import time
                    time.sleep(5)
                else:
                    log.error(f"[GROQ_NARRATIVE] Failed to analyze narrative roles for batch {batch_idx+1}: {e}")
        
        # Add a small delay between batches to avoid immediate 429
        if batch_idx < len(batches) - 1:
            import time
            time.sleep(1.5)
            
    log.info(f"[GROQ_NARRATIVE] Successfully mapped {len(master_roles_map)} total narrative roles.")
    return master_roles_map
