"""Isolated Phase 3A launcher. Binds :5055 to club.phase3a-test.db."""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEST_DB = os.path.abspath(os.path.join(_HERE, "..", "instance", "club.phase3a-test.db"))
if not os.path.exists(_TEST_DB):
    raise RuntimeError(f"test DB not found at {_TEST_DB!r}")

os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB
env_uri = os.environ["DATABASE_URL"]
assert "club.phase3a-test.db" in env_uri
assert not env_uri.endswith("/club.db") and not env_uri.endswith("\\club.db")
print(f"[phase3a] launcher DATABASE_URL = {env_uri}")

sys.path.insert(0, _HERE)
import app  # noqa: E402

resolved = app.app.config["SQLALCHEMY_DATABASE_URI"]
print(f"[phase3a] resolved URI       = {resolved}")
assert "club.phase3a-test.db" in resolved
assert not resolved.endswith("/club.db") and not resolved.endswith("\\club.db")
print("[phase3a] isolation verified; starting on 127.0.0.1:5055")

if __name__ == "__main__":
    app.app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
