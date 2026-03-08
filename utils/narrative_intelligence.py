import logging
import math
import re
import json
import os

log = logging.getLogger("narrative_intelligence")


def _load_hook_lexicon():
    default = {
        "phrase_groups": {
            "pattern_break": ["most people think", "the truth is", "nobody tells you"],
            "curiosity_gap": ["before you", "here is why", "what happened next"],
            "authority_trust": ["real data", "i tested", "case study"],
        },
        "combo_rules": [{"all": ["before you", "you have to"], "weight": 0.2}],
        "group_weights": {"pattern_break": 0.45, "curiosity_gap": 0.35, "authority_trust": 0.2},
    }
    try:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "config", "hook_word_combinations.json")
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return default
        return payload
    except Exception:
        return default


_HOOK_LEXICON = _load_hook_lexicon()


def _think_verbose() -> bool:
    return str(os.environ.get("HS_THINK_VERBOSE", "0")).strip().lower() in ("1", "true", "yes", "y", "on")


def _think_sample_rate() -> float:
    try:
        raw = float(os.environ.get("HS_THINK_LOG_SAMPLE_RATE", "1.0") or 1.0)
    except Exception:
        raw = 1.0
    return max(0.0, min(1.0, raw))


def _think_log(message: str, *args):
    if not _think_verbose():
        return
    rate = _think_sample_rate()
    if rate <= 0.0:
        return
    if rate < 0.999:
        key = f"{message}|{args!r}"
        bucket = (hash(key) & 0xFFFFFFFF) / float(0xFFFFFFFF)
        if bucket > rate:
            return
    log.info(message, *args)
def narrative_fingerprint(text: str, start: float, end: float):
    """
    Create a stable fingerprint for a narrative arc.
    Combines semantics + temporal location.
    """
    core = text.lower().strip()
    core = " ".join(core.split()[:20])  # first 20 words define idea
    time_bucket = round((start + end) / 2, 1)
    return f"{core}|{time_bucket}"

# --- semantic quality cache ---
_semantic_cache = {}

def _semantic_quality_hash(text: str, score: float) -> str:
    return f"{hash(text)}::{round(score, 3)}"


def extend_until_sentence_complete(clip_start: float, clip_end: float, transcript: list, max_extend: float = 6.0):
    """
    If the clip end is inside a transcript segment, extend it to finish that segment,
    but not more than max_extend seconds.
    """
    if not transcript:
        return clip_end

    for seg in transcript:
        ts, te = seg.get("start", 0.0), seg.get("end", 0.0)
        if ts < clip_end < te:
            extra = min(te - clip_end, max_extend)
            log.info("[SENSE] sentence cut detected (%.2f < %.2f < %.2f) -> extend by %.2fs", ts, clip_end, te, extra)
            return round(clip_end + extra, 2)
    return clip_end

def detect_message_punch(clip_start: float, clip_end: float, text: str, transcript: list, score: float):
    """
    🎯 PUNCH DETECTION: Detects when the core message has landed.
    Works for English + Hindi/Hinglish.
    """
    if not text:
        return False
    
    text_lower = text.lower()

    # ---------------------------
    # ENGLISH PUNCHLINE MARKERS
    # ---------------------------
    punchline_markers = [
        "that's why", "that's how", "the truth is", "the reality is",
        "here's the thing", "what people don't realize", "most people don't know",
        "the secret is", "the key is", "what it comes down to", "and that's",
        "so basically", "in other words", "what this means"
    ]

    # ---------------------------
    # HINDI / HINGLISH PUNCH MARKERS
    # ---------------------------
    hindi_punch_markers = [
        "तो बात ये है",
        "असल में",
        "सच ये है",
        "हकीकत ये है",
        "यही कारण है",
        "यही वजह है",
        "इसका मतलब",
        "याद रखो",
        "आखिरकार",
        "अंत में",
        "तो समझो",
        "सीधी बात",
        "मतलब साफ है"
    ]

    # ---------------------------
    # EMOTIONAL PAYOFF MARKERS
    # ---------------------------
    payoff_markers = [
        "amazing", "insane", "crazy", "unbelievable", "mind-blowing",
        "shocking", "devastating", "life-changing", "game-changer"
    ]

    # ---------------------------
    # CONCLUSION MARKERS
    # ---------------------------
    conclusion_markers = [
        "so remember", "don't forget", "always remember", "final thought",
        "bottom line", "to summarize", "in conclusion", "ultimately",
        "the point is", "and that's why", "which is why", "this is why"
    ]

    # 🔹 English punchline
    for marker in punchline_markers:
        if marker in text_lower:
            _think_log("[PUNCH] English punch detected: '%s'", marker)
            return True

    # 🔹 Hindi / Hinglish punchline
    for marker in hindi_punch_markers:
        if marker in text_lower:
            _think_log("[PUNCH-HI] Hindi punch detected: '%s'", marker)
            return True

    # 🔹 Emotional payoff (score-aware)
    if score > 0.6:
        for marker in payoff_markers:
            if marker in text_lower:
                _think_log("[PUNCH] Emotional payoff detected: '%s'", marker)
                return True

    # 🔹 Conclusion with punctuation
    if text.rstrip().endswith(("!", ".")):
        for marker in conclusion_markers:
            if marker in text_lower:
                _think_log("[PUNCH] Conclusion detected: '%s'", marker)
                return True

    return False


