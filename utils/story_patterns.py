import re


def detect_story_pattern(moment):
    hook = (moment.get("hook_segment", {}) or {}).get("text", "").lower()
    payoff = (moment.get("payoff_segment", {}) or {}).get("text", "").lower()
    text = (moment.get("text", "") or "").lower()

    combined = " ".join([hook, text, payoff]).strip()
    patterns = []

    # belief reversal
    if re.search(r"(most people think|everyone thinks|people believe)", combined) and re.search(r"(but|however|actually)", combined):
        patterns.append("belief_reversal")

    # problem -> solution
    if re.search(r"(problem|issue|challenge)", combined) and re.search(r"(solution|fix|answer)", combined):
        patterns.append("problem_solution")

    # myth -> truth
    if re.search(r"(myth|misconception)", combined) and re.search(r"(truth|reality)", combined):
        patterns.append("myth_truth")

    # mistake -> lesson
    if re.search(r"(mistake|wrong)", combined) and re.search(r"(lesson|learn)", combined):
        patterns.append("mistake_lesson")

    # analogy
    if re.search(r"(like|as if|imagine)", combined):
        patterns.append("analogy_explanation")

    return patterns
