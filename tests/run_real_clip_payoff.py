import json
from viral_finder.idea_graph import analyze_curiosity_and_detect_punches, debug_print_lens

# load transcript
with open('cache_transcript_s5r4wdOWLjk.json', 'r', encoding='utf-8') as fh:
    transcript = json.load(fh)

feats, curiosity, candidates = analyze_curiosity_and_detect_punches(transcript)

print('Total segments:', len(feats))

# debug lens
print('\n[DEBUG LENS]')
debug_items = []
for c in candidates:
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        meta = c[2]
        debug_items.append({'text': meta.get('text', ''), 'start': meta.get('start_time', c[0]), 'end': meta.get('end_time', c[1]), 'metrics': meta})
    elif isinstance(c, dict):
        debug_items.append({'text': c.get('text',''), 'start': c.get('start',0.0), 'end': c.get('end',0.0), 'metrics': c.get('metrics',{})})
debug_print_lens(debug_items, transcript=transcript)

# pick top candidate
if not candidates:
    print('\nNo candidates found')
else:
    top = sorted(candidates, key=lambda x: x[2].get('curiosity_peak', 0.0) if isinstance(x, (list, tuple)) else x.get('curiosity',0.0), reverse=True)[0]
    meta = top[2] if isinstance(top, (list, tuple)) else top
    s_idx = int(meta.get('start_idx', 0))
    e_idx = int(meta.get('end_idx', len(feats)-1))

    # curiosity peak time (within candidate range)
    if len(curiosity) > 0:
        rel_peak = int((max(range(s_idx, e_idx+1), key=lambda i: curiosity[i])) )
        curiosity_peak_time = feats[rel_peak]['start']
    else:
        curiosity_peak_time = None

    payoff_time = meta.get('payoff_time')
    payoff_conf = meta.get('payoff_confidence')

    # last sentence text at payoff
    last_sentence = None
    if payoff_time is not None:
        for seg in transcript:
            if seg.get('start',0.0) < payoff_time <= seg.get('end', seg.get('start',0.0)):
                last_sentence = seg.get('text','').strip()
                break
        if last_sentence is None:
            # fallback: last segment in candidate
            last_seg = transcript[e_idx]
            last_sentence = last_seg.get('text','').strip()

    print('\nRESULTS:')
    print('curiosity_peak_time:', curiosity_peak_time)
    print('payoff_time:', payoff_time)
    print('payoff_confidence:', payoff_conf)
    print('last_sentence_text:', last_sentence)

    # decision question
    decision = 'no'
    if payoff_conf is not None and payoff_conf >= 0.6:
        decision = 'yes'
    print('\nQuestion: Would I stop listening here and feel satisfied? ->', decision)
    if decision == 'yes':
        print('Action: ship')
    else:
        print("Action: increase semantic threshold slightly and re-run")