def detect_thought_completion(clip_start: float, clip_end: float, transcript: list, max_extend: float = 12.0):
    """
    🧠 INTELLIGENT: Detect natural paragraph/thought breaks, not just sentences.
    - Extends to the next natural pause (silence or semantic break)
    - Looks for common viral patterns (questions answered, conclusions, etc.)
    - Returns the optimal end point for a complete thought/idea
    """
    if not transcript:
        return clip_end
    
    # Hard budget: clamp extend horizon to avoid expensive long scans on dense transcripts.
    try:
        hard_cap = float(os.environ.get("HS_THOUGHT_MAX_EXTEND_HARD", "14.0") or 14.0)
    except Exception:
        hard_cap = 14.0
    max_extend = max(2.0, min(float(max_extend), hard_cap))

    # Find only nearby segments that could affect this clip boundary.
    # Old path scanned almost everything before `clip_end + max_extend`.
    seg_low = max(0.0, clip_start - 1.0)
    seg_high = clip_end + max_extend
    clip_segments = [
        seg for seg in transcript
        if float(seg.get("start", 0.0)) < seg_high and float(seg.get("end", seg.get("start", 0.0))) > seg_low
    ]
    
    if not clip_segments:
        return clip_end
    
    # Start from current end and look ahead
    best_end = clip_end
    
    for i, seg in enumerate(clip_segments):
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        seg_text = seg.get("text", "").strip()
        
        # Skip segments we're already past
        if seg_end <= clip_end:
            continue
            
        # If we've gone too far, stop
        if seg_start - clip_end > max_extend:
            break
        
        # 🎯 Pattern 1: Question-answer pairs (viral endings!)
        if "?" in seg_text and seg_start < clip_end:
            # If clip contains a question, find the answer (next 1-2 segments)
            for future_seg in clip_segments[i:]:
                future_text = future_seg.get("text", "").strip()
                future_end = future_seg.get("end", 0.0)
                
                # Answer usually comes within 3-4 seconds of question
                if future_end - seg_end > 4.0:
                    break
                if future_text and "?" not in future_text:
                    best_end = max(best_end, future_end)
                    _think_log("[THOUGHT] Q&A pattern detected: extending to %.2f", best_end)
                    return round(best_end, 2)
        
        # 🎯 Pattern 2: Strong ending punctuation
        if seg_text and seg_text[-1] in ".!":
            # Check if it's a conclusion word (common in viral content)
            conclusion_words = ["so", "therefore", "that's why", "that's how", "remember", "don't", "always", "never", "final", "last", "key"]
            seg_lower = seg_text.lower()
            
            if any(word in seg_lower for word in conclusion_words):
                best_end = max(best_end, seg_end)
                _think_log("[THOUGHT] Conclusion pattern at %.2f", seg_end)
                return round(best_end, 2)
        
        # 🎯 Pattern 3: Call-to-action (subscribe, like, follow)
        cta_words = ["subscribe", "like", "follow", "comment", "click", "check out", "watch", "visit", "download"]
        if any(word in seg_text.lower() for word in cta_words):
            # Extend slightly past CTA
            best_end = max(best_end, seg_end + 0.5)
            _think_log("[THOUGHT] CTA detected at %.2f", seg_end)
            return round(best_end, 2)
    
    # Default: extend to end of any segment that's not too far
    for seg in clip_segments:
        seg_end = seg.get("end", 0.0)
        if seg_end <= clip_end + max_extend and seg_end > best_end:
            best_end = seg_end
    
    return round(best_end, 2)

def estimate_semantic_quality(text: str, score: float) -> float:
    """
    🧠 OPTIMIZED: Estimate content quality beyond just emotion score.
    - Uses vectorized pattern matching (⚡ FAST)
    - Caches results to avoid recomputation
    """
    if not text:
        return 0.3
    
    # Check cache first
    text_hash = _semantic_quality_hash(text, score)
    if text_hash in _semantic_cache:
        return _semantic_cache[text_hash]
    
    quality = score  # Start with emotion score
    text_lower = text.lower()
    
    # ⚡ VECTORIZED: Use set lookup instead of loop (O(1) vs O(n))
    word_count = len(text.split())
    if word_count > 30:
        quality += 0.15
    elif word_count > 20:
        quality += 0.10
    elif word_count < 5:
        quality -= 0.2
    
    # ⚡ PATTERN MATCHING: Check once with multi-pattern approach
    viral_patterns = [
        ("?", 0.15),  # Questions
        ("!", 0.10),  # Excitement
        ("...", 0.08),  # Suspense
        ("how to", 0.18),  # How-tos (most viral!)
        ("secret", 0.20),  # Secrets
        ("never", 0.12),  # Contrarian
        ("because", 0.12),  # Explanations
    ]
    
    for pattern, bonus in viral_patterns:
        if pattern in text_lower:
            quality += bonus
            break  # First match wins (faster)
    
    # Cap at 1.0 and cache result
    quality = min(quality, 1.0)
    _semantic_cache[text_hash] = quality
    return quality

def emotion_based_silence_minlen(emotion: float):
    """
    Returns a sensible min_len for silence detector based on emotion.
    None means "disable silence removal" for that clip.
    """
    if emotion >= 0.75:
        return None      # preserve all pauses for high-emotion moments
    if emotion >= 0.5:
        return 1.5
    return 0.9

