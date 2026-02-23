# 🔄 MIGRATION QUICK REFERENCE

## Current State ✅
- Database: `instance/hotshort.db`
- Status: Clean and in sync with models
- Last reset: February 1, 2026
- No pending migrations

---

## Make a Schema Change (Step-by-Step)

### Step 1: Modify Your Model
```python
# models/user.py
class User(db.Model):
    # ... existing columns ...
    new_column = db.Column(db.String(100), nullable=True)  # ← ADD THIS
```

### Step 2: Generate Migration
```bash
flask db migrate -m "Added new_column to user"
# Output: "INFO  [alembic.revision.RevisionFile] Generating ..."
```

### Step 3: Apply Migration
```bash
flask db upgrade
# Output: "INFO  [alembic.runtime.migration] Running upgrade ..."
```

### Step 4: Verify (Optional)
```bash
python verify_schema.py
```

---

## If Migrations Get Stuck Again

⚠️ **Only if you're in pre-production:**

```bash
# 1. Stop the app (Ctrl+C)

# 2. Delete old migrations
rm migrations/versions/*

# 3. Delete database
del instance/hotshort.db

# 4. Recreate database
python init_clean_db.py

# 5. Fresh migrations
flask db migrate -m "initial clean schema"
flask db upgrade

# 6. Restart app
python app.py
```

---

## Quick Checks

### Is my database up to date?
```bash
flask db migrate
# "No changes in schema detected" = ✅ Good
# "Generating migrations" = Need to upgrade
```

### What tables exist?
```bash
python verify_schema.py
```

### Reset migrations (pre-production only)
```bash
python init_clean_db.py
```

---

## Important Notes

✅ Models in: `models/user.py` and `models/clip.py`  
✅ Database in: `instance/hotshort.db`  
✅ Config in: `settings.py` (SQLALCHEMY_DATABASE_URI)  
✅ Migrations in: `migrations/versions/` (auto-generated)  
✅ App startup: `db.create_all()` called automatically  

---

## Production Checklist

Before deploying to production:

- [ ] Switch to PostgreSQL (easier migrations)
- [ ] Test all model changes locally
- [ ] Run migrations on staging
- [ ] Backup production database
- [ ] Run migrations on production
- [ ] Verify schema matches models

---

**Last Updated:** February 1, 2026
