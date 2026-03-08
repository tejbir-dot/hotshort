from viral_finder.dominance_selector import SelectorConfig, select_dominant_arcs
from viral_finder.global_fields import build_cognition_cache


def test_dominant_cluster_lock_keeps_arc():
    transcript = []
    t = 0.0
    # Dominant arc region
    for txt in [
        "you think this is easy?",
        "it keeps building and pressure rises",
        "but conflict appears here and spikes",
        "this is the peak moment!",
        "so this is why it resolves.",
    ]:
        transcript.append({"start": t, "end": t + 1.2, "text": txt})
        t += 1.2
    # Secondary unrelated region
    for txt in [
        "another topic starts here",
        "this one has minor signal",
        "short closure here.",
    ]:
        transcript.append({"start": t, "end": t + 1.2, "text": txt})
        t += 1.2

    aud = [{"time": (i + 0.5) * 1.2, "energy": (0.9 if i in (2, 3) else 0.35)} for i in range(len(transcript))]
    cache = build_cognition_cache(transcript, aud=aud, vis=[])
    out = select_dominant_arcs(cache, top_k=3, cfg=SelectorConfig(top_k=3), selection_mode="godmode")
    assert out, "expected godmode candidates"
    top = out[0]
    assert top.get("selection_mode") == "godmode"
    assert top.get("cluster_id", -1) >= 0
    assert isinstance(top.get("arc_complete"), bool)

