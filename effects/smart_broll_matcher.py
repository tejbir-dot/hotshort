"""
Smart Local B-Roll Matcher v2 - INTELLIGENT DESIGN
====================================================
Maps transcript speech (with timestamps) to local video assets.

Architecture: Direct Asset Scoring (No Category Middleman)
----------------------------------------------------------
OLD BROKEN DESIGN:
  text ? keyword ? CATEGORY ? random.choice(clips_in_category) ? GARBAGE

NEW INTELLIGENT DESIGN:
  text ? score EVERY asset directly ? pick HIGHEST scored asset ? PRECISE

Each asset has its own INTENT list (what this video visually represents).
Matching is done by computing an overlap score between the spoken text
and every asset intent, then picking the highest scorer - zero randomness.
"""

import os
import logging
from typing import List, Tuple, Optional

log = logging.getLogger("smart_broll_matcher")

# -----------------------------------------------------------------------------
# ASSET LIBRARY ROOT
# -----------------------------------------------------------------------------
_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "broll_assets")


# -----------------------------------------------------------------------------
# ASSET INTENT MAP
# Every asset has:
#   "path"   : relative path inside _BASE (use forward slashes)
#   "intent" : phrases this clip VISUALLY represents (lowercase)
#   "weight" : quality multiplier (1.0 normal, 1.5 high impact)
#   "avoid"  : words that make this clip WRONG - hard exclude
# -----------------------------------------------------------------------------
ASSET_INTENTS = [
    # -- TRADING SPECIFIC -----------------------------------------------------
    {
        "path": "money_assets/down_fall_in_trading.mp4",
        "intent": ["lose", "losing", "lost", "loss", "downfall", "blow", "blew",
                   "blowing account", "account blown", "mistake", "failed", "failure",
                   "crash", "crashed", "wipe out", "wiped", "negative", "destroyed",
                   "ruined", "liquidated", "margin call", "blow up"],
        "weight": 1.5,
        "avoid": ["win", "profit", "made money", "success", "gaining"],
    },
    {
        "path": "money_assets/volume_trading.mp4",
        "intent": ["volume", "liquidity", "indicator", "indicators", "chart", "charts",
                   "candlestick", "candle", "technical", "technical analysis", "setup",
                   "signal", "entry", "exit", "resistance", "support", "moving average",
                   "rsi", "macd", "analysis", "read the chart"],
        "weight": 1.5,
        "avoid": ["psychology", "mindset", "lifestyle"],
    },
    {
        "path": "money_assets/the_secret_move_big_players.mp4",
        "intent": ["big players", "institutional", "smart money", "manipulation",
                   "market makers", "banks", "hedge fund", "whale", "whales",
                   "they dont want you", "secret move", "hidden", "rigged", "trap",
                   "retail trader", "they want you to"],
        "weight": 1.5,
        "avoid": [],
    },
    {
        "path": "money_assets/trading_freedom.mp4",
        "intent": ["trading for a living", "full time trader", "quit job",
                   "financial freedom through trading", "day trading income",
                   "trade for freedom", "live off trading", "replace your income"],
        "weight": 1.4,
        "avoid": ["lose", "failure"],
    },
    # -- MONEY / WEALTH --------------------------------------------------------
    {
        "path": "money_assets/money_flow.mp4",
        "intent": ["money", "cash", "dollar", "dollars", "earn", "earning",
                   "made", "making money", "wealth", "rich", "riches"],
        "weight": 1.0,
        "avoid": ["lose", "lost", "blew", "failure"],
    },
    {
        "path": "money_assets/payout.mp4",
        "intent": ["payout", "payment", "paid", "paycheck", "get paid",
                   "income", "revenue", "profit", "salary", "commission", "bonus"],
        "weight": 1.0,
        "avoid": ["lose", "lost"],
    },
    {
        "path": "money_assets/bank balance growing.mp4",
        "intent": ["bank", "balance", "savings", "save", "account growing",
                   "watching money grow", "compound", "passive income",
                   "accumulate", "stack", "stacking"],
        "weight": 1.0,
        "avoid": ["lose", "crashed"],
    },
    {
        "path": "money_assets/tones of money.mp4",
        "intent": ["wealth", "abundance", "financial", "millions", "billions",
                   "wealthy", "loaded", "filthy rich", "unlimited money"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/money_succes.mp4",
        "intent": ["success", "successful", "wealthy", "millionaire", "billionaire",
                   "achieve", "achieved", "financial freedom", "made it"],
        "weight": 1.0,
        "avoid": ["lose", "failure"],
    },
    {
        "path": "money_assets/win.mp4",
        "intent": ["win", "winning", "winner", "nailed it", "profitable",
                   "consistently profitable", "goal achieved", "reward", "victory"],
        "weight": 1.2,
        "avoid": ["lose", "failure"],
    },
    # -- PSYCHOLOGY / MINDSET --------------------------------------------------
    {
        "path": "money_assets/mind awakening.mp4",
        "intent": ["mindset", "realize", "realization", "woke up", "awareness",
                   "conscious", "epiphany", "clicked", "understood", "perspective shift",
                   "mental shift", "eye opening"],
        "weight": 1.2,
        "avoid": [],
    },
    {
        "path": "money_assets/deep work.mp4",
        "intent": ["focus", "deep work", "concentrated", "no distractions",
                   "work session", "grind", "locked in", "productive", "output",
                   "work ethic", "hard work", "relentless", "putting in the work"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/obsession.mp4",
        "intent": ["obsessed", "obsession", "driven", "cant stop", "all in",
                   "dedicated", "passionate", "consumed by", "eat sleep breathe"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/sacrifice ,never give up.mp4",
        "intent": ["sacrifice", "never give up", "keep going", "consistent",
                   "commitment", "stay the course", "dont quit", "resilience",
                   "bounce back", "persistent", "showing up every day"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/king.mp4",
        "intent": ["king", "top", "elite", "1%", "top 1 percent", "best",
                   "boss", "empire", "authority", "legend", "top tier"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/the real game.mp4",
        "intent": ["truth", "real", "reality", "the actual game", "what they dont tell you",
                   "nobody talks about", "honest", "brutal truth", "real talk",
                   "exposed", "the truth is", "nobody tells you"],
        "weight": 1.2,
        "avoid": [],
    },
    {
        "path": "money_assets/golden chance.mp4",
        "intent": ["opportunity", "chance", "right now", "window", "rare opportunity",
                   "perfect timing", "golden window", "once in a lifetime", "dont miss",
                   "this is it", "now or never"],
        "weight": 1.2,
        "avoid": [],
    },
    {
        "path": "money_assets/secret roadmap.mp4",
        "intent": ["roadmap", "blueprint", "plan", "system", "framework",
                   "step by step", "exact steps", "formula", "playbook", "method",
                   "strategy", "the plan", "my system"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/1% people.mp4",
        "intent": ["1 percent", "top 1", "elite few", "exclusive", "six figures",
                   "seven figures", "most people dont", "few people", "rare few"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/creative focus work.mp4",
        "intent": ["creative", "creating", "build something", "building",
                   "making something", "creative work", "idea", "ideas"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/war inner beast.mp4",
        "intent": ["inner battle", "fight yourself", "beast mode", "conquer",
                   "overcome", "fearless", "courage", "mental toughness",
                   "inner demon", "war within"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/neurons pathways.mp4",
        "intent": ["neurons", "brain", "learn", "learning", "habits", "habit",
                   "rewire", "pathway", "neural", "repetition builds", "train your brain",
                   "hard wired", "new neural"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/BLIND_FOLLOW.mp4",
        "intent": ["following blindly", "sheep", "crowd", "everyone else",
                   "copy trading", "following the herd", "influenced by",
                   "blind follower", "most traders do", "what everyone does",
                   "doing what everyone", "following someone"],
        "weight": 1.3,
        "avoid": [],
    },
    {
        "path": "money_assets/Warrior.mp4",
        "intent": ["warrior", "fight", "battle", "soldier", "strong mindset",
                   "face challenges", "brave", "face it head on", "go to war",
                   "fighting spirit"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/controlled by.mp4",
        "intent": ["controlled", "matrix", "system controls you", "trapped",
                   "conditioned", "social programming", "stuck", "cant escape",
                   "puppet", "slave to the system"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/controlled_brain_rot.mp4",
        "intent": ["attention", "distracted", "social media addiction", "dopamine",
                   "scrolling", "brain rot", "phone addiction", "unfocused",
                   "wasting time", "cant focus", "doom scrolling"],
        "weight": 1.1,
        "avoid": [],
    },
    {
        "path": "money_assets/FREEDOM.mp4",
        "intent": ["freedom", "free", "liberty", "escape the 9 to 5",
                   "financial freedom", "be your own boss", "independence",
                   "work from anywhere", "no boss", "quit the rat race"],
        "weight": 1.3,
        "avoid": [],
    },
    {
        "path": "money_assets/peace.mp4",
        "intent": ["peace", "calm", "relax", "rest", "mental peace",
                   "inner peace", "quiet mind", "clarity", "zen"],
        "weight": 0.9,
        "avoid": [],
    },
    # -- TECH / AI -------------------------------------------------------------
    {
        "path": "money_assets/algorithm.mp4",
        "intent": ["algorithm", "code", "automated", "automation",
                   "software", "data driven", "programmed"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/human and ai.mp4",
        "intent": ["ai", "artificial intelligence", "machine learning",
                   "automation", "tech", "future of", "robot", "chatgpt"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "money_assets/data centers.mp4",
        "intent": ["data", "server", "scale", "digital infrastructure",
                   "processing", "compute", "cloud"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/processor ,tech.mp4",
        "intent": ["processor", "chip", "speed", "computing power",
                   "technology", "hardware", "fast computing"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/DNA.mp4",
        "intent": ["genetics", "dna", "fundamental", "deep rooted",
                   "built into you", "wired", "innate", "core of who you are"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/writing.mp4",
        "intent": ["write", "writing", "journaling", "note", "document",
                   "script", "tracking", "log", "record", "journal"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/content networking.mp4",
        "intent": ["network", "connection", "community", "relationship",
                   "people around you", "mentors", "inner circle", "network effect"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/luxury view.mp4",
        "intent": ["luxury", "penthouse", "premium view", "high life"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "money_assets/Black_panther_roaring_in_flames_20260911153855.mp4",
        "intent": ["power", "beast", "fearless", "bold", "fierce", "strong",
                   "unstoppable", "dominant", "predator mindset", "apex predator"],
        "weight": 1.1,
        "avoid": [],
    },
    # -- LUXURY / LIFESTYLE ----------------------------------------------------
    {
        "path": "luxury/spead_car.mp4",
        "intent": ["car", "supercar", "ferrari", "lamborghini", "speed",
                   "race", "fast car", "sports car", "exotic car"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "luxury/buggatti_jet.mp4",
        "intent": ["jet", "private jet", "flying", "travel", "bugatti",
                   "air travel", "private plane"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "luxury/bmw.mp4",
        "intent": ["bmw", "sedan", "drive", "car ride", "vehicle",
                   "commute", "on the road"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "luxury/luxury.1.mp4",
        "intent": ["mansion", "penthouse", "villa", "luxury home",
                   "exclusive lifestyle", "high end living"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "luxury/luxury_view_building.mp4",
        "intent": ["office building", "city view", "skyline", "urban",
                   "downtown", "apartment", "city life"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "luxury/luxury_watch_view.mp4",
        "intent": ["watch", "rolex", "time", "timepiece", "premium accessory",
                   "status symbol", "flex"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "luxury/Adding_running_chaotic_motion_20260911155141.mp4",
        "intent": ["energy", "fast paced", "dynamic", "action", "running",
                   "chaotic", "intensity", "hustle"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "luxury/Animate_picture_in_slow_motion_20260911155031.mp4",
        "intent": ["slow motion", "cinematic", "smooth", "premium feel",
                   "aesthetic", "slow", "beautiful"],
        "weight": 0.8,
        "avoid": [],
    },
    {
        "path": "luxury/Tech_video_sequence_generation_p._20260911152335.mp4",
        "intent": ["innovation", "future tech", "digital world", "ai driven",
                   "technology sequence", "next generation"],
        "weight": 0.9,
        "avoid": [],
    },
    # -- CONTENT / CLIPPING ----------------------------------------------------
    {
        "path": "content_assets/viral_graph.mp4",
        "intent": ["viral", "views", "view count", "analytics", "reach",
                   "impression", "graph going up", "trending", "blew up"],
        "weight": 1.2,
        "avoid": [],
    },
    {
        "path": "content_assets/million of clips.mp4",
        "intent": ["clips", "clipping", "shorts", "automate", "scale content",
                   "bulk", "mass", "million clips", "clip factory"],
        "weight": 1.2,
        "avoid": [],
    },
    {
        "path": "content_assets/content_growth.mp4",
        "intent": ["growth", "growing channel", "audience", "followers",
                   "subscribers", "subscriber count", "channel growth"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "content_assets/higher_graph.mp4",
        "intent": ["going up", "higher", "metric", "engagement", "scaling",
                   "growth chart", "upward trend"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "content_assets/editing.mp4",
        "intent": ["editing", "editor", "edit", "cut", "video editing",
                   "thumbnail", "post production"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "content_assets/networks.mp4",
        "intent": ["network", "networking", "social media", "platform",
                   "connections", "digital network"],
        "weight": 0.9,
        "avoid": [],
    },
    {
        "path": "content_assets/networks_from_clipping.mp4",
        "intent": ["clipping agency", "content business", "brand",
                   "niche", "system", "workflow"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "content_assets/quant_wealth.mp4",
        "intent": ["monetize", "monetization", "revenue stream", "income stream",
                   "passive income", "sponsorship", "brand deal"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "content_assets/tone of clip.mp4",
        "intent": ["tone", "voice", "style", "vibe", "content style",
                   "brand voice"],
        "weight": 0.8,
        "avoid": [],
    },
    {
        "path": "content_assets/digital_monoply.mp4",
        "intent": ["digital monopoly", "dominate online", "own the platform",
                   "internet empire", "digital real estate"],
        "weight": 1.0,
        "avoid": [],
    },
    {
        "path": "content_assets/Youtube_button.mP4",
        "intent": ["youtube", "youtube channel", "subscribe", "hit subscribe",
                   "youtube button", "play button"],
        "weight": 1.1,
        "avoid": [],
    },
]

# Build resolved paths once at import time
_RESOLVED_INTENTS = []
for _a in ASSET_INTENTS:
    _full_path = os.path.join(_BASE, _a["path"].replace("/", os.sep))
    if os.path.exists(_full_path):
        _RESOLVED_INTENTS.append({**_a, "full_path": _full_path})
    else:
        log.debug("[SMART_BROLL] Asset not on disk, skipping: %s", _full_path)


# -----------------------------------------------------------------------------
# CORE: Direct Asset Scorer
# -----------------------------------------------------------------------------

def _score_asset_for_text(text: str, asset: dict) -> float:
    """
    Score relevance between spoken text and a single asset.
    +1.0 per single-word intent match
    +2.5 per multi-word phrase match (more specific = higher weight)
    x asset["weight"]
    hard 0.0 if any avoid word matches
    """
    text_lower = text.lower()
    for avoid_word in asset.get("avoid", []):
        if avoid_word in text_lower:
            return 0.0

    score = 0.0
    for phrase in asset["intent"]:
        if phrase in text_lower:
            word_count = len(phrase.split())
            score += (2.5 if word_count > 1 else 1.0)

    return score * asset.get("weight", 1.0)


def _pick_best_asset(text: str, used_assets: set) -> Optional[str]:
    """Score ALL assets vs text, return path of highest-scoring unused asset."""
    scored = []
    for asset in _RESOLVED_INTENTS:
        s = _score_asset_for_text(text, asset)
        if s > 0:
            scored.append((s, asset["full_path"]))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[0])
    for score, path in scored:
        if path not in used_assets:
            log.info("[SMART_BROLL] score=%.2f -> %s", score, os.path.basename(path))
            return path

    # All top candidates used - repeat best (better than irrelevant)
    return scored[0][1]


# -----------------------------------------------------------------------------
# PUBLIC API  (drop-in replacement - same signature)
# -----------------------------------------------------------------------------

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
    Scan transcript segments and find best B-Roll insertion points.
    Returns List of (clip_relative_start_sec, asset_path, cut_duration_sec).
    """
    if not transcript_window:
        return []

    sample_starts = [float(s.get("start", 0)) for s in transcript_window if s.get("text")]
    _is_relative = bool(sample_starts) and max(sample_starts) < clip_duration * 2

    log.info(
        "[SMART_BROLL] mode=%s | segs=%d | src_start=%.1f | clip_dur=%.1f | assets=%d",
        "RELATIVE" if _is_relative else "ABSOLUTE",
        len(transcript_window), source_start, clip_duration, len(_RESOLVED_INTENTS)
    )

    candidates = []
    for i, seg in enumerate(transcript_window):
        t_start = float(seg.get("start", 0))
        text = seg.get("text", "")
        if not text.strip():
            continue

        # Rich context: prev + current + next segment
        ctx_parts = []
        if i > 0:
            ctx_parts.append(transcript_window[i - 1].get("text", ""))
        ctx_parts.append(text)
        if i < len(transcript_window) - 1:
            ctx_parts.append(transcript_window[i + 1].get("text", ""))
        full_context = " ".join(ctx_parts).strip()

        clip_rel_start = t_start if _is_relative else (t_start - source_start)

        # Skip hook (first 3s) and end buffer
        if clip_rel_start < 3.0 or clip_rel_start + cut_duration_s > clip_duration - 0.3:
            continue

        # Find best asset for this moment
        best_score = 0.0
        best_path = None
        for asset in _RESOLVED_INTENTS:
            s = _score_asset_for_text(full_context, asset)
            if s > best_score:
                best_score = s
                best_path = asset["full_path"]

        if best_score <= 0 or best_path is None:
            continue

        log.info("[SMART_BROLL] candidate t=%.2fs score=%.2f asset=%s | '%s'",
                 clip_rel_start, best_score, os.path.basename(best_path), text[:60])

        candidates.append({
            "clip_rel_start": clip_rel_start,
            "score": best_score,
            "asset_path": best_path,
            "context": full_context,
        })

    # Fallback: use cortex keyword hints if transcript had nothing
    if not candidates:
        log.info("[SMART_BROLL] No transcript matches - trying cortex hints.")
        if cortex_keywords:
            hint_text = " ".join(cortex_keywords)
            asset = _pick_best_asset(hint_text, set())
            if asset:
                safe_t = max(3.0, clip_duration / 2.0 - cut_duration_s / 2.0)
                if safe_t + cut_duration_s < clip_duration - 0.3:
                    return [(safe_t, asset, cut_duration_s)]
        return []

    # ─────────────────────────────────────────────────────────────────────────
    # PROFESSIONAL WEIGHTED ARC SELECTION (Cinematographic Zone System)
    # ─────────────────────────────────────────────────────────────────────────
    # Clip is divided into 4 zones based on storytelling structure.
    # Each zone has its own min_score threshold and cut allowance.
    # This prevents clustering and ensures B-roll lands at emotional peaks.
    #
    # Zone layout (% of clip_duration):
    #   HOOK  (0% - 8%)   : BLOCKED — viewer must see the speaker's face
    #   BUILD (8% - 50%)  : max 1 cut, min_score ≥ 0.9
    #   CLIMAX(50% - 85%) : max 2 cuts, min_score ≥ 0.5  ← emotional peak
    #   CTA   (85% - 100%): BLOCKED — clean face for the call-to-action
    # ─────────────────────────────────────────────────────────────────────────

    hook_end    = clip_duration * 0.08   # first 8% → blocked
    build_end   = clip_duration * 0.50   # 8% – 50% → 1 cut, strict threshold
    climax_end  = clip_duration * 0.85   # 50% – 85% → up to 2 cuts, loose threshold
    # CTA zone  = 85% – 100% → blocked

    ZONES = [
        # (zone_name, t_start, t_end, max_cuts_in_zone, min_score)
        ("BUILD",  hook_end,  build_end,  1,   0.90),
        ("CLIMAX", build_end, climax_end, 2,   0.50),
    ]

    selected: List[Tuple[float, str, float]] = []
    used_times: List[float] = []
    used_assets: set = set()

    for zone_name, z_start, z_end, zone_max, z_min_score in ZONES:
        if len(selected) >= max_cuts:
            break

        # Gather candidates that fall inside this zone
        zone_candidates = [
            c for c in candidates
            if z_start <= c["clip_rel_start"] < z_end
            and c["score"] >= z_min_score
        ]

        # Sort within zone by score desc (best first)
        zone_candidates.sort(key=lambda x: -x["score"])

        zone_picked = 0
        for c in zone_candidates:
            if zone_picked >= zone_max:
                break
            if len(selected) >= max_cuts:
                break

            t = c["clip_rel_start"]

            # Enforce global min-gap across all already-selected cuts
            if any(abs(t - ut) < min_cut_gap_s for ut in used_times):
                continue

            asset = c["asset_path"]
            if asset in used_assets:
                asset = _pick_best_asset(c["context"], used_assets)
                if asset is None:
                    continue

            selected.append((t, asset, cut_duration_s))
            used_times.append(t)
            used_assets.add(asset)
            zone_picked += 1

            log.info(
                "[SMART_BROLL] [%s] CONFIRMED cut @ t=%.2fs score=%.2f asset=%s",
                zone_name, t, c["score"], os.path.basename(asset),
            )

    # ── FALLBACK: if we still have room and zones produced < max_cuts, ────────
    # fill from global candidates with min_gap enforced (no zone restriction)
    if len(selected) < max_cuts:
        remaining = [
            c for c in candidates
            if c["clip_rel_start"] >= hook_end                        # respect HOOK block
            and c["clip_rel_start"] + cut_duration_s <= climax_end    # respect CTA block
            and not any(abs(c["clip_rel_start"] - ut) < min_cut_gap_s for ut in used_times)
        ]
        remaining.sort(key=lambda x: -x["score"])
        for c in remaining:
            if len(selected) >= max_cuts:
                break
            t = c["clip_rel_start"]
            if any(abs(t - ut) < min_cut_gap_s for ut in used_times):
                continue
            asset = c["asset_path"]
            if asset in used_assets:
                asset = _pick_best_asset(c["context"], used_assets)
                if asset is None:
                    continue
            selected.append((t, asset, cut_duration_s))
            used_times.append(t)
            used_assets.add(asset)
            log.info(
                "[SMART_BROLL] [FALLBACK] CONFIRMED cut @ t=%.2fs score=%.2f asset=%s",
                t, c["score"], os.path.basename(asset),
            )

    selected.sort(key=lambda x: x[0])
    log.info("[SMART_BROLL] Final: %d B-roll cuts.", len(selected))
    return selected
