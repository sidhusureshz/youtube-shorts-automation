import sqlite3
conn = sqlite3.connect('pipeline.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print("Tables found:", tables)
print("Total table count:", len(tables))
for t in tables:
    cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
    count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"\n  [{t}] rows={count} cols={[c[1] for c in cols]}")
conn.close()
