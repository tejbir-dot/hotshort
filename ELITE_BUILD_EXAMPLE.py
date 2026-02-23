"""
🎬 ELITE BUILD: Example Integration with app.py

This shows HOW to integrate the new clip architecture into your existing Flask app.
Copy the relevant parts into your app.py or routes.

⚠️ IMPORTANT: This file contains EXAMPLE CODE with @app decorators.
   You must either:
   A) Copy these functions into your existing app.py (where app = Flask(__name__) is defined)
   B) Create these functions in a new Flask Blueprint and register it in app.py
   
   See STEP 4 in IMPLEMENTATION NOTES for detailed copy-paste instructions.
"""

# ==========================================
# IMPORTS (add to top of app.py)
# ==========================================
# ✅ These imports work because we import from models.user which has access to db
# ✅ When you paste these into your app.py, all imports will resolve correctly

from flask import Flask, render_template, request, send_file, jsonify
from flask_login import login_required
from utils.clip_builder import build_clips_from_analysis
from utils.clip_schema import clip_to_dict
from utils.platform_variants import generate_platform_variants
from models.user import db, Job  # ✅ REQUIRED: Job model for database queries
import json
import os
import subprocess


# ==========================================
# EXAMPLE: Results Route (Updated)
# ==========================================
# ⚠️ IMPORTANT: Understanding @app decorator
#
# This is EXAMPLE CODE meant to be COPIED into your app.py
#
# In your app.py, 'app' is defined at the top:
#   app = Flask(__name__)
#
# Once 'app' is defined, you can use @app.route() decorators below it.
#
# How to use this example:
# Option 1 (Simple): Copy-paste this function into app.py after app is defined
# Option 2 (Clean): Create a Blueprint and register it in app.py
#
# ✅ DO THIS:
#   # In your app.py at the top:
#   app = Flask(__name__)
#   
#   # Then anywhere below, paste:
#   @app.route("/results/<job_id>")
#   def results(job_id):
#       ...
#
# ✅ OR DO THIS (Blueprint approach):
#   # results_bp.py
#   from flask import Blueprint
#   results_bp = Blueprint('results', __name__)
#   
#   @results_bp.route("/results/<job_id>")
#   def results(job_id):
#       ...
#   
#   # In app.py:
#   app.register_blueprint(results_bp)
#
# For Pylance: app is defined in your main app.py as Flask(__name__)
# noinspection PyUnresolvedReference
app = None  # type: ignore  # This is a placeholder; actual app comes from your app.py

# ==========================================
def results(job_id):
    """
    NEW: Serve clips with full metadata and confidence scores.
    
    This replaces the old simple results page with an intelligent,
    explainable clip showcase.
    """
    
    # 1. Fetch raw analysis from your existing pipeline
    # (This might come from database, cache, or session)
    try:
        raw_analysis = fetch_clips_from_job(job_id)  # Your existing function
        if not raw_analysis:
            return render_template("results_new.html", clips_json="[]")
    except Exception as e:
        print(f"Error fetching analysis: {e}")
        return render_template("results_new.html", clips_json="[]")
    
    # 2. Get source video path (for variant generation)
    source_video = get_job_video_path(job_id)  # Your existing function
    
    # 3. Get full transcript (for context)
    full_transcript = get_job_transcript(job_id)  # Your existing function
    
    # 4. BUILD: Transform raw analysis into ViralClip objects
    # This is where backend intelligence → explainable data happens
    try:
        clips = build_clips_from_analysis(
            analysis_results=raw_analysis,
            source_video=source_video,
            full_transcript=full_transcript,
        )
    except Exception as e:
        print(f"Error building clips: {e}")
        clips = []
    
    # 5. SERIALIZE: Convert to JSON for frontend
    clips_json = json.dumps([clip_to_dict(c) for c in clips])
    
    # 6. RENDER: Serve new template with data
    return render_template(
        "results_new.html",
        clips_json=clips_json,
        job_id=job_id,
    )


# ==========================================
# HELPER: Fetch clips from job
# ==========================================

