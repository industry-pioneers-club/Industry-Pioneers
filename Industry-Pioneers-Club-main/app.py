import hmac
import logging
import os
from datetime import datetime
from functools import wraps

try:
    import fcntl
except ImportError:  # Non-Unix interpreters have no file locks.
    fcntl = None

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)
logger = logging.getLogger(__name__)


def _database_uri():
    # DATABASE_URL overrides the local file for tests. Default is instance/club.db.
    uri = os.environ.get("DATABASE_URL", "").strip()
    if not uri:
        return "sqlite:///" + os.path.join(app.instance_path, "club.db")
    # Render Postgres URLs use postgres://, which SQLAlchemy does not accept.
    if uri.startswith("postgres://"):
        return "postgresql://" + uri[len("postgres://") :]
    return uri


def _secure_session_cookie():
    flask_env = os.environ.get("FLASK_ENV", "").strip().lower()
    render_flag = os.environ.get("RENDER", "").strip().lower()
    return flask_env == "production" or render_flag in {"1", "true", "yes"}


# Production must set SECRET_KEY.
_secret_key = os.environ.get("SECRET_KEY", "").strip()
if not _secret_key:
    logger.warning(
        "SECRET_KEY is not set; using the development fallback. Set SECRET_KEY before production."
    )
    _secret_key = "dev-secret-key"
app.config["SECRET_KEY"] = _secret_key
app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# On when FLASK_ENV=production or Render sets RENDER=true. Off for local http.
app.config["SESSION_COOKIE_SECURE"] = _secure_session_cookie()

db = SQLAlchemy(app)


def _safe_static_rel(path):
    if not isinstance(path, str):
        return None
    rel = path.strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    return rel


@app.template_filter("static_image")
def static_image(path):
    rel = _safe_static_rel(path)
    if rel is None or not os.path.isfile(os.path.join(app.static_folder, rel)):
        return None
    return url_for("static", filename=rel)


@app.template_filter("shortdate")
def shortdate(value):
    if value is None:
        return ""
    try:
        return value.strftime("%d %b %Y")
    except AttributeError:
        return str(value)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    image_path = db.Column(db.String(300))
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    date = db.Column(db.DateTime, nullable=False)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author_name = db.Column(db.String(120), nullable=False)
    author_sector = db.Column(db.String(120), nullable=False)
    date_published = db.Column(db.DateTime, nullable=False)
    likes_count = db.Column(db.Integer, nullable=False, default=0)
    image_path = db.Column(db.String(300))


class Sponsor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_path = db.Column(db.String(300))
    tier = db.Column(db.String(50), nullable=False)


class ClubIdentity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    mission = db.Column(db.Text, nullable=False)
    vision = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="visitor")


login_manager = LoginManager(app)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def unauthorized():
    abort(403)


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


# Used only so a missing account is not obviously faster than a bad password.
_LOGIN_DUMMY_HASH = generate_password_hash("invalid-login")


# Paths that earlier seeds stored, mapped to files that exist in static/.
_IMAGE_FIXES = {
    "images/factory-open-day.jpg": "Image/event-4.png",
    "images/planning-session.jpg": "Image/event-5.png",
    "images/lean-production.jpg": "Image/hero.png",
    "images/mentoring.jpg": "Image/about.png",
    "images/gulf-steel.png": "Image/5909072811534257919.jpg",
    "images/najd-logistics.png": "Image/5909072811534257918.jpg",
}
_EVENT_FALLBACKS = ("Image/event-4.png", "Image/event-5.png", "Image/event-6.png")
_ARTICLE_FALLBACKS = ("Image/hero.png", "Image/about.png", "Image/event-6.png", "Image/event-5.png")
_SPONSOR_FALLBACKS = (
    "Image/5909072811534257919.jpg",
    "Image/5909072811534257918.jpg",
    "Image/5909072811534257936.jpg",
    "Image/5909072811534257937.jpg",
)


def _static_file_exists(path):
    rel = _safe_static_rel(path)
    return bool(rel) and os.path.isfile(os.path.join(app.static_folder, rel))


def _sample_events():
    return [
        Event(
            title="Factory Floor Open Day",
            image_path="Image/event-4.png",
            is_public=True,
            date=datetime(2026, 4, 12, 10, 0),
        ),
        Event(
            title="Leadership Planning Session",
            image_path="Image/event-5.png",
            is_public=False,
            date=datetime(2026, 5, 3, 18, 0),
        ),
        Event(
            title="United Glass Plant Visit",
            image_path="Image/event-6.png",
            is_public=True,
            date=datetime(2026, 11, 15, 8, 0),
        ),
        Event(
            title="Industrial Innovation Meetup",
            image_path="Image/event-4.png",
            is_public=True,
            date=datetime(2026, 12, 2, 9, 0),
        ),
    ]


