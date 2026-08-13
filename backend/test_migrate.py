import sys, time
sys.path.insert(0, ".")
t0 = time.time()
print("importing app...", flush=True)
from app import db, store
print(f"import done in {time.time()-t0:.1f}s (init_schema + auto_migrate ran during import)", flush=True)

db.close_pool()
with db.db_conn() as conn:
    count = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"]
    print(f"plans table has {count} row(s)", flush=True)
    if count > 0:
        rows = conn.execute("SELECT id, title FROM plans").fetchall()
        for r in rows:
            print(f"  {r['id']}  {r['title']}")
db.close_pool()
print(f"total: {time.time()-t0:.1f}s", flush=True)
