import sys
import re

with open('local_worker.py', 'r', encoding='utf-8') as f:
    text = f.read()

# We need to replace def _process_job(job: dict, cloudinary_ok: bool): up to def main():
match = re.search(r'def _process_job\(job: dict, cloudinary_ok: bool\):.*?(?=def main\(\):)', text, re.DOTALL)
if match:
    print("Found _process_job!")
else:
    print("Could not find _process_job")

