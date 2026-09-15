import sys
import logging
import time
sys.path.insert(0, ".")

# Setup simple console logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from utils.narrative_intelligence import StoryThread, compute_hook_resolution_bonus

print("=" * 60)
print("HOTSHORT STORY MEMORY STRESS TEST")
print("=" * 60)

# Simulate the Hook Hunter's inner logic for each test
def simulate_hook_hunter(transcript_segs, description=""):
    print(f"\n[TEST] {description}")
    print("-" * 40)
    
    active_story_threads = []
    candidates = []
    arc_horizon_s = 120.0
    continuity_threshold = 0.30

    # Simulate basic hook detector
    def is_hook(seg):
        text = seg["text"].lower()
        if "most people" in text or "what's the one thing" in text or "why?" in text or "hook" in text or "story" in text:
            return True
        return False

    def is_payoff(seg):
        text = seg["text"].lower()
        if "5% that creates 95%" in text or "payoff" in text:
            return True
        return False

    for idx, seg in enumerate(transcript_segs):
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_text = seg["text"]
        
        print(f"\n  Time {seg_start:03.0f}s | Seg {idx}: {seg_text}")

        # 1. Prune expired
        active_next = []
        for t in active_story_threads:
            if t.is_expired(seg_start, arc_horizon_s):
                print(f"  [STORY_THREAD_EXPIRED] {t}")
            else:
                active_next.append(t)
        active_story_threads = active_next

        # 2. Check Payoff (Simulation of resolution)
        # Note: In real HotShort, ArcAssembler does this. For this test, we simulate
        # the system recognizing a payoff and resolving the thread.
        for t in active_story_threads:
            if is_payoff(seg):
                t.resolve(seg_start)
                print(f"  [STORY_THREAD_RESOLVED] {t} at {seg_start}s")

        # 3. Check Hook
        if is_hook(seg):
            print(f"  > Strong Hook Signal Detected.")
            continuing = False
            for t in active_story_threads:
                score = t.does_segment_continue(seg_text, compute_hook_resolution_bonus, continuity_threshold)
                if score >= continuity_threshold:
                    continuing = True
                    print(f"  [STORY_THREAD_CONTINUED] seg={idx} continues {t}")
                    print(f"  [HOOK_SUPPRESSED_BY_MEMORY]\n    segment: {seg_text}\n    score: {score:.2f}\n    thread_start: {t.start_s}")
                    break
            
            if not continuing:
                print(f"  > Spawning new candidate.")
                candidates.append(seg)
                new_t = StoryThread(seg_text, seg_start, idx)
                active_story_threads.append(new_t)
                print(f"  [STORY_THREAD_CREATED] {new_t}")
                print(f"  [NEW_HOOK_ALLOWED] seg={idx} text='{seg_text}'")

    print("\n  RESULTS:")
    print(f"  Candidates generated: {len(candidates)}")
    for i, c in enumerate(candidates):
        print(f"    C_{i}: {c['text']}")

# -------------------------------------------------------------------------
test1 = [
    {"start": 10.0, "end": 15.0, "text": "Most people think productivity is about working harder."},
    {"start": 15.0, "end": 20.0, "text": "The truth is that most people are just busy."},
    {"start": 20.0, "end": 25.0, "text": "They spend all day reacting."},
    {"start": 25.0, "end": 30.0, "text": "They answer messages."},
    {"start": 30.0, "end": 35.0, "text": "They attend meetings."},
    {"start": 35.0, "end": 40.0, "text": "And the last thing you should ask yourself is:"},
    {"start": 40.0, "end": 45.0, "text": "What's the one thing that actually matters?"},
    {"start": 45.0, "end": 50.0, "text": "Because that's the 5% that creates 95% of results."}
]

test2 = [
    {"start": 10.0, "end": 15.0, "text": "Most people think productivity is about working harder."},
    {"start": 40.0, "end": 45.0, "text": "What's the one thing that actually matters?"},
    {"start": 45.0, "end": 50.0, "text": "That's the 5% that creates 95% of results."},
    {"start": 55.0, "end": 60.0, "text": "Now let's talk about fitness."},
    {"start": 60.0, "end": 65.0, "text": "Most people train too hard."},
    {"start": 65.0, "end": 70.0, "text": "Recovery is the real secret."}
]

test3 = [
    {"start": 10.0, "end": 15.0, "text": "Most people think discipline is difficult."},
    {"start": 15.0, "end": 20.0, "text": "The real issue is environment."},
    {"start": 20.0, "end": 25.0, "text": "When your environment changes, behavior changes."},
    {"start": 25.0, "end": 30.0, "text": "Why?"},
    {"start": 30.0, "end": 35.0, "text": "Because behavior follows friction."}
]

test4 = [
    {"start": 10.0, "end": 15.0, "text": "Most people think this is a hook."},
    {"start": 35.0, "end": 40.0, "text": "20 seconds build"},
    {"start": 55.0, "end": 60.0, "text": "20 seconds build"},
    {"start": 75.0, "end": 80.0, "text": "20 seconds build"},
    {"start": 95.0, "end": 100.0, "text": "20 seconds build"},
    {"start": 115.0, "end": 120.0, "text": "What's the one thing that actually matters?"},
    {"start": 120.0, "end": 125.0, "text": "Because that's the 5% that creates 95% of results."}
]

test5 = [
    {"start": 10.0, "end": 15.0, "text": "Story A starts now."},
    {"start": 15.0, "end": 20.0, "text": "Here is the payoff for A."},
    {"start": 30.0, "end": 35.0, "text": "Story B starts now."},
]

simulate_hook_hunter(test1, "TEST 1: FRAGMENTATION TEST")
simulate_hook_hunter(test2, "TEST 2: TRUE NEW STORY TEST")
simulate_hook_hunter(test3, "TEST 3: FALSE HOOK TEST")
simulate_hook_hunter(test4, "TEST 4: LONG MEMORY TEST")
simulate_hook_hunter(test5, "TEST 5: RESOLUTION RELEASE TEST")

