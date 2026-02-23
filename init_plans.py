#!/usr/bin/env python
"""
Initialize pricing plans in the database.
Run this once to set up the starter, creator, and pro plans.
"""

import sys
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, '/'.join(__file__.split('/')[:-1]))

from app import app, db
from models.user import Plan

def init_plans():
    """Create the 3 pricing plans"""
    
    with app.app_context():
        # Check if plans already exist
        existing_plans = Plan.query.count()
        if existing_plans > 0:
            print("✅ Plans already exist in database. Skipping initialization.")
            return
        
        plans = [
            {
                'name': 'starter',
                'display_name': '🚀 Starter',
                'price': 199,
                'billing_period': 'one-time',
                'features': json.dumps([
                    'Download all clips',
                    'Watermark removed',
                    '1 platform export',
                ]),
                'is_recommended': False,
            },
            {
                'name': 'creator',
                'display_name': '🔥 Creator',
                'price': 499,
                'billing_period': 'monthly',
                'features': json.dumps([
                    'Unlimited videos',
                    'All platform exports',
                    'Priority processing',
                    'Best Pick boost',
                ]),
                'is_recommended': True,
            },
            {
                'name': 'pro',
                'display_name': '⚡ Pro',
                'price': 1499,
                'billing_period': 'monthly',
                'features': json.dumps([
                    'Everything in Creator',
                    'Bulk exports',
                    'Faster processing',
                    'Early features',
                ]),
                'is_recommended': False,
            },
        ]
        
        for plan_data in plans:
            plan = Plan(**plan_data)
            db.session.add(plan)
        
        db.session.commit()
        print("✅ Plans initialized successfully!")
        print(f"   - Starter: ₹199/video (one-time)")
        print(f"   - Creator: ₹499/month (recommended)")
        print(f"   - Pro: ₹1,499/month")

if __name__ == '__main__':
    init_plans()
