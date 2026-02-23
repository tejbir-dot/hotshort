from flask import Blueprint, jsonify, current_app
from flask_login import login_required
from pathlib import Path
from models.clip import ClipFeedback
from models.user import db

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/learning', methods=['GET'])
@login_required
def learning_view():
    base = Path(__file__).resolve().parent.parent
    weights_file = base / 'learned_weights.json'
    weights = {}
    if weights_file.exists():
        try:
            weights = json.loads(weights_file.read_text())
        except Exception:
            weights = {}

    rows = ClipFeedback.query.order_by(ClipFeedback.id.desc()).limit(50).all()
    feedback = []
    for r in rows:
        feedback.append({
            'id': r.id,
            'clip_id': r.clip_id,
            'vote': r.vote,
            'features': r.features,
            'user_id': r.user_id,
            'session_id': r.session_id,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        })

    return jsonify({'weights': weights, 'recent_feedback': feedback})
