import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ['HS_TRACE_MODE'] = 'true'

import viral_finder.orchestrator as orch
from utils.payoff_engine import PayoffEngine

orig_resolve = PayoffEngine.resolve

candidate_traces = {}

def hooked_resolve(self, st, transcript, hook_seg, candidate_window):
    print("\n" + "=" * 49)
    print("HOOK")
    
    promise = st.ident.get("hook", "N/A") if st and hasattr(st, "ident") else "N/A"
    debt = "N/A"
    promise_type = "N/A"
    
    if st and hasattr(st, "ident") and "birth_reason" in st.ident:
        br = st.ident["birth_reason"]
        debt = br.get("debt", "N/A")
        promise_type = br.get("promise_type", "N/A")
        
    w_start = candidate_window[0]['start'] if candidate_window else "N/A"
    w_end = candidate_window[-1]['end'] if candidate_window else "N/A"
    num_segs = len(candidate_window) if candidate_window else 0
    
    print(f"Promise:\n{promise}")
    print(f"\nDebt:\n{debt}")
    print(f"\nPromise Type:\n{promise_type}")
    print(f"\nWindow Start:\n{w_start}")
    print(f"\nWindow End:\n{w_end}")
    print(f"\nSegments Given To Engine:\n{num_segs}")
    print(f"\nExpected Payoff Region:\n[Will manually evaluate]")
    
    print("=================================================")
    
    result = orig_resolve(self, st, transcript, hook_seg, candidate_window)
    
    state = result.get("state", "SEARCH_FAILED") if result else "SEARCH_FAILED"
    print(f"Then immediately after")
    print(f"Payoff Engine")
    print(f"received")
    print(f"{num_segs} segments")
    print(f"returned")
    print(f"{state}")
    
    # Store the trace if this is the chosen candidate to analyze (e.g. 0.0s or any)
    if st:
        candidate_traces[st.id] = {
            "promise": promise,
            "debt": debt,
            "promise_type": promise_type,
            "w_start": w_start,
            "w_end": w_end,
            "segments": [s["text"] for s in candidate_window],
            "state": state
        }
    
    return result

PayoffEngine.resolve = hooked_resolve

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "scratch/temp_target.mp4"
    if not os.path.exists(target):
        print(f"Target not found: {target}")
        sys.exit(1)
        
    print(f"Running input contract trace on {target}...")
    orch.orchestrate(target, top_k=8, allow_fallback=False)
    
    print("\n\n--- SAVING FULL TRACES TO JSON ---")
    with open("scratch/input_contract_traces.json", "w") as f:
        json.dump(candidate_traces, f, indent=2)
    print("Saved to scratch/input_contract_traces.json")
