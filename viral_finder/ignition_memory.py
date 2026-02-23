# ignition_memory.py
# Learns over time which ignition types perform better

import json
import os
from collections import defaultdict

MEMORY_FILE = "ignition_memory.json"


def _load_memory():
    if not os.path.exists(MEMORY_FILE):
        return defaultdict(lambda: {"count": 0, "success": 0})
    with open(MEMORY_FILE, "r") as f:
        return defaultdict(lambda: {"count": 0, "success": 0}, json.load(f))


def _save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)


def log_ignition_result(punch_type: str, viral: bool):
    """
    Call this after you know whether a clip worked or not.
    viral=True means good retention / views.
    """
    mem = _load_memory()
    mem[punch_type]["count"] += 1
    if viral:
        mem[punch_type]["success"] += 1
    _save_memory(mem)


def get_punch_weights():
    """
    Returns learned weight per punch type.
    More successful punches get higher weight.
    """
    mem = _load_memory()
    weights = {}

    for punch, data in mem.items():
        if data["count"] == 0:
            weights[punch] = 1.0
        else:
            success_rate = data["success"] / data["count"]
            weights[punch] = round(1.0 + success_rate, 3)  # 1.0 → 2.0

    return weights
