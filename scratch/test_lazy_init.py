import os
import sys

# Add current directory to path
sys.path.insert(0, os.getcwd())

print("Importing app...")
from app import app, _db_initialized
print(f"Initial _db_initialized: {_db_initialized}")

# Simulate a request
print("Simulating a request...")
with app.test_request_context('/'):
    # In Flask, before_request hooks are called during app.preprocess_request()
    app.preprocess_request()

from app import _db_initialized as db_init_after
print(f"Final _db_initialized: {db_init_after}")

if db_init_after:
    print("SUCCESS: Database lazy initialization triggered.")
else:
    print("FAILURE: Database lazy initialization was NOT triggered.")
    sys.exit(1)
