#!/usr/bin/env python
"""Verify database schema"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask
from models.user import db

app = Flask(__name__)
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'hotshort.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path.replace(chr(92), "/")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    from sqlalchemy import inspect
    
    inspector = inspect(db.engine)
    
    print("=== CLIP TABLE SCHEMA ===")
    columns = inspector.get_columns('clip')
    for col in columns:
        print(f"  {col['name']:15} {str(col['type']):20} nullable={col['nullable']}")
    
    print("\n=== JOB TABLE SCHEMA ===")
    columns = inspector.get_columns('job')
    for col in columns:
        print(f"  {col['name']:15} {str(col['type']):20} nullable={col['nullable']}")
    
    print("\n=== USER TABLE SCHEMA ===")
    columns = inspector.get_columns('user')
    for col in columns:
        print(f"  {col['name']:15} {str(col['type']):20} nullable={col['nullable']}")
    
    print("\n✅ All tables verified!")