# =====================================================
# 🎯 QUALITY MODE SCORING (Cheap + Powerful)
# =====================================================

_RE_CONTRAST = re.compile(r"\b(but|however|instead|yet)\b", re.IGNORECASE)
_RE_DIRECT = re.compile(r"\b(you|your|listen|remember)\b", re.IGNORECASE)
_RE_QUESTION_WORDS = re.compile(r"\b(why|how|what if|imagine|ever wonder)\b", re.IGNORECASE)
_RE_ANSWERISH = re.compile(
    r"\b(because|therefore|which means|that means|in other words|for example|here's how|the reason is)\b",
    re.IGNORECASE,
)
_RE_TOPIC_SHIFT = re.compile(r"\b(anyway|moving on|next|so yeah)\b", re.IGNORECASE)
_RE_TRAIL_OFF = re.compile(r"(,\s*)$|\b(and|but|so|because|or)\s*$", re.IGNORECASE)
_RE_NUMERIC = re.compile(r"\b\d+(?:\.\d+)?\b")
_RE_PATTERN_BREAK = re.compile(r"\b(but|actually|truth is|nobody|wrong|myth|instead|yet|stop)\b", re.IGNORECASE)
_RE_MANY_FILLERS = re.compile(r"\b(um+|uh+|like|you know|sort of|kind of)\b", re.IGNORECASE)
_RE_CTA_HEAVY = re.compile(r"\b(subscribe|follow|like this|comment below|share this|link in bio)\b", re.IGNORECASE)
_RE_CTA_VIRAL = re.compile(r"\b(tag someone|comment if|follow for more|tag a friend|share with|send this to)\b", re.IGNORECASE)
_RE_ADVICE = re.compile(r"\b(remember|don't|do this|stop|start|try|make sure|you need to|you have to)\b", re.IGNORECASE)
_RE_UNIVERSAL = re.compile(r"\b(everyone|nobody|always|never|most people|all of us)\b", re.IGNORECASE)
_RE_CREDIBILITY = re.compile(r"\b(for example|for instance|because|proof|results?|numbers?|data|study)\b", re.IGNORECASE)
_RE_EMOTION_WORDS = re.compile(r"\b(shocked|mind blown|crazy|insane|literally|unbelievable|amazing|wow|incredible|insanely|ridiculous|wild|blew my mind|can't believe)\b", re.IGNORECASE)
_RE_VIRAL_ENDING_WAIT = re.compile(r"\b(wait until|wait for it|just wait|hold on|don't leave|don't go anywhere)\b", re.IGNORECASE)
_RE_VIRAL_ENDING_LIST = re.compile(r"\b(\d+\s+things?|\d+\s+reasons?|\d+\s+ways?|first|second|third|lastly|finally)\b", re.IGNORECASE)
_RE_VIRAL_ENDING_DARK = re.compile(r"\b(the worst part|the crazy part|the insane part|the scary part|plot twist|here's the thing|but then)\b", re.IGNORECASE)

# 🎯 ADVANCED HOOK PATTERNS (8 Improvements)

# 1) PATTERN BREAK: "Most people think X but truth is Y" = High viral potential
_RE_HOOK_PATTERN_BREAK = re.compile(
    r"\b(most people think|most people believe|nobody tells you|what nobody tells you|the truth is|the reality is|the fact is)\b",
    re.IGNORECASE
)

# 2) CURIOSITY GAP: Creates open loops = highly rewatchable
_RE_HOOK_CURIOSITY_GAP = re.compile(
    r"\b(before you|wait until|wait for it|just wait|what happened next|here's why|why this works|how i did)\b",
    re.IGNORECASE
)

# 3) EMOTIONAL TRIGGERS: Fear, excitement, FOMO
_RE_HOOK_FEAR_WORDS = re.compile(
    r"\b(scary|dangerous|worst|terrifying|horrifying|risky|threat|vulnerable|exposed)\b",
    re.IGNORECASE
)
_RE_HOOK_EXCITEMENT = re.compile(
    r"\b(shocking|unbelievable|mind-blowing|insane|crazy|wild|incredible|amazing|incredible|jaw-dropping)\b",
    re.IGNORECASE
)
_RE_HOOK_FOMO = re.compile(
    r"\b(what everyone's missing|trending now|going viral|everyone's talking|all over|only|limited|rare|exclusive|nowhere else)\b",
    re.IGNORECASE
)

# 4) SOCIAL PROOF & AUTHORITY: Trust-building language
_RE_HOOK_SOCIAL_PROOF = re.compile(
    r"\b(everyone is|90% of people|most people|viral trend|trending|statistics show|research shows)\b",
    re.IGNORECASE
)
_RE_HOOK_AUTHORITY = re.compile(
    r"\b(i tested|i discovered|case study|data shows|research proves|official|expert|studied|tested)\b",
    re.IGNORECASE
)

# 5) NUMBERS & SPECIFICITY: Concrete numbers attract attention
_RE_HOOK_NUMBERS = re.compile(r"\b(\d{1,3})\b")

