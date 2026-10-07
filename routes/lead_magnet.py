from flask import Blueprint, request, jsonify
from api.lead_magnet_service import LeadMagnetEngine

lead_magnet_bp = Blueprint('lead_magnet', __name__)
engine = LeadMagnetEngine()

@lead_magnet_bp.route('/api/try-free', methods=['POST'])
def try_free():
    """
    Inbound Lead Magnet Endpoint
    Expected JSON: { "youtube_url": "https://...", "email": "client@example.com" }
    """
    data = request.get_json()
    
    if not data or 'youtube_url' not in data or 'email' not in data:
        return jsonify({"error": "Missing youtube_url or email"}), 400
        
    youtube_url = data['youtube_url'].strip()
    email = data['email'].strip()
    
    # 1. Basic validation
    if "youtube.com" not in youtube_url and "youtu.be" not in youtube_url:
        return jsonify({"error": "Invalid YouTube URL"}), 400
        
    if "@" not in email or "." not in email:
        return jsonify({"error": "Invalid Email"}), 400
        
    # 2. Trigger the background free clip generation
    # This won't block the HTTP request; the user gets an immediate success response.
    res = engine.trigger_free_clip(youtube_url, email)
    
    return jsonify({
        "success": True,
        "message": "We have started generating your viral clip. It will be emailed to you within 10 minutes!",
        "status": res["status"]
    }), 200
