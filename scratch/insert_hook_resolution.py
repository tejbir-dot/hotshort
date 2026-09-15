"""
Inserts compute_hook_resolution_bonus() into utils/narrative_intelligence.py
immediately before compute_payoff_resolution_score().
Run once. Safe to re-run (checks if already inserted).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "utils", "narrative_intelligence.py")

MARKER = "def compute_payoff_resolution_score("
GUARD  = "def compute_hook_resolution_bonus("

NEW_CODE = '''# ── HOOK-AWARE RESOLUTION SCORING ─────────────────────────────────────────────
# ending_strength is blind: it evaluates each segment in isolation with no
# awareness of what the hook promised.  This function gives the payoff gate a
# "context thread": it knows what idea was opened and checks whether THIS
# segment is closing it.
#
# Design: additive only.  Never penalizes.  Just rewards segments that
# semantically honor the hook's setup contract.
# ──────────────────────────────────────────────────────────────────────────────

_HOOK_CONTRAST_SIGNALS = frozenset([
    "most people", "everyone thinks", "people think", "you think",
    "most believe", "everyone believes", "nobody knows", "what if",
    "did you know", "ever wonder",
])
_SEG_RESOLUTION_SIGNALS = frozenset([
    "actually", "really", "truth", "one thing", "only", "matters",
    "the answer", "simple", "secret", "key", "turns out", "the real",
    "in reality", "what it comes down to",
])
_HOOK_RES_STOPWORDS = frozenset([
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on",
    "for", "at", "by", "is", "it", "i", "you", "we", "he", "she",
    "they", "this", "that", "with", "are", "was", "be", "so", "do",
])


def compute_hook_resolution_bonus(seg_text: str, hook_text: str, debug: bool = False) -> float:
    """
    Hook-aware payoff bonus.

    The hook opens a semantic contract (question, contrast, challenge).
    This asks: does THIS segment honor that contract?

    Three signals (any combination adds up):
      1. Rhetorical question framing  (+0.35)
         Hook has contrast language and segment is a question.
         "What is the one thing that matters?" resolves "Most people think..."

      2. Contrast resolution          (+0.20)
         Hook has contrast language AND segment has resolution language.

      3. Lexical continuity           (up to +0.25)
         Shared key content words between hook and segment = same idea thread.

    Returns float in [0.0, 0.50]. Never negative. Purely additive.
    Does NOT replace ending_strength — adds a new context-aware dimension.
    """
    if not seg_text or not hook_text:
        return 0.0

    seg_low = seg_text.lower().strip()
    hook_low = hook_text.lower().strip()

    bonus = 0.0
    breakdown = {}

    hook_is_contrast = any(p in hook_low for p in _HOOK_CONTRAST_SIGNALS)
    seg_is_question  = "?" in seg_low

    # Signal 1: rhetorical question closes a contrast setup
    if seg_is_question and hook_is_contrast:
        bonus += 0.35
        breakdown["rhetorical_question_resolves_contrast"] = 0.35

    # Signal 2: resolution language present when hook used contrast language
    seg_has_resolution = any(w in seg_low for w in _SEG_RESOLUTION_SIGNALS)
    if hook_is_contrast and seg_has_resolution:
        bonus += 0.20
        breakdown["contrast_resolved"] = 0.20

    # Signal 3: shared content words = still on the same idea thread
    hook_words = {w for w in hook_low.split() if len(w) > 4 and w not in _HOOK_RES_STOPWORDS}
    seg_words  = {w for w in seg_low.split()  if len(w) > 4 and w not in _HOOK_RES_STOPWORDS}
    shared = hook_words & seg_words
    if shared:
        continuity = min(0.25, len(shared) * 0.10)
        bonus += continuity
        breakdown["lexical_continuity"] = round(continuity, 3)
        breakdown["shared_words"] = sorted(shared)

    final = min(0.50, bonus)
    if debug:
        import logging
        logging.getLogger("narrative_intelligence").info(
            "[HOOK_RESOLUTION] seg=%r hook=%r bonus=%.2f breakdown=%s",
            seg_text[:50], hook_text[:50], final, breakdown,
        )
    return final


'''

with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

if GUARD in content:
    print("Already inserted. Nothing changed.")
else:
    assert MARKER in content, f"Marker '{MARKER}' not found in file"
    content = content.replace(MARKER, NEW_CODE + MARKER, 1)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Inserted successfully. New size: {len(content)} bytes")
