import json
import re

logs = open('scratch/experiment_logs_clean.txt').read()

print('--- INVESTIGATION C: Payoff Competition ---')
matches = re.findall(r'\[PAYOFF_COMPETITION\] candidate_id=(.*?)\n(.*?)\n\[ARC_END_TRACE\]', logs, re.DOTALL)
for cid, content in matches:
    print(f'\nCID: {cid}')
    # Extract segments
    segments = re.findall(r'\[INFO\] (\d+)\ntext=\"(.*?)\"\nlegacy=(.*?)\ngroq=(.*?)\nrole_weight=(.*?)\nfinal=(.*?)\n\[INFO\] ending_strength=(.*?) \((.*?)\)\n\[INFO\] payoff_resolution=(.*?) \((.*?)\)', content)
    for seg in segments:
        print(f'Seg: {seg[0]} | text: {seg[1]} | legacy: {seg[2]} | groq: {seg[3]} | weight: {seg[4]} | final: {seg[5]} | end_str: {seg[6]} | payoff_res: {seg[8]}')
