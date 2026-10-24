import subprocess
import json

clips = [
    '99cdb3e7_branded_0_246_328.mp4',
    '99cdb3e7_branded_3_102_189.mp4',
    '99cdb3e7_edited_2_246_328.mp4',
    'a3f63caa_branded_1_388_467.mp4',
    'b1d60a78_branded_0_50_118.mp4',
    'b1d60a78_branded_1_1_68.mp4',
    'b1d60a78_branded_2_32_99.mp4'
]

base = 'marketing_factory/output'
for c in clips:
    path = f"{base}/{c}"
    out = subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,duration',
        '-of', 'json', path
    ])
    d = json.loads(out)
    s = d['streams'][0]
    dur = float(s.get('duration', 0))
    print(f"{c}: {s.get('width')}x{s.get('height')} dur={dur:.1f}s")
