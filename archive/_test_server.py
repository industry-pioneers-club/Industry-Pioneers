


"""Launch Flask on an alternate port against the test DB. Not for production."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.abspath("instance/club.event-test.db"))
from app import app
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
