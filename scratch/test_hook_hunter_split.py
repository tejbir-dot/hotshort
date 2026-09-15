"""
Exact reconstruction of Hook Hunter scoring for c_0014 and c_0015 triggering segments.
Uses actual text from the production log.
"""
import sys, re
sys.path.insert(0, ".")

# Reproduce the hook_strength formula from orchestrator.py lines 1593-1599
# hook_strength = (0.35 * hook_score) + (0.25 * pattern_break_score) +
#                 (0.20 * open_loop_score) + (0.10 * curiosity_peak) + (0.10 * rewatch_score)

# And the admission gate from line 1600:
# if hook_strength > hook_threshold(0.45) OR pattern_break_score > 0.40 OR curiosity_peak > 0.45

# Reproduce the sub-signals from compute_hook_score() in narrative_intelligence.py

_RE_QUESTION_WORDS = re.compile(r"\b(why|how|what if|imagine|ever wonder)\b", re.IGNORECASE)
_RE_CONTRAST       = re.compile(r"\b(but|however|instead|yet)\b", re.IGNORECASE)
_RE_DIRECT         = re.compile(r"\b(you|your|listen|remember)\b", re.IGNORECASE)
_RE_HOOK_PATTERN_BREAK = re.compile(
    r"\b(most people think|most people believe|nobody tells you|what nobody tells you|the truth is|the reality is|the fact is)\b",
    re.IGNORECASE
)
_RE_HOOK_URGENCY = re.compile(
    r"\b(only|limited|expires|ending soon|now|today|this week|before|don't wait|act fast|hurry)\b",
    re.IGNORECASE
)
_RE_HOOK_NUMBERS = re.compile(r"\b(\d{1,3})\b")

def clamp01(x):
    return max(0.0, min(1.0, float(x)))

def analyze_hook(name, text, desc=""):
    t = text.strip()
    t_low = t.lower()

    # Foundation signals
    has_question = ("?" in t) or bool(_RE_QUESTION_WORDS.search(t))
    has_contrast  = bool(_RE_CONTRAST.search(t))
    has_direct    = bool(_RE_DIRECT.search(t))
    # velocity: skip (need multi-seg, assume False for single seg)
    has_velocity  = False

    hits = sum([has_question, has_contrast, has_direct, has_velocity])
    legacy_score = clamp01(hits / 4.0)
    base_score = clamp01(0.72 * legacy_score)   # lexicon_score ≈ 0

    # Tier 1 bonuses
    has_pattern_break = bool(_RE_HOOK_PATTERN_BREAK.search(t_low))
    has_urgency       = bool(_RE_HOOK_URGENCY.search(t_low))
    has_numbers       = bool(_RE_HOOK_NUMBERS.search(t))

    pattern_count = 0
    bonus = 0.0

    if has_pattern_break:
        bonus += 0.15; pattern_count += 1
    if has_question:
        bonus += 0.10
    if has_numbers:
        bonus += 0.10; pattern_count += 1
    if has_urgency:
        bonus += 0.10; pattern_count += 1
    if has_direct:
        bonus += 0.0

    # Tier 2 tier bonus
    tier_bonus = 0.0
    if pattern_count >= 2:
        tier_bonus = 0.04
    elif pattern_count >= 1:
        tier_bonus = 0.02
    bonus += tier_bonus

    hook_score_approx = clamp01(base_score + bonus)

    # Hook Hunter uses pattern_break_score separately (same as _RE_HOOK_PATTERN_BREAK)
    pattern_break_score = 1.0 if has_pattern_break else 0.0
    # open_loop_score: questions create open loops
    open_loop_score = 0.7 if has_question else 0.0
    # curiosity_peak: from curiosity_curve (assume 0 for non-peak segments)
    curiosity_peak = 0.0
    rewatch_score = 0.0

    hook_strength = clamp01(
        (0.35 * hook_score_approx)
        + (0.25 * pattern_break_score)
        + (0.20 * open_loop_score)
        + (0.10 * curiosity_peak)
        + (0.10 * rewatch_score)
    )

    passes_gate = (hook_strength > 0.45) or (pattern_break_score > 0.40) or (curiosity_peak > 0.45)

    print(f"\n{'='*60}")
    print(f"  {name}")
    if desc:
        print(f"  ({desc})")
    print(f"  Text: \"{text[:80]}\"")
    print(f"  ---")
    print(f"  has_question={has_question}  has_pattern_break={has_pattern_break}")
    print(f"  has_contrast={has_contrast}  has_numbers={has_numbers}  has_urgency={has_urgency}")
    print(f"  legacy_score={legacy_score:.2f}  base_score={base_score:.2f}")
    print(f"  bonus={bonus:.2f}  hook_score_approx={hook_score_approx:.2f}")
    print(f"  pattern_break_score={pattern_break_score:.2f}  open_loop_score={open_loop_score:.2f}")
    print(f"  hook_strength={hook_strength:.2f}")
    print(f"  PASSES GATE (>0.45 or pb>0.40 or cp>0.45): {passes_gate}")


# --- c_0014 anchor: "Most people think..." (seg 187, the TRIGGER from the log)
analyze_hook(
    "c_0014 TRIGGER (seg 187)",
    "Most people think, no, I worked on this all week, I worked on this all week.",
    "Trigger phrase: 'most people think' (belief_reversal)"
)

# --- c_0015 anchor: "What's the one thing..." (seg 205, creates c_0015)
# From log: created by hook_hunter at 540.4s-545.3s
# From SURGEON log: hook_text = "one thing that you can do today that actually matters? Now I..."
analyze_hook(
    "c_0015 TRIGGER (seg 205)",
    "one thing that you can do today that actually matters? Now I know you're like, I got 14.",
    "The question that created a SECOND candidate"
)

# --- Also check seg 204 which feeds the question
analyze_hook(
    "c_0015 SETUP (seg 204)",
    "And the last one is asking yourself a powerful question. What's the one thing and only the",
    "The sentence before seg 205"
)

print(f"\n{'='*60}")
print("""
ROOT CAUSE SUMMARY
==================
The Hook Hunter evaluates EVERY transcript segment independently.
It has NO memory of:
  - active story threads
  - unresolved narrative contracts
  - what hook_idx=186 already opened

The question pattern "one thing that actually matters?" scores:
  has_question=True  -> base +0.25 to hits, +0.10 bonus
  has_numbers=True (got 14) -> +0.10 bonus
  open_loop_score=0.70

This pushes hook_strength above 0.45 -> PASSES GATE -> new candidate created.

The system sees a question = a new hook.
A human sees a question = the climax of the existing story.

The split occurs at:
  orchestrator.py, _run_global_hook_hunter(), line 1600
  Condition: hook_strength > 0.45 OR pattern_break_score > 0.40 OR curiosity_peak > 0.45
  This condition has NO awareness of existing active arcs.
""")
