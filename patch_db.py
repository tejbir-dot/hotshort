import sqlite3

def patch_db():
    conn = sqlite3.connect('instance/hotshort.db')
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE job ADD COLUMN creator_intent TEXT")
        print("Successfully added creator_intent to Job table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column creator_intent already exists.")
        else:
            print("Error:", e)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    patch_db()
