"""
Reproduce exact c_0014 situation from the production log,
using the new 3-segment hook window.
"""
import sys
sys.path.insert(0, ".")
from utils.narrative_intelligence import compute_hook_resolution_bonus

# From the log:
# hook_idx=186: "We got to figure out where are we spending our time."
# hook_idx+1=187: "Most people think, no, I worked on this all week..."
# hook_idx+2=188: "And then it's like, no, if you actually had a timer..."

# OLD: single segment hook
hook_old = "We got to figure out where are we spending our time."

# NEW: 3-segment window
hook_new = (
    "We got to figure out where are we spending our time. "
    "Most people think, no, I worked on this all week, I worked on this all week. "
    "And then it's like, no, if you actually had a timer go off every 15 minutes..."
)

# The two candidates that competed
false_winner = "meaning stop it. That's why you have to batch your meetings of similar things or take"
true_payoff  = "one thing that you can do today that actually matters? Now I know you're like, I got 14."

print("=" * 60)
print("OLD hook (single segment):")
print(f"  false_winner bonus: {compute_hook_resolution_bonus(false_winner, hook_old):.2f}")
print(f"  true_payoff  bonus: {compute_hook_resolution_bonus(true_payoff,  hook_old):.2f}")

print()
print("NEW hook (3-segment window):")
b_false = compute_hook_resolution_bonus(false_winner, hook_new)
b_true  = compute_hook_resolution_bonus(true_payoff,  hook_new)
print(f"  false_winner bonus: {b_false:.2f}")
print(f"  true_payoff  bonus: {b_true:.2f}")

print()
print(f"Gate threshold = 0.30")
print(f"true_payoff now passes gate: {b_true >= 0.30}")
print(f"false_winner bonus advantage lost: {b_false < b_true}")
print()
print("VERDICT:", "✅ FIX WORKS" if b_true >= 0.30 and b_false < b_true else "❌ STILL BROKEN")
