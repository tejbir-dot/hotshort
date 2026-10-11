import sqlite3
import os

def patch_db():
    paths = ['data/hotshort.db', 'instance/hotshort.db']
    for p in paths:
        if not os.path.exists(p):
            continue
        conn = sqlite3.connect(p)
        c = conn.cursor()
        for col_def in ["creator_intent TEXT", "usage_counted BOOLEAN DEFAULT 0 NOT NULL"]:
            col_name = col_def.split()[0]
            try:
                c.execute(f"ALTER TABLE job ADD COLUMN {col_def}")
                print(f"[{p}] Added column '{col_name}' to job table.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    pass
                else:
                    print(f"[{p}] Error adding {col_name}:", e)
        conn.commit()
        conn.close()

if __name__ == "__main__":
    patch_db()

