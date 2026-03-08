import os


class Config:
    # Treat empty env var as missing so sessions always have a usable key.
    SECRET_KEY = os.getenv("SECRET_KEY") or "change-me-in-prod"
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DB_DIR = os.path.join(BASE_DIR, "data")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(DB_DIR, 'hotshort.db')}"
)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # OAuth
    GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    GOOGLE_OAUTH_CLIENT_ID_LOCAL = os.getenv("GOOGLE_OAUTH_CLIENT_ID_LOCAL", "")
    GOOGLE_OAUTH_CLIENT_SECRET_LOCAL = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_LOCAL", "")
    GOOGLE_OAUTH_CLIENT_ID_PROD = os.getenv("GOOGLE_OAUTH_CLIENT_ID_PROD", "")
    GOOGLE_OAUTH_CLIENT_SECRET_PROD = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_PROD", "")
    EXTERNAL_BASE_URL = (os.getenv("EXTERNAL_BASE_URL") or "").strip().rstrip("/")

    # Stripe
    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

    # --- Worker/async job configuration ---
    HS_WORKER_MODE = os.getenv("HS_WORKER_MODE", "")
    HS_WORKER_QUEUE_URL = os.getenv("HS_WORKER_QUEUE_URL", "")
    HS_ENABLE_COMMENTS = os.getenv("HS_ENABLE_COMMENTS", "0")
    HS_COMMENTS_TOP_N = os.getenv("HS_COMMENTS_TOP_N", "100")
    HS_SIGNAL_DEGRADED_THRESHOLD = os.getenv("HS_SIGNAL_DEGRADED_THRESHOLD", "0.45")
    HS_PROFILE_DEFAULT = os.getenv("HS_PROFILE_DEFAULT", "balanced")
    HS_WORKER_TIMEOUT_SEC = os.getenv("HS_WORKER_TIMEOUT_SEC", "")