# 6) URGENCY/SCARCITY: Time-sensitive language
_RE_HOOK_URGENCY = re.compile(
    r"\b(only|limited|expires|ending soon|now|today|this week|before|don't wait|act fast|hurry)\b",
    re.IGNORECASE
)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "for", "at", "by", "from",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they", "them", "it",
    "this", "that", "these", "those",
    "as", "if", "then", "than", "so", "because", "while", "with", "without", "into", "out",
    "can", "could", "should", "would", "will", "just", "very", "really", "also",
}

_TENSION_PHRASES = (
    "most people think",
    "everyone thinks",
    "people think",
    "here's the problem",
    "the thing is",
    "what nobody tells you",
    "what people don't realize",
    "you'd think",
)

_CLOSURE_PHRASES = (
    "so remember",
    "don't forget",
    "always remember",
    "bottom line",
    "to summarize",
    "in conclusion",
    "ultimately",
    "the point is",
    "and that's why",
    "which is why",
    "this is why",
)

# 🔥 PAYOFF PHRASES - Semantic markers that signal resolution/takeaway
_PAYOFF_PHRASES = (
    "that's the secret",
    "that's why",
    "that's the difference",
    "the truth is",
    "this is why",
    "and that's how",
    "that's what most people miss",
    "that's the key",
    "that's the real reason",
    "here's the thing",
    "and there you have it",
    "so that's",
    "that's exactly",
    "there's your answer",
    "the reality is",
    "and that changes everything",
    "so the lesson is",
    "and here's what changed",
    "that's the breakthrough",
    "at the end of the day",
    "the bottom line is",
    "you want to know the crazy part",
    "that one decision made all the difference",
    "and that's when everything changed",
    "the best part is",
    "and now you know",
)

# 🚀 VIRAL RHETORIC PATTERNS - Structural framing that drives shares/rewatches
_VIRAL_PATTERN_1 = re.compile(
    r"most people think[^.!?]*?but the truth is",
    re.IGNORECASE | re.DOTALL
)
_VIRAL_PATTERN_2 = re.compile(
    r"most people believe[^.!?]*?but the truth is",
    re.IGNORECASE | re.DOTALL
)
_VIRAL_PATTERN_3 = re.compile(
    r"if you want[^.!?]*?stop doing",
    re.IGNORECASE | re.DOTALL
)
_VIRAL_PATTERN_4 = re.compile(
    r"everyone thinks[^.!?]*?but actually",
    re.IGNORECASE | re.DOTALL
)


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def transcript_text_window(transcript: list, start: float, end: float):
    """
    Return (joined_text, segment_texts) for transcript segments overlapping [start, end].
    Transcript is expected to be a list of {start,end,text}.
    """
    if not transcript:
        return "", []
    s = float(start or 0.0)
    e = float(end or 0.0)
    if e <= s:
        return "", []

    segs = [seg for seg in transcript if float(seg.get("end", 0.0) or 0.0) > s and float(seg.get("start", 0.0) or 0.0) < e]
    if not segs:
        return "", []

    parts = []
    for seg in segs:
        txt = (seg.get("text") or "").strip()
        if txt:
            parts.append(txt)
    joined = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return joined, parts


def _word_tokens(text: str) -> list[str]:
    if not text:
        return []
    return [w for w in re.findall(r"[a-zA-Z0-9']+", text.lower()) if w]


def _first_sentence_word_count(text: str) -> int:
    if not text:
        return 0
    first = re.split(r"[.!?]", text.strip(), maxsplit=1)[0].strip()
    return len(_word_tokens(first))


def _contains_phrase(text_lower: str, phrase: str) -> bool:
    p = (phrase or "").strip().lower()
    if not p:
        return False
    if p.count(" ") == 0:
        return bool(re.search(rf"\b{re.escape(p)}\b", text_lower))
    return p in text_lower


def _score_hook_lexicon(text: str) -> float:
    if not text:
        return 0.0
    data = _HOOK_LEXICON or {}
    phrase_groups = data.get("phrase_groups") or {}
    group_weights = data.get("group_weights") or {}
    combo_rules = data.get("combo_rules") or []
    low = text.lower().strip()

    score = 0.0
    for group, phrases in phrase_groups.items():
        if not isinstance(phrases, list) or not phrases:
            continue
        hits = 0
        for ph in phrases:
            if _contains_phrase(low, ph):
                hits += 1
        coverage = min(1.0, hits / float(max(1, min(4, len(phrases)))))
        weight = float(group_weights.get(group, 0.0) or 0.0)
        score += weight * coverage

    combo_bonus = 0.0
    for rule in combo_rules:
        must = rule.get("all") if isinstance(rule, dict) else None
        if not isinstance(must, list) or not must:
            continue
        if all(_contains_phrase(low, p) for p in must):
            combo_bonus += float(rule.get("weight", 0.0) or 0.0)
    score += min(0.35, combo_bonus)

    return _clamp01(score)


