import os


class Config:
    # Treat empty env var as missing so sessions always have a usable key.
    SECRET_KEY = os.getenv("SECRET_KEY") or "change-me-in-prod"
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DB_DIR = os.path.join(BASE_DIR, "data")

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(DB_DIR, 'hotshort.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # OAuth
    GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")

    # Stripe
    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
