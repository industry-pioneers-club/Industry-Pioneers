"""One-shot DB backup via SQLite online backup API. Refuses to overwrite."""
import sqlite3, hashlib, os, sys

sys.stdout.reconfigure(encoding='utf-8')

SRC = "instance/club.db"
DST = "instance/club.db.pre-phase4-full"

if os.path.exists(DST):
    print(f"REFUSE: {DST} already exists")
    sys.exit(1)
if not os.path.exists(SRC):
    print(f"REFUSE: {SRC} missing")
    sys.exit(1)

src = sqlite3.connect(SRC)
dst = sqlite3.connect(DST)
with dst:
    src.backup(dst)
src.close()
dst.close()

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

def rows(p):
    c = sqlite3.connect(p).cursor()
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

src_rows, dst_rows = rows(SRC), rows(DST)
integrity = sqlite3.connect(DST).execute("PRAGMA integrity_check").fetchone()

print("backup path  :", DST)
print("backup bytes :", os.path.getsize(DST))
print("src sha256   :", sha(SRC))
print("dst sha256   :", sha(DST), "(may differ -- normal for backup API)")
print("src rows     :", src_rows)
print("dst rows     :", dst_rows)
print("integrity    :", integrity)

if src_rows != dst_rows:
    print("FAIL: row count mismatch")
    sys.exit(2)
if integrity != ("ok",):
    print("FAIL: integrity_check")
    sys.exit(3)
print("BACKUP VERIFIED")