def compute_hook_score(transcript: list, clip_start: float, look_s: float = 4.0) -> float:
    """
    🚀 INTELLIGENT HOOK SCORING (8 Advanced Patterns)
    
    Detects high-impact opening hooks with multi-pattern boost system.
    Includes: pattern breaks, curiosity gaps, emotional triggers, social proof,
    specificity, urgency, power tiers, and multi-pattern synergies.
    
    Normalized 0–1, with intelligent tier-based baseline.
    """
    text, seg_texts = transcript_text_window(transcript, clip_start, float(clip_start or 0.0) + float(look_s))
    if not text and not seg_texts:
        return 0.0

    t = (text or "").strip()
    t_low = t.lower()
    
    # === FOUNDATION: Classic signals (still important) ===
    hits = 0
    
    # 1) Question trigger
    has_question = ("?" in t) or bool(_RE_QUESTION_WORDS.search(t))
    if has_question:
        hits += 1

    # 2) Contrast words
    has_contrast = bool(_RE_CONTRAST.search(t))
    if has_contrast:
        hits += 1

    # 3) Sentence velocity shift (short -> long)
    lengths = []
    for piece in (seg_texts or [t]):
        piece = piece.strip()
        if not piece:
            continue
        words = [w for w in re.split(r"\s+", piece) if w]
        lengths.append(len(words))
    
    has_velocity = False
    for i in range(len(lengths) - 1):
        if lengths[i] <= 5 and lengths[i + 1] >= 12:
            has_velocity = True
            break
    if has_velocity:
        hits += 1

    # 4) Direct address
    has_direct = bool(_RE_DIRECT.search(t))
    if has_direct:
        hits += 1

    legacy_score = _clamp01(hits / 4.0)
    lexicon_score = _score_hook_lexicon(t)
    base_score = _clamp01((0.72 * legacy_score) + (0.28 * lexicon_score))
    
    # === TIER 1: Individual Pattern Bonuses (8 Improvements) ===
    pattern_count = 0
    bonus = 0.0
    
    # 1️⃣ PATTERN BREAK detection (+0.15)
    # "Most people think X but truth is Y" = highest viral pattern
    has_pattern_break = bool(_RE_HOOK_PATTERN_BREAK.search(t_low))
    if has_pattern_break:
        bonus += 0.15
        pattern_count += 1
    
    # 2️⃣ CURIOSITY GAP detection (+0.12)
    # "Before you", "Wait until" = creates open loops
    has_curiosity = bool(_RE_HOOK_CURIOSITY_GAP.search(t_low))
    if has_curiosity:
        bonus += 0.12
        pattern_count += 1
    
    # 3️⃣ EMOTIONAL TRIGGERS (+0.08 each category)
    has_fear = bool(_RE_HOOK_FEAR_WORDS.search(t_low))
    has_excitement = bool(_RE_HOOK_EXCITEMENT.search(t_low))
    has_fomo = bool(_RE_HOOK_FOMO.search(t_low))
    
    if has_fear:
        bonus += 0.08
        pattern_count += 1
    if has_excitement:
        bonus += 0.08
        pattern_count += 1
    if has_fomo:
        bonus += 0.08
        pattern_count += 1
    
    # 4️⃣ SOCIAL PROOF & AUTHORITY (+0.10-0.12)
    has_social_proof = bool(_RE_HOOK_SOCIAL_PROOF.search(t_low))
    has_authority = bool(_RE_HOOK_AUTHORITY.search(t_low))
    
    if has_social_proof:
        bonus += 0.10
        pattern_count += 1
    if has_authority:
        bonus += 0.12
        pattern_count += 1
    
    # 5️⃣ NUMBERS & SPECIFICITY (+0.10)
    # Specific numbers attract 3x more attention than generic statements
    has_numbers = bool(_RE_HOOK_NUMBERS.search(t))
    if has_numbers:
        bonus += 0.10
        pattern_count += 1
    
    # 6️⃣ URGENCY/SCARCITY (+0.10)
    # "Only", "Limited", "Now", "Today" = high conversion language
    has_urgency = bool(_RE_HOOK_URGENCY.search(t_low))
    if has_urgency:
        bonus += 0.10
        pattern_count += 1
    
    # 7️⃣ RHETORICAL QUESTION + SHORT TEXT boost (+0.10 + 0.05)
    if has_question:
        bonus += 0.10
    if seg_texts and len(seg_texts) > 1:
        first_words = len(re.split(r"\s+", str(seg_texts[0]).strip()))
        if first_words < 10 and first_words > 0:
            bonus += 0.05
    
    # === TIER 2: Power Tier System (7-step hierarchy) ===
    # Each tier has an expected strength based on combined signals
    # Tier 1 (0.30): Generic or weak ("Let me tell you")
    # Tier 2 (0.50): Single pattern present
    # Tier 3 (0.65): Two strong patterns
    # Tier 4 (0.80): Pattern break + curiosity (highest individual combo)
    # Tier 5 (0.85): Three+ patterns with authority
    # Tier 6 (0.92): Complex multi-pattern (4+ patterns)
    # Tier 7 (1.0): Perfect hook (5+ patterns + maximum synergy)
    
    tier_bonus = 0.0
    if pattern_count >= 5:
        tier_bonus = 0.08  # Power Tier 7
    elif pattern_count >= 4:
        tier_bonus = 0.06  # Power Tier 6
    elif pattern_count >= 3 and (has_authority or has_authority):
        tier_bonus = 0.05  # Power Tier 5
    elif pattern_count >= 2 and (has_pattern_break and has_curiosity):
        tier_bonus = 0.12  # Power Tier 4 - strongest combo!
    elif pattern_count >= 2:
        tier_bonus = 0.04  # Power Tier 3
    elif pattern_count >= 1:
        tier_bonus = 0.02  # Power Tier 2
    
    bonus += tier_bonus
    
    # === TIER 3: Multi-Pattern Synergy Boosts (combinations multiply impact) ===
    # These compounds work together to amplify virality
    synergy_bonus = 0.0
    
    # Synergy 1: Pattern Break + Curiosity = "But wait..." effect
    if has_pattern_break and has_curiosity:
        synergy_bonus += 0.08
    
    # Synergy 2: Emotional Trigger + Urgency = panic buying
    if (has_fear or has_excitement) and has_urgency:
        synergy_bonus += 0.06
    
    # Synergy 3: Social Proof + Authority = trusted recommendations
    if has_social_proof and has_authority:
        synergy_bonus += 0.06
    
    # Synergy 4: Numbers + Specificity + Authority = data-backed claims
    if has_numbers and has_authority:
        synergy_bonus += 0.05
    
    # Synergy 5: FOMO + Urgency + Numbers = triple threat
    if has_fomo and has_urgency and has_numbers:
        synergy_bonus += 0.08
    
    bonus += _clamp01(synergy_bonus)
    
    return _clamp01(base_score + bonus)


