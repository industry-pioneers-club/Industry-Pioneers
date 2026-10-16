"""Isolated Phase 1 test launcher.

Binds 127.0.0.1:5055 to the isolated app.py in this subfolder.
DATABASE_URL points at ../instance/club.event-test.db — never the shared DB.

Three isolation guarantees:
  1. Entry point is this _run.py which imports from the local app.py in the
     same directory. It does NOT import the live app.py from the parent dir.
  2. DATABASE_URL is set BEFORE `import app`, so _database_uri() resolves
     to the test DB when it is called at module top-level.
  3. After import, we assert the resolved URI contains 'club.event-test.db'
     and does not end with 'club.db'. If either fails, we exit without
     ever calling app.run().
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# Layer 2: point DATABASE_URL at the test DB BEFORE importing app.
_HERE = os.path.dirname(os.path.abspath(__file__))
_TEST_DB_PATH = os.path.abspath(os.path.join(_HERE, "..", "instance", "club.event-test.db"))
if not os.path.exists(_TEST_DB_PATH):
    raise RuntimeError(f"test DB not found at {_TEST_DB_PATH!r}")

os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB_PATH

# Launcher-level assertion.
_env_uri = os.environ["DATABASE_URL"]
assert "club.event-test.db" in _env_uri, f"UNSAFE launcher env: {_env_uri!r}"
assert not _env_uri.endswith("/club.db"), f"UNSAFE: {_env_uri!r}"
assert not _env_uri.endswith("\\club.db"), f"UNSAFE: {_env_uri!r}"
print(f"[isolated_phase1] launcher DATABASE_URL = {_env_uri}")

# Make sure 'import app' resolves to THIS directory's app.py, not the parent.
sys.path.insert(0, _HERE)
import app  # noqa: E402

# Layer 3: final resolved-URI assertion.
_resolved = app.app.config["SQLALCHEMY_DATABASE_URI"]
print(f"[isolated_phase1] resolved URI       = {_resolved}")
assert "club.event-test.db" in _resolved, f"UNSAFE resolved URI: {_resolved!r}"
assert not _resolved.endswith("/club.db"), f"UNSAFE: {_resolved!r}"
assert not _resolved.endswith("\\club.db"), f"UNSAFE: {_resolved!r}"
print("[isolated_phase1] isolation verified; starting on 127.0.0.1:5055")

if __name__ == "__main__":
    app.app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
