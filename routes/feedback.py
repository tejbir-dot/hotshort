from flask import Blueprint, request, jsonify, session
from flask_login import current_user, login_required
from datetime import datetime, timedelta
import uuid

from models.clip import ClipFeedback
from models.user import db, Clip

feedback_bp = Blueprint("feedback", __name__)


def _ensure_session_id():
    sid = session.get("feedback_uid")
    if not sid:
        sid = str(uuid.uuid4())
        session["feedback_uid"] = sid
    return sid


def allow_feedback(user_id, session_id, clip_id, window_hours: int = 12) -> bool:
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    q = db.session.query(ClipFeedback).filter(ClipFeedback.clip_id == clip_id)
    if user_id:
        q = q.filter(ClipFeedback.user_id == user_id)
    else:
        q = q.filter(ClipFeedback.session_id == session_id)
    recent = q.filter(ClipFeedback.created_at > cutoff).count()
    return recent == 0


@feedback_bp.route("/feedback", methods=["POST"])  # mounted at /api/feedback if registered under /api
@login_required
def clip_feedback():
    data = request.json or {}
    clip_id = data.get("clip_id")
    vote = data.get("vote")
    feedback_str = data.get("feedback")
    features = data.get("features")

    if clip_id is None or vote is None:
        return jsonify({"status": "error", "message": "clip_id and vote required"}), 400

    # Hard-validate clip ownership
    clip = Clip.query.filter_by(id=clip_id, user_id=current_user.id).first()
    if not clip:
        return jsonify({"status": "error", "message": "clip not found"}), 404

    # derive identity: prefer authenticated user
    user_id = current_user.id

    session_id = _ensure_session_id()

    # Rate-limit: one feedback per user per clip per window
    if not allow_feedback(user_id, session_id, clip_id):
        return jsonify({"status": "ignored", "message": "recent feedback exists"}), 200

    # Per-minute throttle
    minute_cutoff = datetime.utcnow() - timedelta(minutes=1)
    recent_count = ClipFeedback.query.filter(
        ClipFeedback.user_id == user_id,
        ClipFeedback.created_at > minute_cutoff
    ).count()
    if recent_count >= 10:
        return jsonify({"status": "error", "message": "rate limit exceeded"}), 429

    try:
        existing = ClipFeedback.query.filter_by(clip_id=clip_id, user_id=user_id).first()
        weight = 1.0
        plan = getattr(current_user, "subscription_plan", "") or getattr(current_user, "subscription", None)
        if str(plan).lower() in ("pro", "creator"):
            weight = 1.5
        if existing:
            existing.vote = int(vote)
            existing.features = features
            existing.created_at = datetime.utcnow()
            existing.weight = weight if hasattr(existing, "weight") else None
        else:
            fb = ClipFeedback(clip_id=clip_id, vote=int(vote), features=features, user_id=user_id, session_id=session_id)
            if hasattr(fb, "weight"):
                fb.weight = weight
            db.session.add(fb)

        db.session.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