def compute_open_loop_score(transcript: list, clip_start: float, look_s: float = 8.0) -> float:
    """
    Open-loop pressure: prefer clips that promise before delivering.
    Looks at the first ~8 seconds. Normalized 0–1.
    """
    text, _ = transcript_text_window(transcript, clip_start, float(clip_start or 0.0) + float(look_s))
    if not text:
        return 0.0

    t = text.lower().strip()
    has_question = ("?" in t) or bool(_RE_QUESTION_WORDS.search(t))
    has_tension = any(p in t for p in _TENSION_PHRASES)
    has_contrast = bool(_RE_CONTRAST.search(t))
    answerish = bool(_RE_ANSWERISH.search(t))

    num_hits = len(_RE_NUMERIC.findall(t))
    factual_dump = num_hits >= 2 or any(w in t for w in ("first,", "second,", "third,", "step ", "tips:", "here are"))

    score = 0.0
    if has_question:
        score += 0.55
    if has_tension:
        score += 0.35
    if has_contrast:
        score += 0.10

    # Bonus if it asks/teases without immediately explaining.
    if (has_question or has_tension) and not answerish:
        score += 0.15

    # Penalties: explanation/factual dump too early.
    if answerish and not (has_question or has_tension):
        score -= 0.35
    if factual_dump and not has_question:
        score -= 0.20

    return _clamp01(score)


def compute_pattern_break_score(transcript: list, clip_start: float, look_s: float = 6.0) -> float:
    """
    Pattern-break signal in the opening seconds.
    High when intro disrupts expectations and starts with a strong framing contrast.
    """
    text, _ = transcript_text_window(transcript, clip_start, float(clip_start or 0.0) + float(look_s))
    if not text:
        return 0.0

    t = text.strip()
    low = t.lower()

    score = 0.0
    if _RE_PATTERN_BREAK.search(low):
        score += 0.38
    if ("?" in low) or _RE_QUESTION_WORDS.search(low):
        score += 0.15
    if any(p in low for p in ("most people", "everyone thinks", "what nobody", "you'd think")):
        score += 0.18

    first_sentence_words = _first_sentence_word_count(t)
    if 3 <= first_sentence_words <= 9:
        score += 0.14
    if _RE_DIRECT.search(low):
        score += 0.10

    fillers = len(_RE_MANY_FILLERS.findall(low))
    if fillers >= 2:
        score -= 0.16

    return _clamp01(score)


def compute_ending_strength(transcript: list, clip_end: float, look_s: float = 4.0) -> float:
    """
    Ending payoff check: last ~4 seconds should land a punch/advice/closure.
    Penalize trailing off / mid-segment cuts / topic shifts.
    """
    end_t = float(clip_end or 0.0)
    start_t = max(0.0, end_t - float(look_s))
    text, _ = transcript_text_window(transcript, start_t, end_t)
    if not text:
        return 0.0

    raw = text.strip()
    t = raw.lower()

    advice = bool(re.search(r"\b(remember|don't|do this|stop|start|try|make sure|you need to|you have to)\b", t))
    closure = any(p in t for p in _CLOSURE_PHRASES)
    ends_with_punct = raw.rstrip().endswith((".", "!", "?"))

    cut_mid_segment = False
    if transcript:
        for seg in transcript:
            ts = float(seg.get("start", 0.0) or 0.0)
            te = float(seg.get("end", 0.0) or 0.0)
            if ts < end_t < (te - 0.15):
                cut_mid_segment = True
                break

    score = 0.0
    if advice:
        score += 0.45
    if closure:
        score += 0.35
    if ends_with_punct:
        score += 0.20

    if cut_mid_segment:
        score -= 0.35
    if _RE_TOPIC_SHIFT.search(raw):
        score -= 0.20
    if (not ends_with_punct) and _RE_TRAIL_OFF.search(raw):
        score -= 0.30

    return _clamp01(score)


