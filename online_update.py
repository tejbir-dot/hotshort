"""Nightly online adjustment of decision weights from ClipFeedback.

Usage:
  .\.venv\Scripts\python.exe online_update.py

This reads new rows from `ClipFeedback`, updates a local JSON of weights
(`learned_weights.json`) and advances a `feedback_cursor.txt` pointer.
"""
import json
import os
from pathlib import Path

from models.clip import ClipFeedback
from models.user import db
from app import app

BASE = Path(__file__).parent
WEIGHTS_PATH = BASE / "learned_weights.json"
CURSOR_PATH = BASE / "feedback_cursor.txt"

DEFAULT_WEIGHTS = {
    "curiosity": 0.12,
    "authority": 0.10,
    "emotion": 0.10,
    "sarcasm": 0.08,
    "clarity": 0.10
}


def load_weights():
    if WEIGHTS_PATH.exists():
        try:
            return json.loads(WEIGHTS_PATH.read_text())
        except Exception:
            return DEFAULT_WEIGHTS.copy()
    return DEFAULT_WEIGHTS.copy()


def save_weights(w):
    WEIGHTS_PATH.write_text(json.dumps(w, indent=2))


def get_last_id():
    if CURSOR_PATH.exists():
        try:
            return int(CURSOR_PATH.read_text().strip() or 0)
        except Exception:
            return 0
    return 0


def set_last_id(i):
    CURSOR_PATH.write_text(str(int(i)))


def clamp_weights(w):
    for k in list(w.keys()):
        v = float(w[k])
        w[k] = min(0.5, max(0.05, v))


def main():
    with app.app_context():
        last = get_last_id()
        rows = ClipFeedback.query.filter(ClipFeedback.id > last).order_by(ClipFeedback.id.asc()).all()
        if not rows:
            print("No new feedback rows to process.")
            return

        weights = load_weights()
        for fb in rows:
            sign = 1 if fb.vote > 0 else -1
            features = fb.features or {}
            # confidence-weighted learning rate (prevent low-confidence noise)
            confidence = float(features.get("confidence", features.get("score", 0.5)) or 0.5)
            for k, v in features.items():
                try:
                    val = float(v)
                except Exception:
                    continue
                learning_rate = 0.008 * confidence
                weights[k] = weights.get(k, 0.1) + sign * learning_rate * val
            last = max(last, fb.id)

        clamp_weights(weights)
        save_weights(weights)
        set_last_id(last)
        print(f"Processed {len(rows)} feedback rows. New weights saved to {WEIGHTS_PATH}")


if __name__ == "__main__":
    main()
