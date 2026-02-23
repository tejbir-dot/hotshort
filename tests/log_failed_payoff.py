import os, json
from viral_finder.idea_graph import analyze_curiosity_and_detect_punches, detect_conclusion_marker

TRANS_DIR = 'cache'
OUT_PATH = 'tests/payoff_failures.jsonl'
FILES = [f for f in os.listdir(TRANS_DIR) if f.endswith('.json')]

# utilities
def compress_curve(curiosity, max_points=20):
    if curiosity is None:
        return []
    N = len(curiosity)
    if N <= max_points:
        return [round(float(x),3) for x in curiosity]
    step = max(1, N // max_points)
    return [round(float(curiosity[i]),3) for i in range(0, N, step)][:max_points]


def sem_density_deltas(feats):
    s = [float(f.get('sem_density',0.0)) for f in feats]
    return [round(s[i+1]-s[i],3) for i in range(len(s)-1)]


if __name__ == '__main__':
    # ensure output file
    with open(OUT_PATH, 'w', encoding='utf-8') as out_fh:
        count = 0
        for fn in FILES:
            path = os.path.join(TRANS_DIR, fn)
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    transcript = json.load(fh)
            except Exception as e:
                print('skip', fn, e)
                continue

            feats, curiosity, candidates = analyze_curiosity_and_detect_punches(transcript)
            # choose top candidate if any
            if not candidates:
                # log entire transcript as no-candidate case
                compressed = compress_curve(curiosity)
                sem_deltas = sem_density_deltas(feats)
                last_two = ' '.join((transcript[-2]["text"].strip() if len(transcript)>=2 else '' , transcript[-1]["text"].strip()))
                closure_flags = [detect_conclusion_marker(seg.get('text','')) for seg in transcript[-6:]]
                rec = {
                    'file': fn,
                    'reason': 'no_candidates',
                    'curiosity_compressed': compressed,
                    'sem_density_deltas_sample': sem_deltas[-20:],
                    'last_two_sentences': last_two[:500],
                    'closure_flags_last_segments': closure_flags
                }
                out_fh.write(json.dumps(rec) + '\n')
                count += 1
                continue

            top = sorted(candidates, key=lambda x: x[2].get('curiosity_peak', 0.0) if isinstance(x,(list,tuple)) else x.get('curiosity_peak',0.0), reverse=True)[0]
            meta = top[2] if isinstance(top,(list,tuple)) else top
            payoff_conf = meta.get('payoff_confidence', 0.0)
            decision = 'yes' if payoff_conf is not None and payoff_conf >= 0.6 else 'no'

            if decision == 'no':
                s_idx = int(meta.get('start_idx',0))
                e_idx = int(meta.get('end_idx', len(feats)-1))
                # compress curiosity for the node window
                node_cur = curiosity[s_idx:e_idx+1] if curiosity is not None else []
                compressed = compress_curve(node_cur)
                sem_deltas = sem_density_deltas(feats[s_idx:e_idx+1])
                # last two sentences inside the node
                last_two_segs = transcript[s_idx:e_idx+1][-2:]
                last_two = ' '.join(seg.get('text','').strip() for seg in last_two_segs)
                # detect closure markers in last 6 segments
                closure_flags = [bool(detect_conclusion_marker(seg.get('text',''))) for seg in transcript[max(0,e_idx-5):e_idx+1]]
                rec = {
                    'file': fn,
                    'candidate_range': [s_idx,e_idx],
                    'curiosity_compressed': compressed,
                    'sem_density_deltas_sample': sem_deltas[-20:],
                    'last_two_sentences': last_two[:500],
                    'closure_flags_last_segments': closure_flags,
                    'payoff_confidence': payoff_conf
                }
                out_fh.write(json.dumps(rec) + '\n')
                count += 1
        print('Wrote', count, 'failure logs to', OUT_PATH)
