"""
Smart Local B-Roll Matcher
===========================
Maps transcript speech (with timestamps) to local video assets.
Returns a list of (timestamp_sec, asset_path, duration_sec) tuples
for the most impactful moments in the clip.

Asset Library:
  assets/broll_assets/money_assets/   → money, income, earn, wealth topics
  assets/broll_assets/luxury/         → cars, jets, lifestyle topics
  assets/broll_assets/content_assets/ → content, viral, clipping topics
"""

import os
import random
import logging
from typing import List, Tuple, Optional

log = logging.getLogger("smart_broll_matcher")

# ─────────────────────────────────────────────────────────────────────────────
# ASSET LIBRARY ROOT
# ─────────────────────────────────────────────────────────────────────────────
_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "broll_assets")

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORD → CATEGORY MAPPING  (add more as you add folders / clips)
# ─────────────────────────────────────────────────────────────────────────────
KEYWORD_MAP = {
    # ── MONEY / FINANCE ──────────────────────────────────────────────────────
    "money_assets": [
        "money", "million", "billion", "dollar", "earn", "earning",
        "income", "revenue", "profit", "rich", "wealth", "wealthy",
        "paid", "salary", "cash", "payment", "payout", "bank",
        "invest", "investment", "fund", "funding", "return", "roi",
        "financial", "finance", "affordable", "expensive", "price",
        "cost", "cheap", "economy", "economic", "tax", "taxes",
        "broke", "savings", "save", "spend", "spending", "budget",
        "crypto", "bitcoin", "stock", "stocks", "trading", "trade",
        "passive", "income stream", "six figures", "seven figures",
        "charge", "fee", "subscription", "monthly", "annual",
        "paycheck", "payroll", "commission", "bonus",
    ],

    # ── LUXURY / LIFESTYLE ───────────────────────────────────────────────────
    "luxury": [
        "luxury", "lamborghini", "ferrari", "bugatti", "supercar",
        "car", "cars", "vehicle", "jet", "private jet", "yacht",
        "watch", "rolex", "mansion", "penthouse", "villa", "resort",
        "travel", "trip", "vacation", "holiday", "lifestyle",
        "expensive", "high-end", "premium", "exclusive", "vip",
        "success", "successful", "boss", "ceo", "entrepreneur",
        "fast", "speed", "race", "drive", "flying", "luxury apartment",
        "club", "party", "celebration", "freedom", "dream",
        "status", "flex", "flexing", "drip",
    ],

    # ── CONTENT / CLIPPING / DIGITAL ─────────────────────────────────────────
    "content_assets": [
        "content", "viral", "clip", "clips", "clipping", "short",
        "shorts", "video", "videos", "views", "viewers", "watch",
        "growth", "growing", "grow", "audience", "followers", "subscriber",
        "subscribers", "channel", "platform", "youtube", "tiktok",
        "instagram", "reel", "reels", "algorithm", "creator",
        "editing", "editor", "edit", "thumbnail", "hook",
        "network", "networking", "social media", "digital",
        "online", "internet", "automation", "automate",
        "scale", "scaling", "system", "process", "workflow",
        "agency", "business", "brand", "branding", "niche",
        "podcast", "podcasting", "stream", "streaming",
        "monetize", "monetization", "adsense", "sponsorship",
        "graph", "analytics", "metric", "data", "impression",
        "reach", "engagement", "click", "conversion",
    ],
}

