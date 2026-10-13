from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import UniqueConstraint
import secrets
import string

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
    # Google Identity + Unified generation limits
    google_sub = db.Column(db.String(255), unique=True, nullable=True)
    free_generations_used = db.Column(db.Integer, default=0, nullable=False)

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
    creator_intent = db.Column(db.Text, nullable=True) # Custom prompt for clip extraction
    status = db.Column(db.String(50), default="pending")  # pending, processing, completed, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    usage_counted = db.Column(db.Boolean, default=False, nullable=False)
    
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


class UserExport(db.Model):
    __tablename__ = "user_export"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    clip_id = db.Column(db.String(50), nullable=False)
    clip_name = db.Column(db.String(150), default="Untitled Clip")
    platform_format = db.Column(db.String(50), nullable=False)
    duration = db.Column(db.Float, nullable=True)
    file_path = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



def _generate_referral_code(length=8):
    """Generate a unique-ish alphanumeric referral code."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class Partner(db.Model):
    """Partner/Affiliate account — one per User."""
    __tablename__ = "partner"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    referral_code = db.Column(db.String(20), unique=True, nullable=False, default=_generate_referral_code)
    social_handle = db.Column(db.String(120), nullable=True)  # Raw handle or channel URL
    channel_url   = db.Column(db.String(300), nullable=True)  # Full channel link pasted by user
    platform      = db.Column(db.String(50),  nullable=True)  # YouTube / TikTok / Instagram etc.
    wallet_usd = db.Column(db.Float, default=0.0, nullable=False)  # Accumulated earnings in USD
    total_clicks = db.Column(db.Integer, default=0, nullable=False)
    total_signups = db.Column(db.Integer, default=0, nullable=False)
    total_conversions = db.Column(db.Integer, default=0, nullable=False)  # Paid subscriptions
    total_earned_usd = db.Column(db.Float, default=0.0, nullable=False)  # All-time earned
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    payout_method = db.Column(db.String(20),  nullable=True)  # upi / paypal / bank / crypto
    payout_info   = db.Column(db.String(300), nullable=True)  # UPI ID, PayPal email, wallet addr

    # Relationship back to user
    user = db.relationship('User', backref=db.backref('partner', uselist=False))
    # Conversions list
    conversions = db.relationship('PartnerConversion', backref='partner', lazy='dynamic')

    def __repr__(self):
        return f'<Partner code={self.referral_code} wallet=${self.wallet_usd:.2f}>'


class PartnerConversion(db.Model):
    """Records each paid subscription that came through a partner link."""
    __tablename__ = "partner_conversion"

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False, index=True)
    # The new user who subscribed via this partner
    converted_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    plan_name = db.Column(db.String(50), nullable=False, default='starter')
    amount_usd = db.Column(db.Float, nullable=False)  # What partner earns for this conversion
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    stripe_session_id = db.Column(db.String(200), nullable=True)  # Audit trail

    def __repr__(self):
        return f'<PartnerConversion partner={self.partner_id} +${self.amount_usd}>'
