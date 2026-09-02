"""
viral_brain.py — HotShort Viral Prediction System
Three-layer intelligence: Rule Engine + XGBoost + Groq LLM
"""

import json
import os
import csv
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

FEATURE_COLUMNS = [
    "hook_score", "hook_emotion", "hook_type", "hook_length_words", "hook_is_question",
    "open_loop_score", "subversion", "build_segment_count", "narrative_tension", "belief_reversal",
    "payoff_score", "payoff_type", "payoff_emotion", "arc_complete", "payoff_idx_exists",
    "duration", "hook_to_payoff_ratio", "silence_ratio", "clip_position_ratio",
    "arc_score", "semantic_impact", "novelty",
]

EMOTION_MAP = {
    "fear": 4, "anger": 3, "confusion": 2,
    "curiosity": 1, "surprise": 2, "neutral": 0
}
HOOK_TYPE_MAP = {
    "rhetorical_question": 3, "shocking_claim": 2,
    "personal_authority": 2, "story": 1, "statement": 0
}
PAYOFF_TYPE_MAP = {
    "revelation": 3, "proof": 2,
    "subversion": 2, "confirmation": 1, "none": 0
}
PAYOFF_EMOTION_MAP = {
    "surprise": 4, "satisfaction": 3,
    "anger": 2, "fear": 2, "neutral": 0
}

BRAIN_DIR = Path(__file__).parent / "viral_brain" / "data"
CLIPS_CSV  = BRAIN_DIR / "clips.csv"
MODEL_PKL  = BRAIN_DIR / "model.pkl"
RULES_JSON = BRAIN_DIR / "rules.json"

RETRAIN_EVERY = 25   # retrain after every N new labeled clips
MIN_TRAIN     = 25   # minimum labeled clips before first train


# ─────────────────────────────────────────────
# RULE ENGINE
# ─────────────────────────────────────────────

class RuleEngine:

    INSTANT_REJECT = [
        ("duration",           ">",  75),
        ("hook_score",         "<",  0.15),
        ("arc_score",          "<",  0.30),
        ("payoff_idx_exists",  "==", 0),
    ]

    BASE_BOOSTS = {
        "subversion":          1.40,
        "belief_reversal":     1.25,
        "hook_emotion_fear":   1.30,
        "hook_emotion_anger":  1.30,
        "open_loop_high":      1.20,
        "duration_optimal":    1.15,
    }

    PLATFORM_RULES = {
        "tiktok":    {"max_dur": 45, "hook_window": 3,  "duration_sweet": (25, 45)},
        "youtube":   {"max_dur": 60, "hook_window": 8,  "duration_sweet": (40, 60)},
        "instagram": {"max_dur": 30, "hook_window": 2,  "duration_sweet": (15, 30)},
        "twitter":   {"max_dur": 30, "hook_window": 2,  "duration_sweet": (15, 25)},
    }

    def __init__(self, learned_boosts: dict = None):
        self.boosts = dict(self.BASE_BOOSTS)
        if learned_boosts:
            self.boosts.update(learned_boosts)

    def evaluate(self, features: dict) -> tuple[str, float]:
        """Returns (verdict, boost_multiplier)"""

        # Hard reject check
        for field, op, threshold in self.INSTANT_REJECT:
            val = features.get(field, 0)
            if op == ">"  and val > threshold:
                return "REJECT", 0.0
            if op == "<"  and val < threshold:
                return "REJECT", 0.0
            if op == "==" and val == threshold:
                return "REJECT", 0.0

        # Calculate boost
        boost = 1.0

        if features.get("subversion"):
            boost *= self.boosts["subversion"]

        if features.get("belief_reversal"):
            boost *= self.boosts["belief_reversal"]

        emotion = features.get("hook_emotion", 0)
        if emotion == EMOTION_MAP["fear"]:
            boost *= self.boosts["hook_emotion_fear"]
        elif emotion == EMOTION_MAP["anger"]:
            boost *= self.boosts["hook_emotion_anger"]

        if features.get("open_loop_score", 0) > 0.7:
            boost *= self.boosts["open_loop_high"]

        dur = features.get("duration", 0)
        if 35 <= dur <= 55:
            boost *= self.boosts["duration_optimal"]

        return "PASS", boost

    def platform_check(self, features: dict, platform: str) -> float:
        rules = self.PLATFORM_RULES.get(platform, {})
        if not rules:
            return 1.0
        dur = features.get("duration", 0)
        sweet = rules.get("duration_sweet", (0, 999))
        if sweet[0] <= dur <= sweet[1]:
            return 1.10
        elif dur > rules.get("max_dur", 999):
            return 0.70
        return 1.0


