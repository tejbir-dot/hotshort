import os
import json
import logging
import requests

log = logging.getLogger("groq_cortex")

def is_groq_enabled() -> bool:
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
            
        if score < min_score:
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

def review_candidates_with_groq(candidates: list, transcript_meta=None) -> list:
    if not is_groq_enabled():
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
            c["id"] = f"c{i}"

    try:
        max_candidates = int(os.environ.get("HS_GROQ_MAX_CANDIDATES", "30"))
    except ValueError:
        max_candidates = 20

    top_candidates = candidates[:max_candidates]
    
    # Prepare payload for Groq
    groq_input = []
    for c in top_candidates:
        groq_input.append({
            "candidate_id": str(c.get("id")),
            "start": round(float(c.get("start", 0)), 2),
            "end": round(float(c.get("end", 0)), 2),
            "duration": round(float(c.get("duration", 0)), 2),
            "text": str(c.get("text", "")).strip(),
            "existing_score": round(float(c.get("viral_score", 0)), 2),
            "existing_reason": str(c.get("reason", "none"))
        })

    prompt_json = json.dumps(groq_input, indent=2)
    
    system_prompt = """
You are HotShort Cortex: a world-class short-form content director, retention psychologist, podcast editor, and content research lab.

Your job is NOT to find a fixed number of clips.
Your job is to discover how many genuinely valuable short-form clips exist in the provided candidates.

Return 0 to N clips.
If only 1 clip is excellent, return 1.
If 6 clips are excellent and meaningfully different, return 6.
If none are strong, return 0.
Never force clips.

CORE PRINCIPLE:
Not every viral clip needs a dangerous hook.
Some great clips win because they are useful, insightful, emotional, surprising, practical, contrarian, funny, story-driven, or deeply relatable.

FIRST: Identify the content type.
Possible content modes:
- educational
- founder/startup
- podcast interview
- story/confession
- motivational
- technical/tutorial
- business/marketing
- entertainment
- philosophical
- news/commentary
- mixed

SECOND: Choose clip archetypes based on the transcript.
Possible strong clip archetypes:
- dangerous_hook
- practical_insight
- founder_lesson
- contrarian_take
- mistake_warning
- story_payoff
- emotional_truth
- framework_or_steps
- quote_or_big_line
- before_after_realization
- tactical_tip
- myth_busting
- curiosity_loop
- strong_opinion
- relatable_problem
- surprising_fact

A clip is valuable if it has at least ONE strong reason to exist:
1. It teaches something useful.
2. It reveals a strong insight.
3. It opens a curiosity loop.
4. It gives a clear takeaway.
5. It contains emotional truth.
6. It shows conflict, contrast, or contradiction.
7. It has a memorable line.
8. It solves a real problem.
9. It feels shareable, saveable, or comment-worthy.
10. It works as a standalone short without previous context.

DO NOT over-prioritize suspense.
DO NOT reject a clip just because it is calm.
A calm clip can be excellent if the insight is strong.

Reject clips that are:
- incomplete
- generic
- context-dependent
- repetitive
- only setup with no payoff
- only hype with no meaning
- too vague
- weak educational value
- same idea as another stronger clip

DIVERSITY RULE:
Do not return multiple clips that feel like the same idea.
Prefer a diverse set like:
- one practical insight
- one founder lesson
- one warning
- one contrarian take
- one story payoff
- one tactical tip

SCORING:
Score each selected clip from 0 to 100 using:
- hook_strength
- insight_strength
- completeness
- standalone_clarity
- retention_potential
- shareability
- payoff_strength
- uniqueness
- usefulness

Only return clips with viral_score >= 72.
But if a clip has exceptional educational value, practical value, or founder insight, it can pass even without a dramatic hook.

TIMESTAMP RULES:
- Only use candidate_id values provided.
- Never invent timestamps.
- start_adjustment_seconds and end_adjustment_seconds must stay inside original candidate boundaries.
- Prefer trimming dead setup and ending after the payoff.

EDITING INTELLIGENCE:
For every selected clip, decide pacing and subtitle style based on the clip type:
- fast: high-energy, punchy, tactical, controversial
- normal: educational, founder, business, insight
- slow: emotional, philosophical, dramatic, story payoff

Subtitle style:
- classic: clean educational/business
- neon: tech/futuristic/high-energy
- beast: loud viral/motivational
- retro: story/commentary
- minimal: premium calm insight

OUTPUT JSON ONLY.
No markdown.
No explanation outside JSON.

Return this exact structure:
{
  "content_diagnosis": {
    "content_mode": "founder/startup",
    "dominant_signals": ["insight", "warning", "practical"],
    "overall_clip_density": "low | medium | high",
    "estimated_valuable_clip_count": 0
  },
  "clips": [
    {
      "candidate_id": "c0",
      "clip_archetype": "practical_insight",
      "viral_score": 86,
      "title": "The Real Startup Cost Trap",
      "opening_caption": "Most founders spend money on the wrong thing...",
      "hook_type": "Insight",
      "why_this_clip_is_valuable": "It gives a useful founder lesson with clear standalone meaning.",
      "why_people_keep_watching": "They want to know what cost actually matters.",
      "payoff": "Customer acquisition matters more than product polish early on.",
      "retention_risk": "Could feel slow if captions are not punchy.",
      "start_adjustment_seconds": 0.0,
      "end_adjustment_seconds": 0.0,
      "scores": {
        "hook_strength": 78,
        "insight_strength": 92,
        "completeness": 88,
        "standalone_clarity": 90,
        "retention_potential": 82,
        "shareability": 80,
        "payoff_strength": 86,
        "uniqueness": 76,
        "usefulness": 94
      },
      "learning_signal_for_hotshort": {
        "meaning_pattern": "Useful founder insight with clear mistake correction",
        "psychological_trigger": "Problem-solution clarity",
        "why_selected_over_others": "More useful and complete than generic motivational clips"
      },
      "editing_notes": {
        "pacing_note": "normal",
        "subtitle_style": "classic",
        "caption_strategy": "Highlight the mistake and the corrected belief.",
        "broll_suggestion": "startup dashboard, Stripe, landing page, analytics"
      }
    }
  ],
  "rejected_candidates": [
    {
      "candidate_id": "c1",
      "reason": "Good topic but incomplete payoff and too dependent on previous context."
    }
  ]
}

Now review these candidates:
{{CANDIDATES_JSON}}
""".replace("{{CANDIDATES_JSON}}", prompt_json)

    log.info(f"[GROQ_CORTEX] Sending {len(groq_input)} candidates to Groq Cortex...")

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": _get_groq_model(),
                "messages": [
                    {
                        "role": "user",
                        "content": system_prompt
                    }
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            },
            timeout=_get_timeout()
        )
        response.raise_for_status()
        
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        parsed = parse_groq_json_safely(content)
        if _is_log_reasoning():
            log.info(f"[GROQ_CORTEX] Raw content snippet: {content[:500]}")
            log.info(f"[GROQ_CORTEX] Parsed type: {type(parsed).__name__}, keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'N/A'}")
        if not parsed:
            raise ValueError("Failed to parse Groq response into valid JSON dict.")
            
        validated = validate_groq_clips(parsed, top_candidates)
        
        if _is_log_reasoning():
            log.info(f"[GROQ_CORTEX] Selected {len(validated)} clips after validation.")
            log.info(f"[GROQ_CORTEX] Parsed keys: {list(parsed.keys())}")
            if "rejected_candidates" in parsed:
                for r in parsed["rejected_candidates"]:
                    log.info(f"[GROQ_CORTEX] Rejected {r.get('candidate_id')}: {r.get('reason')}")
                    
        if not validated:
            if _is_fail_open():
                log.info("[GROQ_CORTEX] 0 clips selected. Fail open is ON. Falling back to original candidates.")
                return candidates
            else:
                log.info("[GROQ_CORTEX] 0 clips selected. Fail open is OFF. Returning empty list.")
                return []
                
        merged = merge_groq_results_with_candidates(validated, top_candidates)
        
        if _is_log_reasoning():
            for m in merged:
                log.info(f"[GROQ_CORTEX] Clip '{m.get('title')}' learning signal: {m.get('learning_signal_for_hotshort')}")
                
        return merged

    except Exception as e:
        log.error(f"[GROQ_CORTEX] failed: {str(e)}")
        if _is_fail_open():
            log.info("[GROQ_CORTEX] Falling back to original candidates.")
            return candidates
        return []