# Within each category, map specific clips to more precise sub-keywords
CLIP_PREFERENCE = {
    "money_assets": {
        "money.mp4":  ["money", "cash", "dollar", "earn", "rich", "wealth", "broke", "savings"],
        "payout.mp4": ["payout", "payment", "paid", "income", "revenue", "profit", "salary", "commission"],
    },
    "luxury": {
        "buggatti_jet.mp4":          ["jet", "private jet", "flying", "travel"],
        "luxury.1.mp4":              ["luxury", "mansion", "penthouse", "villa", "lifestyle", "exclusive"],
        "luxury_view_building.mp4":  ["building", "penthouse", "apartment", "office", "city"],
        "luxury_watch_view.mp4":     ["watch", "rolex", "premium", "status", "flex"],
        "spead_car.mp4":             ["car", "supercar", "ferrari", "lamborghini", "speed", "race", "drive", "fast"],
        "WhatsApp Video 2026-09-04 at 7.17.13 PM.mp4": ["success", "freedom", "dream", "celebration"],
    },
    "content_assets": {
        "content_growth.mp4":        ["growth", "growing", "grow", "audience", "followers"],
        "content_viral_graph.mp4":   ["viral", "views", "analytics", "data", "impression", "reach"],
        "create_thousands_clipd.mp4":["clip", "clips", "clipping", "shorts", "automate"],
        "digital_monoply.mp4":       ["digital", "online", "internet", "platform", "monopoly"],
        "editing.mp4":               ["editing", "editor", "edit", "thumbnail"],
        "higher_graph.mp4":          ["graph", "growth", "metric", "engagement", "scale"],
        "huge_clipping.mp4":         ["clipping", "short", "viral", "scale"],
        "networks.mp4":              ["network", "networking", "social media", "connection"],
        "networks_from_clipping.mp4":["agency", "business", "brand", "niche", "system"],
        "quant_wealth.mp4":          ["monetize", "monetization", "revenue", "income stream", "passive"],
    },
}


def _pick_clip_for_category(category: str, matched_word: str) -> Optional[str]:
    """Pick the most relevant clip file within a category for a matched word."""
    folder = os.path.join(_BASE, category)
    prefs = CLIP_PREFERENCE.get(category, {})
    word_lower = matched_word.lower()

    # 1) Try preference map — exact sub-keyword match
    for clip_name, sub_kws in prefs.items():
        if any(word_lower in kw or kw in word_lower for kw in sub_kws):
            path = os.path.join(folder, clip_name)
            if os.path.exists(path):
                return path

    # 2) Fallback: any existing clip in the folder (random)
    try:
        candidates = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith((".mp4", ".mov", ".avi"))
        ]
        if candidates:
            return random.choice(candidates)
    except Exception:
        pass
    return None


def _score_segment(text: str) -> Tuple[str, str, float]:
    """
    Score a text segment against all keyword categories.
    Returns (matched_word, category, score).
    """
    text_lower = text.lower()
    best_score = 0.0
    best_category = None
    best_word = ""

    for category, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in text_lower:
                # Longer keyword = more specific = higher weight
                score = len(kw.split()) * 1.0 + (1.0 if len(kw) > 6 else 0.5)
                if score > best_score:
                    best_score = score
                    best_category = category
                    best_word = kw

    return best_word, best_category, best_score


