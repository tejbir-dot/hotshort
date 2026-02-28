from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200))
    name = db.Column(db.String(120))
    # URLs from Google can exceed 300 characters, so use Text instead of bounded String
    profile_pic = db.Column(db.Text)
    # Legacy billing label (kept for Stripe/backwards compatibility)
    subscription_plan = db.Column(db.String(50), default="free")
    subscription_status = db.Column(db.String(50), default="active")
    clips_this_week = db.Column(db.Integer, default=0)
    last_reset = db.Column(db.DateTime, default=datetime.utcnow)
    # New unified pricing state
    # "trial", "starter", "pro", "industry"
    plan_type = db.Column(db.String(50), default="trial", nullable=False)
    # Free trial usage accounting (server authoritative)
    trial_analyze_count = db.Column(db.Integer, default=0, nullable=False)
    trial_clip_exports = db.Column(db.Integer, default=0, nullable=False)

class FreeClipClaim(db.Model):
    __tablename__ = "free_clip_claim"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    clip_id = db.Column(db.Integer, db.ForeignKey('clip.id'), nullable=False, index=True)
    claimed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "clip_id", name="uq_free_clip_claim_user_clip"),
    )

class Clip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150))
    file_path = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    # Link clip to a Job (optional)
    job_id = db.Column(db.String(50), db.ForeignKey('job.id'), nullable=True)
    # Clip metadata
    start = db.Column(db.Float, nullable=True)
    end = db.Column(db.Float, nullable=True)
    score = db.Column(db.Float, nullable=True)
    label = db.Column(db.String(120), nullable=True)

class Job(db.Model):
    """Video processing job with analysis results"""
    id = db.Column(db.String(50), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_path = db.Column(db.String(300), nullable=True)
    transcript = db.Column(db.Text, nullable=True)
    analysis_data = db.Column(db.Text, nullable=True)  # JSON string of analysis results
    status = db.Column(db.String(50), default="pending")  # pending, processing, completed, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f"<Job {self.id}>"

class Plan(db.Model):
    """Pricing plans"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # starter, creator, pro
    display_name = db.Column(db.String(100), nullable=False)  # "🚀 Starter", "🔥 Creator", "⚡ Pro"
    price = db.Column(db.Float, nullable=False)  # in rupees
    billing_period = db.Column(db.String(20), default="monthly")  # monthly, one-time
    features = db.Column(db.Text, nullable=False)  # JSON string of features
    is_recommended = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<Plan {self.name}>"

class Subscription(db.Model):
    """User subscriptions to plans"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    stripe_subscription_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), default="active")  # active, cancelled, expired
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    auto_renew = db.Column(db.Boolean, default=True)
    
    # Relationship
    plan = db.relationship('Plan', backref='subscriptions')
    
    def __repr__(self):
        return f"<Subscription user={self.user_id} plan={self.plan_id}>"