def fetch_clips_from_job(job_id: str) -> list:
    """
    Fetch the raw analysis for a job.
    
    YOUR JOB: Replace this with your actual data source.
    Could come from:
    - Database (query Clip model)
    - Cache (Redis)
    - File system
    - Session
    """
    
    # EXAMPLE: Query database
    try:
        job = Job.query.filter_by(id=job_id).first()
        if not job or not job.analysis_data:
            return []
        
        # Parse the analysis JSON
        analysis = json.loads(job.analysis_data)
        
        # Convert to format expected by ClipBuilder
        # ClipBuilder expects: List[Dict] with keys:
        # - start_time, end_time
        # - text, hook_score, retention_score, clarity_score, emotion_score
        
        clips = []
        for i, analysis_item in enumerate(analysis.get('moments', [])):
            clip = {
                'start_time': analysis_item.get('start', 0.0),
                'end_time': analysis_item.get('end', 15.0),
                'text': analysis_item.get('text', ''),
                'hook_score': analysis_item.get('hook_score', 0.7),
                'retention_score': analysis_item.get('retention_score', 0.7),
                'clarity_score': analysis_item.get('clarity_score', 0.75),
                'emotion_score': analysis_item.get('emotion_score', 0.70),
            }
            clips.append(clip)
        
        return clips
    
    except Exception as e:
        print(f"Error fetching job analysis: {e}")
        return []


# ==========================================
# HELPER: Get job video path
# ==========================================

def get_job_video_path(job_id: str) -> str:
    """
    Get the path to the downloaded video for this job.
    
    YOUR JOB: Replace with your actual path logic.
    """
    
    # EXAMPLE: Database
    try:
        job = Job.query.filter_by(id=job_id).first()
        if job and job.video_path:
            return job.video_path
    except:
        pass
    
    # EXAMPLE: File system convention
    video_path = f"downloads/video_{job_id}.mp4"
    if os.path.exists(video_path):
        return video_path
    
    return None


# ==========================================
# HELPER: Get job transcript
# ==========================================

def get_job_transcript(job_id: str) -> str:
    """
    Get the full transcript for this job.
    
    YOUR JOB: Replace with your actual transcript source.
    """
    
    # EXAMPLE: Database
    try:
        job = Job.query.filter_by(id=job_id).first()
        if job and job.transcript:
            return job.transcript
    except:
        pass
    
    # EXAMPLE: File system
    transcript_path = f"data/transcripts/{job_id}.txt"
    if os.path.exists(transcript_path):
        with open(transcript_path, 'r') as f:
            return f.read()
    
    return ""


# ==========================================
# EXAMPLE: Download API Endpoint
# ==========================================

@app.route("/api/clips/download/<clip_id>/<platform>")
@login_required
def download_clip_variant(clip_id: str, platform: str):
    """
    Download a platform-specific clip variant.
    
    Example: /api/clips/download/clip_1/youtube_shorts
    
    Returns: File download
    """
    
    # 1. Security: Verify user owns this clip
    # (Add your authorization logic)
    
    # 2. Construct file path
    # YOU need to know where your clips are stored
    file_path = f"static/outputs/{clip_id}_{platform}.mp4"
    
    # 3. Verify file exists
    if not os.path.exists(file_path):
        return jsonify({"error": "Clip not found"}), 404
    
    # 4. Serve file
    return send_file(
        file_path,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=f"{clip_id}_{platform}.mp4"
    )


# ==========================================
# EXAMPLE: Clips API Endpoint
# ==========================================

@app.route("/api/clips/<job_id>")
def get_clips_json(job_id: str):
    """
    API endpoint to fetch clips as JSON (useful for AJAX updates).
    
    Returns: JSON array of ViralClip objects
    """
    
    # 1. Fetch raw analysis
    raw_analysis = fetch_clips_from_job(job_id)
    if not raw_analysis:
        return jsonify([])
    
    # 2. Build ViralClip objects
    source_video = get_job_video_path(job_id)
    full_transcript = get_job_transcript(job_id)
    
    clips = build_clips_from_analysis(
        analysis_results=raw_analysis,
        source_video=source_video,
        full_transcript=full_transcript,
    )
    
    # 3. Return as JSON
    return jsonify([clip_to_dict(c) for c in clips])


# ==========================================
# EXAMPLE: Generate Clip (from analysis)
# ==========================================

