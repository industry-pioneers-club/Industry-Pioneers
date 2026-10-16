"""Tier 1 isolated test launcher.

Binds 127.0.0.1:5055 to a Flask app loaded from _app_tier1 (not app).
_app_tier1 is a standalone copy of app.py plus Tier 1 route changes,
and includes its own hard safety check that refuses to start unless
DATABASE_URL resolves to instance/club.event-test.db.

Three isolation layers:
  1. No `import app` here or in _app_tier1 — separate module avoids
     app.py's import-time side effects running against the shared DB.
  2. DATABASE_URL is set BEFORE `import _app_tier1`, so _database_uri()
     resolves to the test DB when it is called at line 55 of _app_tier1.
  3. Both this launcher AND _app_tier1 assert the resolved URI contains
     "club.event-test.db" and does not end with "club.db" before any
     SQLAlchemy engine is created.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# Layer 2: point DATABASE_URL at the test DB BEFORE importing _app_tier1.
_TEST_DB_PATH = os.path.abspath(os.path.join("instance", "club.event-test.db"))
if not os.path.exists(_TEST_DB_PATH):
    raise RuntimeError(f"test DB not found at {_TEST_DB_PATH!r}; run prep script first")

os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB_PATH

# Launcher-level assertion (fast fail before any _app_tier1 import):
_env_uri = os.environ["DATABASE_URL"]
assert "club.event-test.db" in _env_uri, f"UNSAFE launcher env: {_env_uri!r}"
assert not _env_uri.endswith("/club.db"), f"UNSAFE launcher env: {_env_uri!r}"
assert not _env_uri.endswith("\\club.db"), f"UNSAFE launcher env: {_env_uri!r}"
print(f"[tier1] launcher DATABASE_URL = {_env_uri}")

# Layer 1 + 3: import _app_tier1 (its in-module safety check will fire if
# DATABASE_URL is wrong, aborting with RuntimeError before SQLAlchemy init).
import _app_tier1  # noqa: E402

# Final sanity: confirm what SQLAlchemy actually resolved to.
_resolved = _app_tier1.app.config["SQLALCHEMY_DATABASE_URI"]
print(f"[tier1] resolved URI       = {_resolved}")
assert "club.event-test.db" in _resolved, f"UNSAFE resolved URI: {_resolved!r}"
assert not _resolved.endswith("/club.db"), f"UNSAFE resolved URI: {_resolved!r}"
assert not _resolved.endswith("\\club.db"), f"UNSAFE resolved URI: {_resolved!r}"
print("[tier1] isolation verified; starting server on 127.0.0.1:5055")

if __name__ == "__main__":
    _app_tier1.app.run(
        host="127.0.0.1",
        port=5055,
        debug=False,
        use_reloader=False,
    )
