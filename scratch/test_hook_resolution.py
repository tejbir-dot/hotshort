from utils.narrative_intelligence import compute_hook_resolution_bonus

hook = "Most people think that success is about working harder"
seg_true  = "What is the one thing and only the one thing that actually matters?"
seg_false = "meaning stop it and focus on what matters"

r_true  = compute_hook_resolution_bonus(seg_true,  hook, debug=True)
r_false = compute_hook_resolution_bonus(seg_false, hook, debug=True)

print()
print(f"TRUE PAYOFF  hook_res_bonus = {r_true:.2f}  -> gate passes: {r_true >= 0.30}")
print(f"FALSE WINNER hook_res_bonus = {r_false:.2f}  -> gate passes: {r_false >= 0.30}")
print()
print("The true payoff now ENTERS the competition.")
print("The competition can now choose the right winner.")
