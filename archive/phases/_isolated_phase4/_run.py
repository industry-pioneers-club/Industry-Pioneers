"""Isolated Phase 4 launcher. Binds :5055 to club.phase4-test.db."""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEST_DB = os.path.abspath(os.path.join(_HERE, "..", "instance", "club.phase4-test.db"))
if not os.path.exists(_TEST_DB):
    raise RuntimeError(f"test DB not found at {_TEST_DB!r}")

os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB
env_uri = os.environ["DATABASE_URL"]
assert "club.phase4-test.db" in env_uri
assert not env_uri.endswith("/club.db") and not env_uri.endswith("\\club.db")
print(f"[phase4] launcher DATABASE_URL = {env_uri}")

sys.path.insert(0, _HERE)
import app  # noqa: E402

resolved = app.app.config["SQLALCHEMY_DATABASE_URI"]
print(f"[phase4] resolved URI       = {resolved}")
assert "club.phase4-test.db" in resolved
assert not resolved.endswith("/club.db") and not resolved.endswith("\\club.db")
print("[phase4] isolation verified; starting on 127.0.0.1:5055")

if __name__ == "__main__":
    app.app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