@app.route("/generate_clip_from_analysis", methods=["POST"])
@login_required
def generate_clip_from_analysis():
    """
    User selects a clip from carousel and requests final generation.
    
    This generates the actual playable video file if it doesn't exist.
    """
    
    clip_id = request.form.get("clip_id")
    job_id = request.form.get("job_id")
    
    # 1. Fetch the clip data
    clips_data = fetch_clips_from_job(job_id)
    clip_data = next((c for c in clips_data if c.get("clip_id") == clip_id), None)
    
    if not clip_data:
        return jsonify({"error": "Clip not found"}), 404
    
    # 2. Generate the video file
    source_video = get_job_video_path(job_id)
    output_path = f"static/outputs/{clip_id}_main.mp4"
    
    try:
        # Use fast FFmpeg stream copy
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip_data.get("start_time", 0)),
            "-to", str(clip_data.get("end_time", 15)),
            "-i", source_video,
            "-c", "copy",  # Stream copy (no re-encode)
            output_path,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        return jsonify({
            "success": True,
            "clip_url": f"/static/outputs/{clip_id}_main.mp4"
        })
    
    except Exception as e:
        print(f"Error generating clip: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# TEMPLATE: Update results_new.html
# ==========================================

# In your Flask template, inject the clips data:

"""
<!-- In templates/results_new.html, add this BEFORE the main script section -->
<script>
  // Inject the ViralClip objects as JSON
  // This makes the clips data available to the frontend JavaScript
  window.CLIPS_DATA = {{ clips_json | safe }};
</script>
"""


# ==========================================
# KNOWN UNDEFINED REFERENCES (YOU MUST DEFINE THESE)
# ==========================================

"""
These helper functions are PLACEHOLDERS - you must replace them with your actual code:

1. fetch_clips_from_job(job_id) - REQUIRED
   → Must query your raw analysis data (from Job.analysis_data)
   → Return format: List[Dict] with keys: start_time, end_time, text, hook_score, retention_score, clarity_score, emotion_score

2. get_job_video_path(job_id) - REQUIRED
   → Must return path to the video file for this job
   → Example from Job model: job.video_path

3. get_job_transcript(job_id) - REQUIRED
   → Must return the full transcript text
   → Example from Job model: job.transcript

4. Job.query - REQUIRED
   → This is from SQLAlchemy (already imported: from models.user import Job)
   → Usage: Job.query.filter_by(id=job_id).first()
"""


# ==========================================
# IMPLEMENTATION NOTES
# ==========================================

"""
STEP 1: REQUIRED - Your existing code must:
   ✓ Generate raw analysis (hooks, retention scores, etc.)
   ✓ Store it somewhere (DB, cache, filesystem)
   ✓ Have a way to retrieve it by job_id

STEP 2: Replace these placeholder functions with YOUR data sources:
   • fetch_clips_from_job(job_id) - Get analysis from your system
   • get_job_video_path(job_id) - Get video file path
   • get_job_transcript(job_id) - Get transcript text

STEP 3: The new system will:
   ✓ Read your raw analysis
   ✓ Transform into ViralClip objects with metadata
   ✓ Generate platform variants (YouTube, Instagram, TikTok)
   ✓ Serve via clean data contract
   ✓ Frontend renders intelligently

STEP 4: Copy-paste this code into your app.py:
   1. Copy the IMPORTS section to the top
   2. Copy the route functions
   3. Copy the helper functions
   4. Replace XXX_from_job() with YOUR actual data sources
   5. Add the template injection to results_new.html
   6. Test end-to-end
   7. Deploy!

BENEFITS:
   ✅ Backend owns intelligence (no frontend guessing)
   ✅ Frontend is purely a renderer
   ✅ Easy to add new platforms
   ✅ Easy to adjust scoring weights
   ✅ Easy to customize UI
   ✅ Real AI UX (users understand the decisions)

EXPECTED RESULT:
   Users see: Carousel with confidence scores, badges, reasoning
   Users feel: Confident and informed ✨

Got questions? Check:
   • ELITE_BUILD_INTEGRATION.md - Full integration guide
   • CONFIDENCE_AND_BADGES.md - Badge system
   • ARCHITECTURE_VISUAL.md - Visual diagrams
"""
