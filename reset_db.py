from app import app
from models.user import db

with app.app_context():
    db.drop_all()
    db.create_all()
    print("✅ Database reset & recreated successfully!")