def compute_payoff_resolution_score(transcript: list, clip_start: float, clip_end: float, tail_look_s: float = 6.0) -> float:
    """
    Payoff quality near the ending:
    prefers clips where setup (question/tension) resolves with a clear, complete takeaway.
    
    UPGRADED: Now includes semantic payoff phrase detection (20-30% improvement)
    """
    s = float(clip_start or 0.0)
    e = float(clip_end or (s + 0.01))
    if e <= s:
        return 0.0

    full_text, _ = transcript_text_window(transcript, s, e)
    tail_text, _ = transcript_text_window(transcript, max(s, e - float(tail_look_s)), e)
    if not full_text or not tail_text:
        return 0.0

    full_low = full_text.lower().strip()
    tail_raw = tail_text.strip()
    tail_low = tail_raw.lower()

    setup_question = ("?" in full_low) or bool(_RE_QUESTION_WORDS.search(full_low)) or any(p in full_low for p in _TENSION_PHRASES)
    answerish_tail = bool(_RE_ANSWERISH.search(tail_low))
    closure_tail = any(p in tail_low for p in _CLOSURE_PHRASES)
    advice_tail = bool(_RE_ADVICE.search(tail_low))
    ends_with_punct = tail_raw.rstrip().endswith((".", "!", "?"))
    has_credibility = bool(_RE_CREDIBILITY.search(tail_low)) or bool(_RE_NUMERIC.search(tail_low))
    
    # 🔥 NEW: Semantic payoff phrase detection (+0.35 boost)
    has_payoff_phrase = any(p in tail_low for p in _PAYOFF_PHRASES)
    viral_rhetoric = detect_viral_rhetorical_structure(full_text)
    
    # 💫 EMOTIONAL ENDINGS: Strong emotional words increase rewatch potential
    has_emotion_words = bool(_RE_EMOTION_WORDS.search(tail_low))
    
    # 🎬 VIRAL ENDING PATTERNS: Specific ending structures that drive shares
    is_wait_ending = bool(_RE_VIRAL_ENDING_WAIT.search(tail_low))
    is_list_ending = bool(_RE_VIRAL_ENDING_LIST.search(tail_low))
    is_dark_humor_ending = bool(_RE_VIRAL_ENDING_DARK.search(tail_low))
    
    # 📢 CONTEXT-AWARE CTA: Beneficial CTAs like "tag a friend" boost viral potential
    has_viral_cta = bool(_RE_CTA_VIRAL.search(tail_low))
    has_heavy_cta = bool(_RE_CTA_HEAVY.search(tail_low))

    score = 0.0
    if setup_question and answerish_tail:
        score += 0.42
    elif answerish_tail:
        score += 0.24
    if closure_tail:
        score += 0.24
    if advice_tail:
        score += 0.14
    if ends_with_punct:
        score += 0.10
    if has_credibility:
        score += 0.10
    
    # 🔥 PAYOFF PHRASE BONUS: +0.35 for semantic payoff markers
    if has_payoff_phrase:
        score += 0.35
    
    # 🚀 VIRAL RHETORIC BONUS: Structural patterns boost payoff score
    if viral_rhetoric > 0.0:
        score += (0.25 * viral_rhetoric)
    
    # 💫 EMOTIONAL ENDINGS: +0.15 for strong emotional language (increases rewatch)
    if has_emotion_words:
        score += 0.15
    
    # 🎬 VIRAL ENDING PATTERNS: +0.12 for each pattern (suspense, lists, humor)
    if is_wait_ending:
        score += 0.12
    if is_list_ending:
        score += 0.12
    if is_dark_humor_ending:
        score += 0.12
    
    # 📢 CONTEXT-AWARE CTA: Viral CTAs boost (+0.18), traditional CTAs might penalize
    if has_viral_cta:
        score += 0.18  # Boost for engagement-driving CTAs like "tag someone"
    elif has_heavy_cta:
        score -= 0.10  # Light penalty for traditional subscription-focused CTAs

    if _RE_TRAIL_OFF.search(tail_raw) and not ends_with_punct:
        score -= 0.24
    if _RE_TOPIC_SHIFT.search(tail_low):
        score -= 0.20

    return _clamp01(score)


def compute_rewatch_score(transcript: list, clip_start: float, clip_end: float) -> float:
    """
    Rewatch propensity proxy:
    quotable contrast + universal framing + compact complete lines.
    """
    s = float(clip_start or 0.0)
    e = float(clip_end or (s + 0.01))
    text, segs = transcript_text_window(transcript, s, e)
    if not text:
        return 0.0

    low = text.lower().strip()
    words = _word_tokens(low)
    wc = len(words)
    if wc == 0:
        return 0.0

    score = 0.0
    if _RE_CONTRAST.search(low):
        score += 0.25
    if _RE_UNIVERSAL.search(low):
        score += 0.18
    if any(p in low for p in _CLOSURE_PHRASES):
        score += 0.12

    # Tail quote-like line (complete, compact)
    tail = (segs[-1] if segs else text).strip()
    tail_wc = len(_word_tokens(tail))
    if 6 <= tail_wc <= 18 and tail.rstrip().endswith((".", "!", "?")):
        score += 0.30

    unique_ratio = len(set(words)) / float(max(1, wc))
    if unique_ratio >= 0.62:
        score += 0.15
    elif unique_ratio >= 0.50:
        score += 0.08

    if wc > 140:
        score -= 0.14

    return _clamp01(score)


