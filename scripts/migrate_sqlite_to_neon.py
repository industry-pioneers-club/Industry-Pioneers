"""One-shot, idempotent migration: instance/club.db  →  Neon Postgres.

USAGE
-----
    # 1. Set DATABASE_URL to the Neon connection string in your shell:
    export DATABASE_URL='postgresql://user:password@host/db?sslmode=require'

    # 2. Dry-run first — reads source, validates target, prints counts:
    python scripts/migrate_sqlite_to_neon.py --dry-run

    # 3. Run for real:
    python scripts/migrate_sqlite_to_neon.py

    # 4. If you ever need to RE-migrate into a non-empty target (destroys
    #    all data in the Neon DB first — be sure!):
    python scripts/migrate_sqlite_to_neon.py --force

DESIGN
------
- Source: the SQLite file at instance/club.db (opened read-only).
- Target: whatever DATABASE_URL points at (must be a managed Postgres).
- Source is NEVER modified. The script only reads from SQLite.
- Preserves every primary-key id so FKs across tables stay valid.
- Preserves password_hash exactly as stored (no re-hashing — users can
  still log in with their current passwords after migration).
- Bumps Postgres sequences after insert so new rows get fresh ids.
- Refuses to run if the target already contains user data, unless
  --force is passed (which TRUNCATEs every app table first).

This script does NOT print or log the DATABASE_URL anywhere.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SOURCE_DB_PATH = PROJECT_ROOT / "instance" / "club.db"

# Tables in INSERT order — children after their parents so FKs are
# satisfied. Mirrors the explicit relationships in app.py models.
# NB: ClubIdentity is seeded automatically by seed_if_empty on first
# boot, so we skip it here (it has no FK dependencies).
TABLES_IN_ORDER = [
    # Independent / parents first
    ("club_identity", None),
    ("sponsor", None),
    ("user", None),
    ("event", None),
    ("article", None),
    ("committee", None),
    # Children — reference user / event / article / committee
    ("membership_request", None),
    ("initiative", None),
    ("task", None),
    ("event_registration", None),
    ("activity_log", None),
    ("notification", None),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def _safe_url_hint(url: str) -> str:
    """Return a redacted form of the DB URL safe to print."""
    if not url:
        return "(unset)"
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        if parts.username:
            netloc = f"***@{netloc}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return "<redacted>"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Read source + validate target; do not insert.")
    parser.add_argument("--force", action="store_true",
                        help="Truncate every app table in the target before "
                             "migrating. Dangerous — ONLY use to re-migrate.")
    args = parser.parse_args()

    # ---- Preflight ----
    if not SOURCE_DB_PATH.exists():
        log(f"FATAL: source SQLite file not found at {SOURCE_DB_PATH}")
        return 2

    target_url = os.environ.get("DATABASE_URL", "").strip()
    if not target_url:
        log("FATAL: DATABASE_URL is unset — point it at your Neon Postgres.")
        return 2
    if "sqlite" in target_url.lower():
        log(f"FATAL: DATABASE_URL looks like SQLite ({_safe_url_hint(target_url)})"
            f" — refusing to migrate SQLite→SQLite.")
        return 2

    log(f"Source : {SOURCE_DB_PATH}")
    log(f"Target : {_safe_url_hint(target_url)}")
    log(f"Mode   : {'DRY RUN' if args.dry_run else ('FORCE RE-MIGRATE' if args.force else 'normal')}")

    # ---- Open source read-only ----
    import sqlite3
    src = sqlite3.connect(f"file:{SOURCE_DB_PATH}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    # Print source row counts so the user sees exactly what will migrate.
    log("\nSource row counts:")
    totals = {}
    for name, _ in TABLES_IN_ORDER:
        try:
            n = src.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        totals[name] = n
        log(f"  {name:<22} {n}")

    # ---- Open target via Flask app so schema matches EXACTLY ----
    # This is critical: we let app.py run its _upgrade_schema() against
    # the Postgres so every column we're about to INSERT already exists.
    log("\nInitializing target schema via app.initialize_database() ...")
    from app import app, db
    with app.app_context():
        # app.py's module-level init already ran create_all + _upgrade_schema
        # against DATABASE_URL. We can just use the session now.
        engine = db.engine
        from sqlalchemy import inspect, text

        insp = inspect(engine)
        target_tables = set(insp.get_table_names())
        log(f"  Target has {len(target_tables)} tables: {sorted(target_tables)}")

        # ---- Safety: target must be empty (or --force used) ----
        with engine.connect() as conn:
            try:
                existing_users = conn.execute(text('SELECT COUNT(*) FROM "user"')).scalar() or 0
            except Exception:
                existing_users = 0
        log(f"  Target user count before migrate: {existing_users}")

        if existing_users and not args.force and not args.dry_run:
            log("ABORTING: target already contains user data. Pass --force "
                "to truncate and re-migrate (destroys existing Postgres data).")
            return 3

        if args.dry_run:
            log("\nDRY RUN complete — nothing was written. Re-run without "
                "--dry-run to perform the migration.")
            return 0

        # ---- Optionally truncate target ----
        if args.force and existing_users:
            log("\n[--force] Truncating target tables ...")
            # Reverse order so children are cleared before parents.
            with engine.begin() as conn:
                for name, _ in reversed(TABLES_IN_ORDER):
                    if name in target_tables:
                        conn.execute(text(f'TRUNCATE TABLE "{name}" RESTART IDENTITY CASCADE'))
                        log(f"  truncated {name}")

        # ---- Copy rows table-by-table, preserving ids ----
        log("\nCopying rows ...")
        with engine.begin() as conn:
            # Defer FK constraints for the whole transaction so inter-table
            # ordering surprises can't block an otherwise valid migration.
            try:
                conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            except Exception:
                pass

            for name, _ in TABLES_IN_ORDER:
                if name not in target_tables:
                    log(f"  skipped {name:<22} (table not in target schema)")
                    continue
                try:
                    src_rows = src.execute(f'SELECT * FROM "{name}"').fetchall()
                except sqlite3.OperationalError as exc:
                    log(f"  skipped {name:<22} (source has no such table: {exc})")
                    continue
                if not src_rows:
                    log(f"  copied  {name:<22} 0 rows")
                    continue
                # Only insert columns that exist in BOTH source and target —
                # ignores Postgres-only columns (filled by DEFAULT) and
                # SQLite-only columns (not useful on Postgres).
                src_cols = set(src_rows[0].keys())
                tgt_cols = {c["name"] for c in insp.get_columns(name)}
                shared = [c for c in src_rows[0].keys() if c in tgt_cols]
                col_list = ", ".join(f'"{c}"' for c in shared)
                placeholders = ", ".join(f":{c}" for c in shared)
                stmt = text(f'INSERT INTO "{name}" ({col_list}) VALUES ({placeholders})')
                inserted = 0
                for row in src_rows:
                    values = {c: row[c] for c in shared}
                    conn.execute(stmt, values)
                    inserted += 1
                dropped_cols = src_cols - tgt_cols
                extra = f" (dropped src-only cols: {sorted(dropped_cols)})" if dropped_cols else ""
                log(f"  copied  {name:<22} {inserted} rows{extra}")

            # ---- Fix sequences so new rows don't collide with migrated ids ----
            # On Postgres, SERIAL / IDENTITY columns have an associated sequence.
            # After we insert explicit ids, the sequence's counter is still at
            # its original value — the next INSERT without an id would collide.
            # Bump each sequence to max(id)+1.
            log("\nResynchronizing Postgres id sequences ...")
            for name, _ in TABLES_IN_ORDER:
                if name not in target_tables:
                    continue
                has_id = any(c["name"] == "id" for c in insp.get_columns(name))
                if not has_id:
                    continue
                try:
                    conn.execute(text(
                        f'SELECT setval(pg_get_serial_sequence(\'"{name}"\', \'id\'), '
                        f'COALESCE((SELECT MAX(id) FROM "{name}"), 1), '
                        f'(SELECT MAX(id) FROM "{name}") IS NOT NULL)'
                    ))
                except Exception as exc:
                    log(f"  warn: could not resync {name}: {exc}")

        # ---- Verify ----
        log("\nTarget row counts after migrate:")
        all_ok = True
        with engine.connect() as conn:
            for name, _ in TABLES_IN_ORDER:
                if name not in target_tables:
                    continue
                tgt = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() or 0
                src_n = totals.get(name, 0)
                match = tgt >= src_n
                mark = "OK" if match else "MISMATCH"
                log(f"  [{mark}] {name:<22} src={src_n:<5} tgt={tgt}")
                if not match:
                    all_ok = False

        src.close()
        log("\n" + ("Migration complete." if all_ok else "Migration finished WITH MISMATCHES — review above."))
        return 0 if all_ok else 4


if __name__ == "__main__":
    sys.exit(main())
