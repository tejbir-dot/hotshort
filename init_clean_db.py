#!/usr/bin/env python
"""
Quick script to initialize a clean database without loading heavy ML models
"""
import os
import sys

# Set up paths
sys.path.insert(0, os.path.dirname(__file__))

# Minimal Flask app setup ONLY for database
from flask import Flask
from models.user import db, User, Clip, Job, Plan, Subscription
from models.clip import ClipFeedback

app = Flask(__name__)
# Use absolute path for SQLite database
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'hotshort.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path.replace(chr(92), "/")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

if __name__ == '__main__':
    with app.app_context():
        print("🔨 Creating database tables...")
        db.create_all()
        print("✅ Database initialized successfully!")
        print("\nSchema created:")
        print("  ✓ User")
        print("  ✓ Clip (with job_id foreign key)")
        print("  ✓ Job")
        print("  ✓ Plan")
        print("  ✓ Subscription")
        print("  ✓ ClipFeedback")