# ─────────────────────────────────────────────
# FEATURE EXTRACTOR
# ─────────────────────────────────────────────

class FeatureExtractor:

    def extract(self, clip: dict, groq_result: dict = None, video_duration: float = 0) -> dict:
        """Convert clip dict + groq analysis -> numeric feature vector"""
        gr = groq_result or {}

        hook_text  = clip.get("hook_text", "")
        hook_words = len(hook_text.split()) if hook_text else 0

        # Hook emotion — prefer Groq, fallback heuristic
        raw_emotion = gr.get("hook_emotion", "neutral")
        hook_emotion = EMOTION_MAP.get(raw_emotion, 0)

        raw_hook_type = gr.get("hook_type", "statement")
        hook_type = HOOK_TYPE_MAP.get(raw_hook_type, 0)

        raw_payoff_type = gr.get("payoff_type", "none")
        payoff_type = PAYOFF_TYPE_MAP.get(raw_payoff_type, 0)

        raw_payoff_emotion = gr.get("payoff_emotion", "neutral")
        payoff_emotion = PAYOFF_EMOTION_MAP.get(raw_payoff_emotion, 0)

        duration = clip.get("duration", clip.get("end", 0) - clip.get("start", 0))

        hook_ratio = 0.0
        if duration > 0:
            hook_dur = min(hook_words * 0.4, duration)
            hook_ratio = hook_dur / duration

        position_ratio = 0.0
        if video_duration > 0:
            position_ratio = clip.get("start", 0) / video_duration

        return {
            # Hook
            "hook_score":           float(clip.get("hook_score", clip.get("HOOK_SCORE", 0))),
            "hook_emotion":         hook_emotion,
            "hook_type":            hook_type,
            "hook_length_words":    hook_words,
            "hook_is_question":     int("?" in hook_text),
            # Story
            "open_loop_score":      float(clip.get("open_loop_score", clip.get("OPEN_LOOP_SCORE", 0))),
            "subversion":           int(bool(gr.get("subversion", False))),
            "build_segment_count":  int(clip.get("build_segment_count", 5)),
            "narrative_tension":    float(clip.get("narrative_tension", 0.5)),
            "belief_reversal":      int(bool(clip.get("belief_reversal", False))),
            # Payoff
            "payoff_score":         float(clip.get("payoff_score", clip.get("PAYOFF_SCORE", 0))),
            "payoff_type":          payoff_type,
            "payoff_emotion":       payoff_emotion,
            "arc_complete":         int(bool(clip.get("arc_complete", clip.get("arc_score", 0) > 0))),
            "payoff_idx_exists":    int(
                clip.get("payoff_idx") is not None or 
                clip.get("payoff_score", 0) > 0 or
                clip.get("PAYOFF_SCORE", 0) > 0
            ),
            # Timing
            "duration":             float(duration),
            "hook_to_payoff_ratio": hook_ratio,
            "silence_ratio":        float(clip.get("silence_ratio", 0.05)),
            "clip_position_ratio":  position_ratio,
            # Quality
            "arc_score":            float(clip.get("arc_score", 0)),
            "semantic_impact":      float(clip.get("semantic_impact", clip.get("impact", 0.5))),
            "novelty":              float(clip.get("novelty", 0.5)),
        }


# ─────────────────────────────────────────────
# GROQ ANALYZER
# ─────────────────────────────────────────────

