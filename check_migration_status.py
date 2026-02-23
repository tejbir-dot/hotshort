#!/usr/bin/env python
"""
Status check: Verify migration and database are ready
Run this anytime to confirm everything is working
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask
from models.user import db

def check_status():
    app = Flask(__name__)
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'hotshort.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path.replace(chr(92), "/")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    
    print("=" * 60)
    print("🔍 MIGRATION & DATABASE STATUS CHECK")
    print("=" * 60)
    
    with app.app_context():
        from sqlalchemy import inspect, text
        
        try:
            # Test connection
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("\n✅ Database Connection: WORKING")
        except Exception as e:
            print(f"\n❌ Database Connection: FAILED - {e}")
            return False
        
        # Check tables
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        print(f"\n📋 Tables Found: {len(tables)}")
        expected_tables = ['user', 'clip', 'job', 'plan', 'subscription', 'clip_feedback', 'alembic_version']
        for table in expected_tables:
            status = "✅" if table in tables else "❌"
            print(f"   {status} {table}")
        
        # Check job_id column in clip
        print("\n🔗 Critical Column Check:")
        clip_columns = [col['name'] for col in inspector.get_columns('clip')]
        if 'job_id' in clip_columns:
            print("   ✅ Clip.job_id exists")
        else:
            print("   ❌ Clip.job_id MISSING")
        
        # Check alembic_version table
        alembic_tables = [t for t in tables if 'alembic' in t.lower()]
        if alembic_tables:
            print(f"\n✅ Alembic Migration Tracking: ACTIVE")
        else:
            print(f"\n⚠️  Alembic Migration Tracking: NOT INITIALIZED")
        
        print("\n" + "=" * 60)
        print("🟢 ALL SYSTEMS READY FOR PRODUCTION" if all(
            t in tables for t in expected_tables
        ) and 'job_id' in clip_columns else "🔴 ISSUES DETECTED")
        print("=" * 60)
        
        return True

if __name__ == '__main__':
    try:
        check_status()
    except KeyboardInterrupt:
        print("\n⏸️  Check interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Check failed: {e}")
        sys.exit(1)
