import json, os
from viral_finder.idea_graph import analyze_curiosity_and_detect_punches, debug_print_lens

TRANS_DIR = 'cache'
FILES = ['s5r4wdOWLjk.json','4z7Tv5DSRcs.json','88BbTpbWVpY.json','RJGo6K3-gHg.json']

results = []
for fn in FILES:
    path = os.path.join(TRANS_DIR, fn)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            transcript = json.load(fh)
    except Exception as e:
        print('Failed to load', path, e)
        continue

    feats, curiosity, candidates = analyze_curiosity_and_detect_punches(transcript)
    # pick top candidate by curiosity_peak
    if not candidates:
        results.append((fn, None))
        continue
    top = sorted(candidates, key=lambda x: x[2].get('curiosity_peak', 0.0) if isinstance(x,(list,tuple)) else x.get('curiosity_peak',0.0), reverse=True)[0]
    meta = top[2] if isinstance(top,(list,tuple)) else top
    s_idx = int(meta.get('start_idx',0))
    e_idx = int(meta.get('end_idx', len(feats)-1))
    # find curiosity peak index/time
    if curiosity is not None and (hasattr(curiosity, '__len__') and len(curiosity) > 0):
        peak_idx = max(range(s_idx, e_idx+1), key=lambda i: (curiosity[i] if not hasattr(curiosity[i], '__iter__') else float(curiosity[i])))
        peak_time = feats[peak_idx]['start']
    else:
        peak_time = None
    payoff_time = meta.get('payoff_time')
    payoff_conf = meta.get('payoff_confidence')
    # get last sentence text at payoff
    last_sentence = None
    if payoff_time is not None:
        for seg in transcript:
            if seg.get('start',0.0) < payoff_time <= seg.get('end', seg.get('start',0.0)):
                last_sentence = seg.get('text','').strip()
                break
    if last_sentence is None:
        # fallback to end_idx text
        last_sentence = ' '.join(seg.get('text','').strip() for seg in transcript[s_idx:e_idx+1][-1:])

    decision = 'yes' if (payoff_conf is not None and payoff_conf >= 0.6) else 'no'
    results.append((fn, {'curiosity_peak_time': peak_time, 'payoff_time': payoff_time, 'payoff_confidence': payoff_conf, 'last_sentence': last_sentence, 'decision': decision}))

# Print summary
for fn, r in results:
    print('\nFILE:', fn)
    if r is None:
        print('  No candidates')
    else:
        print('  curiosity_peak_time:', r['curiosity_peak_time'])
        print('  payoff_time:', r['payoff_time'])
        print('  payoff_confidence:', r['payoff_confidence'])
        print('  last_sentence:', r['last_sentence'][:200])
        print('  decision:', r['decision'])