def _sample_articles():
    return [
        Article(
            title="How Local Plants Adopt Lean Production",
            author_name="Sara Al-Harbi",
            author_sector="Manufacturing",
            date_published=datetime(2026, 2, 18, 9, 0),
            likes_count=0,
            image_path="Image/hero.png",
        ),
        Article(
            title="Mentoring the Next Plant Engineers",
            author_name="Omar Al-Qahtani",
            author_sector="Engineering",
            date_published=datetime(2026, 3, 2, 9, 0),
            likes_count=0,
            image_path="Image/about.png",
        ),
        Article(
            title="Safety on the Factory Floor",
            author_name="Nora Al-Johani",
            author_sector="Safety",
            date_published=datetime(2026, 9, 1, 9, 0),
            likes_count=0,
            image_path="Image/event-6.png",
        ),
        Article(
            title="From Campus to the Production Line",
            author_name="Fahd Al-Qahtani",
            author_sector="Logistics",
            date_published=datetime(2026, 9, 28, 9, 0),
            likes_count=0,
            image_path="Image/event-5.png",
        ),
    ]


def _sample_sponsors():
    return [
        Sponsor(
            name="Gulf Steel Co.",
            logo_path="Image/5909072811534257919.jpg",
            tier="Gold",
        ),
        Sponsor(
            name="Najd Logistics",
            logo_path="Image/5909072811534257918.jpg",
            tier="Silver",
        ),
        Sponsor(
            name="BusinessHub",
            logo_path="Image/5909072811534257936.jpg",
            tier="Gold",
        ),
        Sponsor(
            name="SPE KSA Section",
            logo_path="Image/5909072811534257937.jpg",
            tier="Silver",
        ),
    ]


def seed_if_empty():
    if db.session.query(ClubIdentity.id).first() is None:
        db.session.add(
            ClubIdentity(
                name="نادي رواد الصناعة",
                mission="Connect students with factory leaders and hands-on industry work.",
                vision="A generation of engineers who build and lead local industry.",
                description="Industry Pioneers Club hosts plant visits, talks, and projects with manufacturing partners.",
            )
        )
        db.session.commit()
    ensure_sample_rows()
    repair_image_paths()


def ensure_sample_rows():
    titles = {row.title for row in Event.query}
    for event in _sample_events():
        if event.title not in titles:
            db.session.add(event)
    article_titles = {row.title for row in Article.query}
    for article in _sample_articles():
        if article.title not in article_titles:
            db.session.add(article)
    sponsor_names = {row.name for row in Sponsor.query}
    for sponsor in _sample_sponsors():
        if sponsor.name not in sponsor_names:
            db.session.add(sponsor)
    db.session.commit()


def _canonical_image(path, fallbacks, row_id):
    mapped = _IMAGE_FIXES.get(path, path)
    rel = _safe_static_rel(mapped)
    if rel:
        candidate = rel if rel.startswith("Image/") else "Image/" + rel.split("/")[-1]
        if _static_file_exists(candidate):
            return candidate
        if _static_file_exists(rel):
            return rel
    return fallbacks[(row_id or 0) % len(fallbacks)]


def repair_image_paths():
    changed = False
    for event in Event.query:
        fixed = _canonical_image(event.image_path, _EVENT_FALLBACKS, event.id)
        if fixed != event.image_path:
            event.image_path = fixed
            changed = True
    for article in Article.query:
        fixed = _canonical_image(article.image_path, _ARTICLE_FALLBACKS, article.id)
        if fixed != article.image_path:
            article.image_path = fixed
            changed = True
    for sponsor in Sponsor.query:
        fixed = _canonical_image(sponsor.logo_path, _SPONSOR_FALLBACKS, sponsor.id)
        if fixed != sponsor.logo_path:
            sponsor.logo_path = fixed
            changed = True
    if changed:
        db.session.commit()


def seed_demo_leader():
    # Dev-only demo credential. Remove or change before production.
    if db.session.query(User.id).filter_by(email="leader@club.com").first() is not None:
        return
    db.session.add(
        User(
            name="Admin",
            email="leader@club.com",
            password_hash=generate_password_hash("password123"),
            role="leader",
        )
    )
    db.session.commit()


def initialize_database():
    # One worker at a time. The next worker then sees the rows and skips seeding.
    # IntegrityError covers a unique-email race if the lock is unavailable.
    lock_path = os.path.join(app.instance_path, ".seed.lock")
    lock_file = open(lock_path, "a", encoding="utf-8")
    locked = False
    try:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            locked = True
        try:
            db.create_all()
            seed_if_empty()
            seed_demo_leader()
        except (IntegrityError, OperationalError):
            db.session.rollback()
    finally:
        if locked:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


with app.app_context():
    initialize_database()