class GroqAnalyzer:

    PROMPT = """Analyze this video clip for viral potential on social media.

HOOK: {hook}
BUILD: {build}
PAYOFF: {payoff}
PLATFORM: {platform}

Return ONLY valid JSON, no other text:
{{
  "hook_emotion": "fear|anger|confusion|curiosity|surprise|neutral",
  "hook_type": "rhetorical_question|shocking_claim|personal_authority|story|statement",
  "subversion": true or false,
  "subversion_explanation": "one sentence",
  "payoff_type": "revelation|proof|subversion|confirmation",
  "payoff_emotion": "satisfaction|anger|fear|surprise|neutral",
  "scroll_stop_reason": "why viewer stops scrolling - one sentence",
  "viral_confidence": 0.0 to 1.0,
  "weakness": "main weakness - one sentence",
  "platform_fit": 0.0 to 1.0
}}"""

    def __init__(self, groq_client=None):
        self.client = groq_client

    def analyze(self, clip: dict, platform: str = "tiktok") -> Optional[dict]:
        if not self.client:
            return None
        try:
            prompt = self.PROMPT.format(
                hook     = clip.get("hook_text", "")[:300],
                build    = clip.get("build_text", "")[:400],
                payoff   = clip.get("payoff_text", "")[:200],
                platform = platform,
            )
            response = self.client.chat.completions.create(
                model    = "llama-3.3-70b-versatile",
                messages = [{"role": "user", "content": prompt}],
                max_tokens = 400,
                temperature = 0.1,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as e:
            log.warning(f"[BRAIN_GROQ_FAIL] {e}")
            return None


# ─────────────────────────────────────────────
# MAIN VIRAL BRAIN
# ─────────────────────────────────────────────

class ViralBrain:

    def __init__(self, groq_client=None, platform: str = "tiktok"):
        self.platform  = platform
        self.extractor = FeatureExtractor()
        self.groq      = GroqAnalyzer(groq_client)
        self.rules     = RuleEngine()
        self.model     = None
        self._labeled_count_at_last_train = 0

        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        self._init_csv()
        self._load_model()
        self._load_learned_rules()

    # ── CSV / Storage ──────────────────────────

    def _init_csv(self):
        if not CLIPS_CSV.exists():
            with open(CLIPS_CSV, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self._csv_columns())
                writer.writeheader()

    def _csv_columns(self):
        return (
            ["clip_id", "timestamp", "platform", "result", "views",
             "groq_viral_confidence", "groq_scroll_stop", "groq_weakness",
             "hook_text_preview", "payoff_text_preview"]
            + FEATURE_COLUMNS
        )

    def _read_csv(self) -> list[dict]:
        if not CLIPS_CSV.exists():
            return []
        with open(CLIPS_CSV, "r") as f:
            return list(csv.DictReader(f))

    def _write_row(self, row: dict):
        with open(CLIPS_CSV, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_columns())
            writer.writerow(row)

    def _update_csv(self, clip_id: str, updates: dict):
        rows = self._read_csv()
        found = False
        for row in rows:
            if row["clip_id"] == clip_id:
                row.update(updates)
                found = True
                break
        if not found:
            log.warning(f"[BRAIN] clip_id {clip_id} not found for update")
            return
        with open(CLIPS_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._csv_columns())
            writer.writeheader()
            writer.writerows(rows)

    # ── Model Save/Load ────────────────────────

    def _load_model(self):
        if MODEL_PKL.exists():
            try:
                import joblib
                self.model = joblib.load(MODEL_PKL)
                log.info(f"[BRAIN_LOAD] XGBoost model loaded from {MODEL_PKL}")
            except Exception as e:
                log.warning(f"[BRAIN_LOAD] Model load failed: {e}")
                self.model = None

    def _save_model(self):
        try:
            import joblib
            joblib.dump(self.model, MODEL_PKL)
            log.info(f"[BRAIN_SAVE] Model saved -> {MODEL_PKL}")
        except Exception as e:
            log.warning(f"[BRAIN_SAVE] Failed: {e}")

    def _load_learned_rules(self):
        if RULES_JSON.exists():
            try:
                with open(RULES_JSON) as f:
                    learned = json.load(f)
                self.rules = RuleEngine(learned.get("boosts"))
                log.info("[BRAIN_RULES] Learned rule boosts loaded")
            except Exception:
                pass

    def _save_learned_rules(self, boosts: dict):
        with open(RULES_JSON, "w") as f:
            json.dump({"boosts": boosts, "updated": str(datetime.now())}, f, indent=2)

    # ── Core API ───────────────────────────────

    def add_clip(self, clip_id: str, clip: dict, video_duration: float = 0) -> dict:
        """
        Call this after arc_assembler / before Surgeon.
        Saves clip features for later training.
        Returns groq_result (may be None if Groq unavailable).
        """
        groq_result = self.groq.analyze(clip, self.platform)
        features    = self.extractor.extract(clip, groq_result, video_duration)

        row = {
            "clip_id":               clip_id,
            "timestamp":             str(datetime.now()),
            "platform":              self.platform,
            "result":                "pending",
            "views":                 "",
            "groq_viral_confidence": groq_result.get("viral_confidence", "") if groq_result else "",
            "groq_scroll_stop":      groq_result.get("scroll_stop_reason", "") if groq_result else "",
            "groq_weakness":         groq_result.get("weakness", "") if groq_result else "",
            "hook_text_preview":     clip.get("hook_text", "")[:80],
            "payoff_text_preview":   clip.get("payoff_text", "")[:80],
            **features,
        }
        self._write_row(row)
        log.info(f"[BRAIN_SAVE] Clip {clip_id} saved — features={len(features)}")
        return groq_result or {}

    def update_result(self, clip_id: str, result: str, views: int = 0):
        """
        Call this manually after you see clip performance.
        result = 'viral' | 'flop' | 'mid'
        """
        self._update_csv(clip_id, {"result": result, "views": views})
        log.info(f"[BRAIN_UPDATE] {clip_id} -> result={result} views={views}")

        # Auto retrain check
        labeled = [r for r in self._read_csv() if r["result"] in ("viral", "flop", "mid")]
        n = len(labeled)
        if n >= MIN_TRAIN and (n - self._labeled_count_at_last_train) >= RETRAIN_EVERY:
            log.info(f"[BRAIN_TRAIN] Triggering retrain on {n} labeled clips...")
            self.train()

    def predict(self, clip: dict, video_duration: float = 0) -> dict:
        """
        Main prediction method. Call before final ranking.
        Returns full prediction dict with score + explanation.
        """
        groq_result = self.groq.analyze(clip, self.platform)
        features    = self.extractor.extract(clip, groq_result, video_duration)

        # Layer 1 — Rules
        rule_verdict, rule_boost = self.rules.evaluate(features)
        platform_boost = self.rules.platform_check(features, self.platform)

        if rule_verdict == "REJECT":
            log.info(
                f"[BRAIN_REJECT_REASON] cid={clip.get('cid', clip.get('id','?'))} "
                f"duration={features.get('duration',0):.1f} "
                f"hook={features.get('hook_score',0):.2f} "
                f"arc={features.get('arc_score',0):.2f} "
                f"payoff_exists={features.get('payoff_idx_exists',0)}"
            )
            return {
                "viral_prob":   0.0,
                "verdict":      "REJECT",
                "rule_boost":   0.0,
                "ml_score":     0.0,
                "groq_score":   0.0,
                "explanation":  self._explain(features, groq_result),
            }

        # Layer 2 — ML Model
        ml_score = self._ml_predict(features)

        # Layer 3 — Groq
        groq_score = float(groq_result.get("viral_confidence", 0.5)) if groq_result else 0.5

        # Combine
        final = (ml_score * 0.50) + (groq_score * 0.35) + (min(rule_boost, 2.0) * 0.075)
        final *= platform_boost
        final = min(final, 1.0)

        verdict = "VIRAL" if final > 0.60 else ("MID" if final > 0.40 else "FLOP")

        explanation = self._explain(features, groq_result)

        log.info(
            f"[BRAIN_PREDICT] cid={clip.get('id','?')} "
            f"viral_prob={final:.2f} ml={ml_score:.2f} "
            f"groq={groq_score:.2f} rule_boost={rule_boost:.2f} "
            f"verdict={verdict}"
        )

        return {
            "viral_prob":  round(final, 3),
            "verdict":     verdict,
            "rule_boost":  round(rule_boost, 2),
            "ml_score":    round(ml_score, 3),
            "groq_score":  round(groq_score, 3),
            "groq_result": groq_result,
            "explanation": explanation,
        }

    def _ml_predict(self, features: dict) -> float:
        """XGBoost prediction — returns 0.5 if model not trained yet"""
        if self.model is None:
            return 0.5
        try:
            import numpy as np
            X = np.array([[features.get(f, 0) for f in FEATURE_COLUMNS]])
            prob = self.model.predict_proba(X)[0][1]
            return float(prob)
        except Exception as e:
            log.warning(f"[BRAIN_ML] predict failed: {e}")
            return 0.5

    def train(self):
        """Train/retrain XGBoost on all labeled clips"""
        try:
            import numpy as np
            from xgboost import XGBClassifier

            rows = self._read_csv()
            labeled = [r for r in rows if r["result"] in ("viral", "flop", "mid")]

            if len(labeled) < MIN_TRAIN:
                log.info(f"[BRAIN_TRAIN] Not enough labeled clips ({len(labeled)}/{MIN_TRAIN})")
                return

            label_map = {"viral": 1, "mid": 0, "flop": 0}
            X, y = [], []
            for row in labeled:
                try:
                    vec = [float(row.get(f, 0) or 0) for f in FEATURE_COLUMNS]
                    X.append(vec)
                    y.append(label_map[row["result"]])
                except Exception:
                    continue

            X = np.array(X)
            y = np.array(y)

            model = XGBClassifier(
                n_estimators      = 200,
                max_depth         = 6,
                learning_rate     = 0.05,
                subsample         = 0.8,
                colsample_bytree  = 0.8,
                eval_metric       = "auc",
                random_state      = 42,
                verbosity         = 0,
            )
            model.fit(X, y)
            self.model = model
            self._save_model()
            self._labeled_count_at_last_train = len(labeled)

            # Learn rule boosts from feature importances
            learned_boosts = self._learn_boosts(model, X, y)
            self._save_learned_rules(learned_boosts)

            # Report
            top_idx  = model.feature_importances_.argmax()
            top_feat = FEATURE_COLUMNS[top_idx]
            acc      = self._rough_accuracy(model, X, y)
            log.info(
                f"[BRAIN_TRAIN] clips={len(labeled)} "
                f"accuracy≈{acc:.0%} top_feature={top_feat}"
            )

        except ImportError:
            log.error("[BRAIN_TRAIN] xgboost not installed: pip install xgboost joblib")
        except Exception as e:
            log.error(f"[BRAIN_TRAIN] Failed: {e}")

    def _learn_boosts(self, model, X, y) -> dict:
        """Update rule boosts from feature importances"""
        importances = dict(zip(FEATURE_COLUMNS, model.feature_importances_))
        learned = {}
        if importances.get("subversion", 0) > 0.10:
            learned["subversion"] = 1.40 + importances["subversion"]
        if importances.get("belief_reversal", 0) > 0.08:
            learned["belief_reversal"] = 1.25 + importances["belief_reversal"] * 0.5
        return learned

    def _rough_accuracy(self, model, X, y) -> float:
        preds = model.predict(X)
        return float((preds == y).mean())

    # ── Explainability ─────────────────────────

    def _explain(self, features: dict, groq_result: dict = None) -> dict:
        factors = []

        if features.get("subversion"):
            factors.append(("subversion", "+23% viral chance"))
        if features.get("hook_emotion") == EMOTION_MAP["fear"]:
            factors.append(("fear_hook", "+18% — fear drives sharing"))
        if features.get("hook_emotion") == EMOTION_MAP["anger"]:
            factors.append(("anger_hook", "+18% — anger drives sharing"))
        if features.get("open_loop_score", 0) > 0.7:
            factors.append(("open_loop", f"+15% — loop={features['open_loop_score']:.2f}"))
        if features.get("belief_reversal"):
            factors.append(("belief_reversal", "+20% — unexpected twist"))
        if not features.get("arc_complete"):
            factors.append(("no_arc", "-20% — incomplete story"))
        if features.get("duration", 0) > 65:
            factors.append(("too_long", f"-15% — {features['duration']:.0f}s is too long"))
        if features.get("payoff_score", 0) < 0.4:
            factors.append(("weak_payoff", "-18% — payoff too weak"))

        if groq_result:
            factors.append(("groq_reason", groq_result.get("scroll_stop_reason", "")))
            if groq_result.get("weakness"):
                factors.append(("weakness", groq_result["weakness"]))

        return {"factors": factors}

    def explain(self, clip_id: str):
        """Print explanation for a saved clip"""
        rows = self._read_csv()
        row  = next((r for r in rows if r["clip_id"] == clip_id), None)
        if not row:
            print(f"[BRAIN_EXPLAIN] clip_id {clip_id} not found")
            return
        features = {f: float(row.get(f, 0) or 0) for f in FEATURE_COLUMNS}
        expl = self._explain(features)
        print(f"\n[BRAIN_EXPLAIN] {clip_id}")
        print(f"  Result: {row.get('result', 'pending')} | Views: {row.get('views', '?')}")
        print(f"  Hook: {row.get('hook_text_preview', '')}")
        print(f"  TOP FACTORS:")
        for name, reason in expl["factors"]:
            print(f"    {name}: {reason}")

    def stats(self):
        """Print brain stats"""
        rows    = self._read_csv()
        labeled = [r for r in rows if r["result"] in ("viral", "flop", "mid")]
        viral   = [r for r in labeled if r["result"] == "viral"]
        print(f"\n[BRAIN_STATS]")
        print(f"  Total clips saved:  {len(rows)}")
        print(f"  Labeled:            {len(labeled)}")
        print(f"  Viral:              {len(viral)}")
        print(f"  Model trained:      {self.model is not None}")
        print(f"  Next retrain at:    {self._labeled_count_at_last_train + RETRAIN_EVERY} labeled clips")
        if labeled:
            viral_rate = len(viral) / len(labeled)
            print(f"  Viral rate:         {viral_rate:.0%}")


# ─────────────────────────────────────────────
# ORCHESTRATOR INTEGRATION HELPERS
# ─────────────────────────────────────────────

def integrate_with_pipeline(brain: ViralBrain, candidates: list, video_duration: float = 0) -> list:
    """
    Drop-in function for orchestrator.py
    Call BEFORE final ranking, AFTER arc_assembler.

    Usage:
        brain = ViralBrain(groq_client=groq_client)
        candidates = integrate_with_pipeline(brain, candidates, video_duration)
    """
    for c in candidates:
        clip_id = (
            c.get("id") or 
            c.get("candidate_id") or 
            c.get("cid") or 
            c.get("clip_id") or 
            "unknown"
        )
        prediction = brain.predict(c, video_duration)

        # Store prediction on candidate
        c["brain_viral_prob"] = prediction["viral_prob"]
        c["brain_verdict"]    = prediction["verdict"]
        c["brain_boost"]      = prediction["rule_boost"]

        # Boost arc_score
        if prediction["verdict"] == "VIRAL":
            c["arc_score"] = c.get("arc_score", 0) * 1.20
        elif prediction["verdict"] == "FLOP":
            c["arc_score"] = c.get("arc_score", 0) * 0.75

        # Save for training
        brain.add_clip(clip_id, c, video_duration)

    return candidates


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    brain = ViralBrain()  # No groq client = rules + ML only

    # Test clip — social media ban video, best clip
    test_clip = {
        "id":               "c_0012",
        "hook_text":        "actually we know the answer to this question why because it has already been",
        "build_text":       "tried this experiment — Russia banned Telegram the largest social media platform",
        "payoff_text":      "However 95% of Russian teenagers still use Telegram every month. How? VPNs.",
        "arc_score":        0.66,
        "hook_score":       0.46,
        "open_loop_score":  0.65,
        "payoff_score":     0.694,
        "duration":         40.3,
        "novelty":          0.718,
        "semantic_impact":  0.524,
        "payoff_idx":       27,
    }

    prediction = brain.predict(test_clip, video_duration=378.0)

    print(f"\n=== VIRAL BRAIN TEST ===")
    print(f"Clip:       {test_clip['id']}")
    print(f"Verdict:    {prediction['verdict']}")
    print(f"Viral Prob: {prediction['viral_prob']:.0%}")
    print(f"ML Score:   {prediction['ml_score']:.2f} (no model yet -> 0.5)")
    print(f"Groq Score: {prediction['groq_score']:.2f} (no client -> 0.5)")
    print(f"Rule Boost: {prediction['rule_boost']:.2f}")
    print(f"\nFactors:")
    for name, reason in prediction["explanation"]["factors"]:
        print(f"  + {name}: {reason}")

    brain.stats()
    print("\n✅ viral_brain.py working correctly")