def find_broll_cuts(
    transcript_window: list,
    source_start: float,
    clip_duration: float,
    max_cuts: int = 3,
    min_cut_gap_s: float = 5.0,
    cut_duration_s: float = 2.5,
    cortex_keywords: List[str] = None,
) -> List[Tuple[float, str, float]]:
    """
    Scan transcript segments and find the best B-Roll insertion points.

    Args:
        transcript_window: List of {"start", "end", "text"} dicts (absolute timestamps).
        source_start: The absolute start of the clip in the source video (seconds).
        clip_duration: Total duration of the clip after ramp/speed (seconds).
        max_cuts: Maximum number of B-Roll cuts to inject.
        min_cut_gap_s: Minimum gap between cuts (seconds) to avoid rapid-fire overlaps.
        cut_duration_s: Duration of each B-Roll cut (seconds).

    Returns:
        List of (clip_relative_start_sec, asset_path, cut_duration_s).
        Sorted by timestamp ascending.
    """
    if not transcript_window:
        return []

    # Detect whether transcript_window uses ABSOLUTE or RELATIVE timestamps.
    # WCE remaps them to clip-relative (0-based) before passing.
    # But standalone calls (e.g. test scripts) may pass absolute timestamps.
    # Heuristic: if all t_start values are < clip_duration*2, treat as relative.
    sample_starts = [float(s.get("start", 0)) for s in transcript_window if s.get("text")]
    _is_relative = bool(sample_starts) and max(sample_starts) < clip_duration * 2

    log.info(
        "[SMART_BROLL] transcript mode=%s | segs=%d | source_start=%.1f | clip_dur=%.1f",
        "RELATIVE" if _is_relative else "ABSOLUTE", len(transcript_window), source_start, clip_duration
    )

    # Score every transcript segment
    scored = []
    for seg in transcript_window:
        t_start = float(seg.get("start", 0))
        t_end = float(seg.get("end", 0))
        text = seg.get("text", "")
        if not text.strip():
            continue

        matched_word, category, score = _score_segment(text)
        if score <= 0 or category is None:
            continue

        # Convert to clip-relative timestamp
        if _is_relative:
            # Already clip-relative (from WCE remapping) — use directly
            clip_rel_start = t_start
        else:
            # Absolute timestamp — subtract source_start
            clip_rel_start = t_start - source_start

        # Must fit within clip (leave room for cut_duration + 0.5s buffer)
        # Also avoid the very start (first 3s) so it doesn't clash with hook
        if clip_rel_start < 3.0 or clip_rel_start + cut_duration_s > clip_duration - 0.3:
            log.debug("[SMART_BROLL] skip seg t=%.2f (out of range) word='%s'", clip_rel_start, matched_word)
            continue

        log.info("[SMART_BROLL] scored: t=%.2fs word='%s' cat=%s score=%.1f",
                 clip_rel_start, matched_word, category, score)

        scored.append({
            "clip_rel_start": clip_rel_start,
            "t_end": t_end,
            "score": score,
            "category": category,
            "word": matched_word,
        })

    if not scored:
        log.info("[SMART_BROLL] No keyword matches found in transcript window.")
        
        # Fallback to cortex hints
        if cortex_keywords:
            fallback_scored = []
            for kw in cortex_keywords:
                matched_word, category, score = _score_segment(kw)
                if score > 0 and category:
                    fallback_scored.append({"word": matched_word, "category": category, "score": score})
            
            if fallback_scored:
                fallback_scored.sort(key=lambda x: -x["score"])
                best_fallback = fallback_scored[0]
                
                # Pick a safe timestamp (e.g., middle of the clip, at least 3.0s in)
                safe_t = max(3.0, clip_duration / 2.0 - cut_duration_s / 2.0)
                if safe_t + cut_duration_s < clip_duration - 0.3:
                    asset = _pick_clip_for_category(best_fallback["category"], best_fallback["word"])
                    if asset:
                        log.info(f"[SMART_BROLL] Fallback using cortex keyword '{best_fallback['word']}' at t={safe_t:.2f}s")
                        return [(safe_t, asset, cut_duration_s)]
                        
        return []

    # Sort by score descending, then pick with min-gap enforcement
    scored.sort(key=lambda x: -x["score"])
    selected = []
    used_times = []
    used_assets: set = set()   # anti-repeat: avoid same clip back-to-back

    for candidate in scored:
        t = candidate["clip_rel_start"]
        # Enforce minimum gap between cuts
        too_close = any(abs(t - ut) < min_cut_gap_s for ut in used_times)
        if too_close:
            continue

        asset = _pick_clip_for_category(candidate["category"], candidate["word"])
        if asset is None:
            log.warning("[SMART_BROLL] No asset found for category=%s word='%s'",
                        candidate["category"], candidate["word"])
            continue

        # Anti-repeat: if this exact file was used already, try to find another
        if asset in used_assets:
            folder = os.path.join(_BASE, candidate["category"])
            try:
                alternates = [
                    os.path.join(folder, f)
                    for f in os.listdir(folder)
                    if f.lower().endswith((".mp4", ".mov", ".avi"))
                    and os.path.join(folder, f) not in used_assets
                ]
                if alternates:
                    asset = random.choice(alternates)
                # else: all clips in this category used, allow repeat as last resort
            except Exception:
                pass

        selected.append((t, asset, cut_duration_s))
        used_times.append(t)
        used_assets.add(asset)
        log.info(
            "[SMART_BROLL] ✓ Cut @ t=%.2fs | word='%s' | category=%s | asset=%s",
            t, candidate["word"], candidate["category"], os.path.basename(asset)
        )

        if len(selected) >= max_cuts:
            break

    # Sort by ascending timestamp for FFmpeg overlay chain
    selected.sort(key=lambda x: x[0])
    return selected