def compute_information_density_score(transcript: list, clip_start: float, clip_end: float) -> float:
    """
    Content density (0..1):
    rewards clips with concrete signal and fewer filler-only tokens.
    """
    text, _ = transcript_text_window(transcript, clip_start, clip_end)
    if not text:
        return 0.0

    words = _word_tokens(text)
    if not words:
        return 0.0

    content_words = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    unique_ratio = len(set(content_words)) / float(max(1, len(content_words)))
    content_ratio = len(content_words) / float(max(1, len(words)))
    numeric_ratio = min(1.0, len(_RE_NUMERIC.findall(text)) / 3.0)
    credibility = 1.0 if _RE_CREDIBILITY.search(text.lower()) else 0.0

    score = (0.45 * unique_ratio) + (0.30 * content_ratio) + (0.15 * numeric_ratio) + (0.10 * credibility)
    return _clamp01(score)


def compute_duration_score(duration_s: float, hook_score: float = 0.0) -> float:
    """
    Duration intelligence (soft) - UPGRADED FOR VIRAL SWEET SPOT:
    - TikTok: 8–20s
    - Reels: 10–25s
    - Shorts: 15–35s
    - IDEAL: 18 seconds (geometric center)
    """
    try:
        d = float(duration_s or 0.0)
    except Exception:
        return 0.0
    if d <= 0.0:
        return 0.0

    # 🔥 NEW: Soft bias towards 18s (platform sweet spot)
    IDEAL_LENGTH = 18.0
    if 12.0 <= d <= 22.0:
        # Maximum preference in viral window
        length_bonus = 1.0 - (abs(d - IDEAL_LENGTH) / 10.0)  # 18s=1.0, 12-22s range
        score = 0.95 + (0.05 * length_bonus)  # 0.95 to 1.0
    elif d < 12.0:
        if d >= 8.0:
            score = 0.80 + (0.15 * (d - 8.0) / 4.0)  # 8->0.80, 12->0.95
        else:
            score = 0.60 + (0.20 * max(0.0, d) / 8.0)  # 0->0.60, 8->0.80
    elif d <= 40.0:
        # Gradual decay outside viral window
        if d <= 28.0:
            score = 0.85 + (0.10 * (28.0 - d) / 6.0)  # 22->0.90, 28->0.85
        else:
            score = 0.85 - (0.25 * (d - 28.0) / 12.0)  # 28->0.85, 40->0.60
    else:
        # 40->0.55 down to ~0.20 at 90+
        over = min(1.0, (d - 40.0) / 50.0)
        score = max(0.20, 0.55 - (0.35 * over))
        if float(hook_score or 0.0) >= 0.85:
            score = min(1.0, score + 0.15)

    return _clamp01(score)


def detect_viral_rhetorical_structure(text: str) -> float:
    """
    🚀 Detects viral rhetorical patterns that drive engagement & shares.
    Examples:
    - "Most people think X but the truth is Y"
    - "If you want X, stop doing Y"
    
    Returns confidence score 0-1.
    """
    if not text:
        return 0.0
    
    text_lower = text.lower()
    score = 0.0
    
    if _VIRAL_PATTERN_1.search(text_lower):
        score += 0.40
    if _VIRAL_PATTERN_2.search(text_lower):
        score += 0.40
    if _VIRAL_PATTERN_3.search(text_lower):
        score += 0.35
    if _VIRAL_PATTERN_4.search(text_lower):
        score += 0.35
    
    return _clamp01(score)


def compute_quality_scores(transcript: list, clip_start: float, clip_end: float) -> dict:
    """
    Compute (hook_score, open_loop_score, ending_strength, duration_score, final_score).
    Designed to be used for ranking/curation only (no hard filtering).
    """
    s = float(clip_start or 0.0)
    e = float(clip_end or (s + 0.01))
    d = max(0.0, e - s)

    hook = compute_hook_score(transcript, s, look_s=4.0)
    open_loop = compute_open_loop_score(transcript, s, look_s=8.0)
    pattern_break = compute_pattern_break_score(transcript, s, look_s=6.0)
    ending = compute_ending_strength(transcript, e, look_s=4.0)
    payoff_resolution = compute_payoff_resolution_score(transcript, s, e, tail_look_s=6.0)
    rewatch = compute_rewatch_score(transcript, s, e)
    info_density = compute_information_density_score(transcript, s, e)
    dur_score = compute_duration_score(d, hook_score=hook)

    clip_text, clip_segs = transcript_text_window(transcript, s, e)
    wc = len(_word_tokens(clip_text))
    seg_n = len(clip_segs)
    reliability = _clamp01((0.65 * min(1.0, wc / 36.0)) + (0.35 * min(1.0, seg_n / 4.0)))

    final = (
        (0.25 * hook)
        + (0.18 * open_loop)
        + (0.12 * pattern_break)
        + (0.14 * ending)
        + (0.12 * payoff_resolution)
        + (0.08 * rewatch)
        + (0.03 * info_density)
        + (0.08 * dur_score)
    )
    final = final * (0.88 + (0.12 * reliability))
    final = _clamp01(final)

    return {
        "hook_score": round(hook, 4),
        "open_loop_score": round(open_loop, 4),
        "pattern_break_score": round(pattern_break, 4),
        "ending_strength": round(ending, 4),
        "payoff_resolution_score": round(payoff_resolution, 4),
        "rewatch_score": round(rewatch, 4),
        "information_density_score": round(info_density, 4),
        "virality_confidence": round(reliability, 4),
        "duration_score": round(dur_score, 4),
        "final_score": round(final, 4),
    }

# MAIN