def public_events():
    return (
        Event.query.filter_by(is_public=True).order_by(Event.date.desc()).all()
    )


def published_articles():
    return Article.query.order_by(Article.date_published.desc()).all()


def club_context():
    return {
        "club_identity": ClubIdentity.query.first(),
        "events": public_events(),
        "articles": published_articles(),
        "sponsors": Sponsor.query.order_by(Sponsor.id.asc()).all(),
    }


@app.get("/")
def home():
    return render_template("index.html", **club_context())


@app.get("/about")
def about_page():
    return render_template("about.html", club_identity=ClubIdentity.query.first())


@app.get("/events")
def events_page():
    now = datetime.now()
    events = public_events()
    return render_template(
        "events.html",
        events=events,
        upcoming=[event for event in events if event.date >= now],
        previous=[event for event in events if event.date < now],
    )


@app.get("/gazette")
def gazette_page():
    return render_template("gazette.html", articles=published_articles())


@app.get("/partners")
def partners_page():
    return render_template(
        "partners.html",
        sponsors=Sponsor.query.order_by(Sponsor.id.asc()).all(),
    )


@app.get("/visitor")
def visitor_portal():
    return render_template("visitor.html", events=public_events())


@app.post("/like_article/<int:article_id>")
def like_article(article_id):
    # Public endpoint: any client can target an article id (IDOR) and inflate
    # likes. Add auth, CAPTCHA, or rate limiting before production.
    article = db.session.get(Article, article_id)
    if article is None:
        abort(404)
    article.likes_count += 1
    db.session.commit()
    return jsonify({"id": article_id, "likes_count": article.likes_count})


def submitted():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return request.form


def text_field(data, key):
    value = data.get(key)
    if not isinstance(value, str):
        return ""
    return value.strip()


def invite_grants_member(invite_code):
    if not isinstance(invite_code, str):
        return False
    expected = os.environ.get("INVITE_CODE", "PIONEERS2026")
    return hmac.compare_digest(invite_code, expected)


def public_user(user):
    return {"id": user.id, "email": user.email, "role": user.role}


def landing_for(user):
    if user.role == "leader":
        return url_for("leader_dashboard")
    if user.role == "supervisor":
        return url_for("supervisor_dashboard")
    if user.role == "member":
        return url_for("member_profile")
    return url_for("home")


def prefers_json():
    if request.is_json:
        return True
    json_quality = request.accept_mimetypes["application/json"]
    html_quality = request.accept_mimetypes["text/html"]
    return json_quality > html_quality and json_quality > 0


# JSON and form login/register POSTs have no CSRF protection yet.
# A later iteration should add Flask-WTF/CSRF or token auth.
@app.get("/register")
def register_form():
    return jsonify(
        {
            "fields": {
                "name": "required",
                "email": "required",
                "password": "required",
                "invite_code": "optional",
            }
        }
    )


@app.post("/register")
def register():
    data = submitted()
    name = text_field(data, "name")
    email = text_field(data, "email")
    password = data.get("password")
    if not name or not email or not isinstance(password, str) or password == "":
        return jsonify({"error": "name, email, and password are required"}), 400
    if User.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "Email already registered"}), 409
    # Role comes from the invite code only. Ignore any client-supplied role.
    role = "member" if invite_grants_member(data.get("invite_code")) else "visitor"
    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Email already registered"}), 409
    return jsonify(public_user(user)), 201


@app.get("/login")
def login_form():
    return render_template("login.html")


@app.post("/login")
def login():
    data = submitted()
    email = text_field(data, "email")
    password = data.get("password")
    user = User.query.filter_by(email=email).first() if email else None
    candidate = password if isinstance(password, str) else ""
    password_hash = user.password_hash if user is not None else _LOGIN_DUMMY_HASH
    valid = check_password_hash(password_hash, candidate)
    if user is None or not valid:
        if request.is_json:
            return jsonify({"error": "Invalid email or password"}), 401
        return render_template("login.html", error="Invalid email or password"), 401
    login_user(user)
    if request.is_json:
        return jsonify(public_user(user))
    return redirect(landing_for(user))


@app.get("/logout")
@login_required
def logout():
    logout_user()
    if prefers_json():
        return jsonify({"message": "Logged out"})
    return redirect(url_for("home"))


@app.get("/dashboard")
@login_required
def dashboard():
    if current_user.role == "visitor":
        abort(403)
    return redirect(landing_for(current_user))


@app.get("/member/profile")
@role_required("member", "leader", "supervisor")
def member_profile():
    return render_template("dashboard.html")


@app.get("/leader/dashboard")
@role_required("leader", "supervisor")
def leader_dashboard():
    return render_template("leader-dashboard.html")


@app.get("/supervisor/dashboard")
@role_required("supervisor")
def supervisor_dashboard():
    return render_template("supervisor-dashboard.html")


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
