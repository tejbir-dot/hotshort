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

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORD → CATEGORY MAPPING
# ─────────────────────────────────────────────────────────────────────────────
KEYWORD_MAP = {
    # ── MONEY / FINANCE ──────────────────────────────────────────────────────
    "money_assets": [
        "money", "million", "billion", "dollar", "earn", "earning",
        "income", "revenue", "profit", "rich", "wealth", "wealthy",
        "paid", "salary", "cash", "payment", "payout", "bank",
        "invest", "investment", "fund", "funding", "return", "roi",
        "financial", "finance", "expensive", "price", "cost",
        "economy", "economic", "tax", "taxes", "broke", "savings",
        "save", "spend", "spending", "budget", "passive",
        "crypto", "bitcoin", "stock", "stocks", "trading", "trade",
        "six figures", "seven figures", "paycheck", "payroll",
        "commission", "bonus", "equity", "asset", "assets",
        # Psychology / mindset (mapped to money_assets visuals)
        "mindset", "mind", "brain", "focus", "deep work", "obsession",
        "discipline", "sacrifice", "hustle", "grind", "king", "power",
        "boss", "ceo", "empire", "control", "system", "secret", "roadmap",
        "strategy", "hack", "exposed", "truth", "real game", "1%",
        "elite", "top 1", "algorithm", "data", "ai", "automation",
        "tech", "processor", "neurons", "awakening", "peace", "freedom",
        "opportunity", "chance", "golden", "rare",
    ],

    # ── LUXURY / LIFESTYLE ───────────────────────────────────────────────────
    "luxury": [
        "luxury", "lamborghini", "ferrari", "bugatti", "bmw", "supercar",
        "car", "cars", "vehicle", "jet", "private jet", "yacht",
        "watch", "rolex", "mansion", "penthouse", "villa", "resort",
        "travel", "trip", "vacation", "holiday", "lifestyle",
        "high-end", "premium", "exclusive", "vip",
        "successful", "entrepreneur",
        "fast", "speed", "race", "drive", "flying", "luxury apartment",
        "club", "party", "celebration", "dream",
        "status", "flex", "flexing", "drip", "chaotic", "energy",
    ],

    # ── CONTENT / CLIPPING / DIGITAL ─────────────────────────────────────────
    "content_assets": [
        "content", "viral", "clip", "clips", "clipping", "short",
        "shorts", "video", "videos", "views", "viewers",
        "growth", "growing", "grow", "audience", "followers", "subscriber",
        "subscribers", "channel", "platform", "youtube", "tiktok",
        "instagram", "reel", "reels", "creator",
        "editing", "editor", "edit", "thumbnail", "hook",
        "network", "networking", "social media", "digital",
        "online", "internet", "scale", "scaling", "workflow",
        "agency", "business", "brand", "branding", "niche",
        "podcast", "podcasting", "stream", "streaming",
        "monetize", "monetization", "adsense", "sponsorship",
        "graph", "analytics", "metric", "impression",
        "reach", "engagement", "click", "conversion", "tone",
        "million clips", "youtube button",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# CLIP PREFERENCE — maps exact filenames to precise sub-keywords
# ALL filenames verified against actual files on disk (Sep 2026)
# ─────────────────────────────────────────────────────────────────────────────
CLIP_PREFERENCE = {
    "money_assets": {
        # Core money visuals
        "money.mp4":                    ["money", "cash", "dollar", "earn", "rich", "wealth"],
        "payout.mp4":                   ["payout", "payment", "paid", "income", "revenue", "profit", "salary", "commission"],
        "bank balance growing.mp4":     ["bank", "savings", "save", "passive", "growing", "balance"],
        "tones of money.mp4":           ["wealth", "dollar", "financial", "rich", "abundance"],
        "money_succes.mp4":             ["success", "wealthy", "millionaire", "achieve", "financial freedom"],
        "bussiness.mp4":                ["business", "entrepreneur", "brand", "boss", "ceo"],
        "win.mp4":                      ["win", "winning", "success", "goal", "reward"],
        # Psychology / elite mindset
        "king.mp4":                     ["king", "power", "boss", "empire", "authority", "elite", "1%", "top 1"],
        "golden chance.mp4":            ["opportunity", "chance", "golden", "unlock", "rare", "discover"],
        "secret roadmap.mp4":           ["secret", "roadmap", "strategy", "hack", "exposed", "plan", "system"],
        "the real game.mp4":            ["real", "truth", "game", "mindset", "exposed", "actual", "real game"],
        "1% people.mp4":                ["elite", "top 1", "1%", "exclusive", "rare", "best", "six figures", "seven figures"],
        "deep work.mp4":                ["focus", "deep work", "productive", "grind", "build", "discipline", "work"],
        "creative focus work.mp4":      ["creative", "idea", "build", "create", "creative work"],
        "obsession.mp4":                ["obsession", "driven", "hustle", "grind", "dedicated"],
        "sacrifice ,never give up.mp4": ["sacrifice", "never give up", "discipline", "consistent", "commit"],
        "mind awakening.mp4":           ["mind", "mindset", "awakening", "realize", "conscious", "brain"],
        "brain rot ,controlled.mp4":    ["attention", "control", "discipline", "focus", "brain"],
        "war inner beast.mp4":          ["war", "beast", "inner", "fight", "conquer", "fearless", "courage"],
        "neurons pathways.mp4":         ["neurons", "learn", "understand", "think", "pathway", "brain"],
        # Tech / AI
        "human and ai.mp4":             ["ai", "human and ai", "automation", "tech", "future", "robot"],
        "algorithm.mp4":                ["algorithm", "system", "data", "code"],
        "data centers.mp4":             ["data", "tech", "scale", "server", "digital", "processor"],
        "processor ,tech.mp4":          ["processor", "tech", "speed", "compute", "chip"],
        "DNA.mp4":                      ["genetics", "dna", "deep", "fundamental", "science"],
        # Lifestyle / peace
        "peace.mp4":                    ["peace", "freedom", "lifestyle", "balance", "calm", "rest"],
        "luxury view.mp4":              ["luxury", "view", "premium", "lifestyle", "penthouse"],
        # Content / network
        "content networking.mp4":       ["network", "content", "social", "connection", "community"],
        "controlled by.mp4":            ["control", "system", "matrix", "controlled", "power"],
        "writing.mp4":                  ["write", "writing", "journal", "note", "document", "script"],
        # Cinematic / emotional
        "Flock_of_birds_flying_upward_20260911153702.mp4": ["growth", "upward", "rise", "momentum", "ascend", "climb"],
        "Black_panther_roaring_in_flames_20260911153855.mp4": ["power", "beast", "fearless", "bold", "fierce", "strong"],
    },

    "luxury": {
        "buggatti_jet.mp4":                                     ["jet", "private jet", "flying", "travel", "bugatti"],
        "bmw.mp4":                                              ["bmw", "car", "drive", "speed", "vehicle"],
        "spead_car.mp4":                                        ["car", "supercar", "ferrari", "lamborghini", "speed", "race", "fast"],
        "luxury.1.mp4":                                         ["luxury", "mansion", "penthouse", "villa", "lifestyle", "exclusive"],
        "luxury_view_building.mp4":                             ["building", "penthouse", "apartment", "office", "city"],
        "luxury_watch_view.mp4":                                ["watch", "rolex", "premium", "status", "flex"],
        "Adding_running_chaotic_motion_20260911155141.mp4":      ["energy", "fast", "dynamic", "action", "chaotic", "running"],
        "Animate_picture_in_slow_motion_20260911155031.mp4":     ["slow", "cinematic", "premium", "smooth", "aesthetic"],
        "Tech_video_sequence_generation_p._20260911152335.mp4":  ["tech", "ai", "future", "digital", "innovation"],
    },

    "content_assets": {
        "viral_graph.mp4":              ["viral", "views", "analytics", "reach", "data", "impression", "graph"],
        "million of clips.mp4":         ["clips", "clipping", "shorts", "automate", "scale", "million clips", "bulk"],
        "tone of clip.mp4":             ["tone", "voice", "style", "content", "vibe"],
        "content_growth.mp4":           ["growth", "growing", "grow", "audience", "followers", "subscriber"],
        "higher_graph.mp4":             ["graph", "growth", "metric", "engagement", "scale", "higher"],
        "digital_monoply.mp4":          ["digital", "online", "internet", "platform", "monopoly"],
        "editing.mp4":                  ["editing", "editor", "edit", "thumbnail", "cut"],
        "networks.mp4":                 ["network", "networking", "social media", "connection"],
        "networks_from_clipping.mp4":   ["agency", "business", "brand", "niche", "system", "workflow"],
        "quant_wealth.mp4":             ["monetize", "monetization", "revenue", "income stream", "passive", "sponsorship"],
        "Youtube_button.mP4":           ["youtube", "channel", "subscribe", "youtube button"],
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

    # 2) Fallback: Semantic filename match (NO RANDOM CLIPS)
    # If the word matches part of the filename, use it! Extremely precise.
    try:
        if os.path.exists(folder):
            candidates = [
                f for f in os.listdir(folder)
                if f.lower().endswith((".mp4", ".mov", ".avi", ".webm"))
            ]
            
            for f in candidates:
                name_no_ext = os.path.splitext(f)[0].lower()
                # Remove common separators for better matching (e.g. "trading_chart" -> "trading chart")
                clean_name = name_no_ext.replace("_", " ").replace("-", " ")
                if word_lower in clean_name or clean_name in word_lower:
                    path = os.path.join(folder, f)
                    return path
                    
    except Exception as e:
        log.error(f"[SMART_BROLL] Error reading folder {folder}: {e}")
        
    log.info(f"[SMART_BROLL] No precise B-Roll found for word '{word_lower}' in {category}. Skipping to avoid irrelevant b-roll.")
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

        # Anti-repeat removed: We prefer to repeat a 100% precise asset 
        # (e.g. showing the same trading chart if they say 'strategy' twice) 
        # rather than randomly injecting an irrelevant video.

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
