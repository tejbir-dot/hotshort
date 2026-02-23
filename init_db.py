#!/usr/bin/env python
"""
Quick database initialization script - adds Job table to existing database
"""
import sqlite3
import os
from datetime import datetime

# Path to the database
db_path = 'instance/hotshort.db'

# SQL to create the job table if it doesn't exist
create_job_table = '''
CREATE TABLE IF NOT EXISTS job (
    id VARCHAR(50) PRIMARY KEY,
    user_id INTEGER NOT NULL,
    video_path VARCHAR(300),
    transcript TEXT,
    analysis_data TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES user(id)
)
'''

try:
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create the job table
    cursor.execute(create_job_table)
    conn.commit()
    
    # Verify it was created
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job'")
    result = cursor.fetchone()
    
    if result:
        print("✅ Job table created successfully!")
        print(f"   Database: {db_path}")
    else:
        print("⚠️  Job table creation failed")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")

