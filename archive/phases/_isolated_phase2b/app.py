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
    # Phase 2A: free-text committee assignment set by a leader. Nullable
    # because existing users have no committee yet.
    committee = db.Column(db.String(120), nullable=True)
    # Phase 2A: running total of points awarded via approved tasks.
    # Starts at 0; incremented atomically on leader approval (Phase 2B).
    points = db.Column(db.Integer, nullable=False, default=0)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    points = db.Column(db.Integer, nullable=False, default=0)
    deadline = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="قيد التنفيذ")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # Phase 2B: leader approval of member-completed tasks.
    # 'pending' | 'approved' | 'rejected'. Points awarded only on 'approved'.
    approval_status = db.Column(db.String(20), nullable=False, default="pending")
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    event = db.relationship("Event", lazy="joined")
    assigned_user = db.relationship(
        "User", lazy="joined", foreign_keys=[assigned_user_id]
    )


class ActivityLog(db.Model):
    """Phase 2B: audit trail + source of truth for points awarded.

    A UNIQUE index on (task_id, action) WHERE action='task_approved' prevents
    duplicate-award races.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    # 'task_approved' | 'task_rejected' | 'event_attended'
    points_delta = db.Column(db.Integer, nullable=False, default=0)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    user = db.relationship("User", lazy="joined", foreign_keys=[user_id])
    task = db.relationship("Task", lazy="joined", foreign_keys=[task_id])
    event = db.relationship("Event", lazy="joined", foreign_keys=[event_id])


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


def seed_demo_supervisor():
    # Dev-only demo credential. Remove or change before production.
    if db.session.query(User.id).filter_by(email="supervisor@club.com").first() is not None:
        return
    db.session.add(
        User(
            name="Academic Supervisor",
            email="supervisor@club.com",
            password_hash=generate_password_hash("password1234"),
            role="supervisor",
        )
    )
    db.session.commit()


def _ensure_sqlite_column(table, column, type_sql, default_sql="NULL"):
    """Add a column via ALTER TABLE only if it does not already exist.
    SQLite only; Postgres path would use ADD COLUMN IF NOT EXISTS."""
    rows = db.session.execute(db.text(f"PRAGMA table_info({table})")).fetchall()
    cols = {r[1] for r in rows}
    if column in cols:
        return False
    db.session.execute(db.text(
        f"ALTER TABLE {table} ADD COLUMN {column} {type_sql} DEFAULT {default_sql}"
    ))
    db.session.commit()
    return True


def _upgrade_schema():
    """Idempotent schema upgrades. Safe to run on every boot."""
    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        # Phase 2A: User gains committee + points.
        _ensure_sqlite_column("user", "committee", "VARCHAR(120)", "NULL")
        _ensure_sqlite_column("user", "points", "INTEGER NOT NULL", "0")
        # Phase 2B: Task gains approval columns.
        _ensure_sqlite_column("task", "approval_status", "VARCHAR(20) NOT NULL", "'pending'")
        _ensure_sqlite_column("task", "approved_by", "INTEGER", "NULL")
        _ensure_sqlite_column("task", "approved_at", "DATETIME", "NULL")
        # Phase 2B: unique partial index preventing duplicate task_approved
        # entries in ActivityLog. The activity_log table itself is created
        # by db.create_all() because the model is declared above.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_task_approved "
            "ON activity_log(task_id) WHERE action = 'task_approved'"
        ))
        db.session.commit()
    # Postgres path intentionally omitted for Phase 2A/2B isolated env.


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
            _upgrade_schema()
            seed_if_empty()
            seed_demo_leader()
            seed_demo_supervisor()
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


def _parse_iso_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _int_or_zero(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _task_dict(t):
    return {
        "id": t.id,
        "title": t.title,
        "points": t.points,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "status": t.status,
        "event_id": t.event_id,
        "assigned_user_id": t.assigned_user_id,
        "event": t.event.title if t.event else None,
        "member": t.assigned_user.name if t.assigned_user else None,
    }


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
    # Visitors have no privileged dashboard; direct them to the public portal.
    if user.role == "visitor":
        return url_for("visitor_portal")
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


@app.get("/signup")
def signup_form():
    return render_template("signup.html")


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
    # Every logged-in role has a landing page (visitors go to /visitor).
    # Member-only pages remain protected by role_required on their own routes.
    return redirect(landing_for(current_user))


POINTS_TARGET = 500


@app.get("/member/profile")
@role_required("member", "leader", "supervisor")
def member_profile():
    pts = int(current_user.points or 0)
    pct = min(100, round((pts / POINTS_TARGET) * 100)) if POINTS_TARGET else 0
    activity = (
        ActivityLog.query
        .filter_by(user_id=current_user.id)
        .order_by(ActivityLog.recorded_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "member-dashboard.html",
        points=pts,
        points_target=POINTS_TARGET,
        points_pct=pct,
        committee=current_user.committee,
        activity=activity,
    )


@app.get("/member/tasks")
@role_required("member", "leader", "supervisor")
def member_tasks():
    tasks = (
        Task.query
        .filter_by(assigned_user_id=current_user.id)
        .order_by(Task.created_at.desc())
        .all()
    )
    return render_template("tasks.html", tasks=tasks)


_ALLOWED_TASK_STATUSES = ("قيد التنفيذ", "مكتملة")


@app.post("/member/tasks/<int:task_id>/status")
@role_required("member", "leader", "supervisor")
def update_my_task_status(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if task.assigned_user_id != current_user.id:
        abort(403)
    new_status = text_field(submitted(), "status")
    if new_status not in _ALLOWED_TASK_STATUSES:
        return jsonify({"error": "حالة غير صالحة"}), 400
    task.status = new_status
    db.session.commit()
    return jsonify({"id": task.id, "status": task.status})


@app.get("/member/points-guide")
@role_required("member", "leader", "supervisor")
def points_guide():
    return render_template("points-guide.html")


@app.get("/member/leaderboard")
@role_required("member", "leader", "supervisor")
def member_leaderboard():
    members = User.query.filter_by(role="member").order_by(User.name.asc()).all()
    return render_template("leaderboard.html", members=members)


@app.route("/member/upload-article", methods=["GET", "POST"])
@role_required("member", "leader", "supervisor")
def upload_article():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        if not title or not category:
            return "يرجى إدخال عنوان المقال والتصنيف", 400

        if len(title) > 200 or len(category) > 120:
            return "العنوان أو التصنيف أطول من الحد المسموح", 400

        article = Article(
            title=title,
            author_name=current_user.name,
            author_sector=category,
            date_published=datetime.now(),
            likes_count=0,
        )

        db.session.add(article)
        db.session.commit()

        return redirect(url_for("upload_article"))

    return render_template("upload-article.html")


@app.get("/leader/dashboard")
@role_required("leader")
def leader_dashboard():
    articles = Article.query.order_by(Article.date_published.desc()).all()
    tasks = Task.query.order_by(Task.created_at.desc()).all()
    events = Event.query.order_by(Event.date.desc()).all()
    members = (
        User.query.filter(User.role.in_(["member", "leader"]))
        .order_by(User.name)
        .all()
    )
    sponsors = Sponsor.query.order_by(Sponsor.id.asc()).all()
    return render_template(
        "leader-dashboard.html",
        articles=articles,
        tasks=tasks,
        events=events,
        members=members,
        sponsors=sponsors,
    )


@app.get("/supervisor/stats")
@role_required("supervisor", "leader")
def supervisor_stats():
    now = datetime.now()
    public_q = Event.query.filter_by(is_public=True)
    total = public_q.count()
    completed = public_q.filter(Event.date < now).count()
    upcoming = total - completed
    pct = round((completed / total) * 100) if total else 0
    return jsonify({
        
        "events": {
            "total": total,
            "completed": completed,
            "upcoming": upcoming,
            "completion_pct": pct,
        },
        "articles": {"total": Article.query.count()},
        "sponsors": {"total": Sponsor.query.count()},
    })


@app.get("/leader/tasks")
@role_required("leader", "supervisor")
def list_tasks():
    tasks = Task.query.order_by(Task.created_at.desc()).all()
    return jsonify([_task_dict(t) for t in tasks])


@app.post("/leader/tasks")
@role_required("leader", "supervisor")
def create_task():
    data = submitted()
    title = text_field(data, "title")[:200]
    if not title:
        return jsonify({"error": "title required"}), 400
    deadline_raw = data.get("deadline")
    deadline = _parse_iso_date(deadline_raw) if deadline_raw else None
    if deadline_raw and deadline is None:
        return jsonify({"error": "deadline must be YYYY-MM-DD"}), 400
    task = Task(
        title=title,
        event_id=_int_or_none(data.get("event_id")),
        assigned_user_id=_int_or_none(data.get("assigned_user_id")),
        points=_int_or_zero(data.get("points")),
        deadline=deadline,
        status=(text_field(data, "status") or "قيد التنفيذ")[:30],
    )
    db.session.add(task)
    db.session.commit()
    return jsonify(_task_dict(task)), 201


@app.post("/leader/tasks/<int:task_id>")
@role_required("leader", "supervisor")
def update_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    data = submitted()
    title = text_field(data, "title")
    if title:
        task.title = title[:200]
    status = text_field(data, "status")
    if status:
        task.status = status[:30]
    if "deadline" in data:
        raw = data.get("deadline")
        if raw in (None, ""):
            task.deadline = None
        else:
            parsed = _parse_iso_date(raw)
            if parsed is None:
                return jsonify({"error": "deadline must be YYYY-MM-DD"}), 400
            task.deadline = parsed
    if "points" in data:
        task.points = _int_or_zero(data.get("points"))
    if "event_id" in data:
        task.event_id = _int_or_none(data.get("event_id"))
    if "assigned_user_id" in data:
        task.assigned_user_id = _int_or_none(data.get("assigned_user_id"))
    db.session.commit()
    return jsonify(_task_dict(task))


@app.post("/leader/tasks/<int:task_id>/delete")
@role_required("leader", "supervisor")
def delete_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    db.session.delete(task)
    db.session.commit()
    return jsonify({"deleted": task_id})


@app.post("/leader/tasks/<int:task_id>/approve")
@role_required("leader", "supervisor")
def approve_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if task.assigned_user_id is None:
        return jsonify({"error": "لا يمكن اعتماد مهمة غير مُسندة لعضو"}), 400
    if task.approval_status == "approved":
        return jsonify({"error": "المهمة معتمدة مسبقاً"}), 409
    # Atomic sequence: mark approved -> ledger insert (unique index guards race)
    # -> increment user points. If ledger insert fails due to the UNIQUE
    # partial index, we abort before touching points.
    task.approval_status = "approved"
    task.approved_by = current_user.id
    task.approved_at = datetime.now()
    log = ActivityLog(
        user_id=task.assigned_user_id,
        task_id=task.id,
        event_id=task.event_id,
        action="task_approved",
        points_delta=task.points,
    )
    db.session.add(log)
    try:
        db.session.flush()  # triggers unique index enforcement
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "تم اعتماد هذه المهمة من قبل"}), 409
    assignee = db.session.get(User, task.assigned_user_id)
    assignee.points = int(assignee.points or 0) + int(task.points or 0)
    db.session.commit()
    return jsonify({
        "task_id": task.id,
        "approval_status": task.approval_status,
        "assignee_points": assignee.points,
        "points_awarded": task.points,
    })


@app.post("/leader/tasks/<int:task_id>/reject")
@role_required("leader", "supervisor")
def reject_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if task.approval_status == "approved":
        return jsonify({"error": "لا يمكن رفض مهمة معتمدة"}), 409
    task.approval_status = "rejected"
    task.approved_by = current_user.id
    task.approved_at = datetime.now()
    if task.assigned_user_id is not None:
        log = ActivityLog(
            user_id=task.assigned_user_id,
            task_id=task.id,
            event_id=task.event_id,
            action="task_rejected",
            points_delta=0,
        )
        db.session.add(log)
    db.session.commit()
    return jsonify({"task_id": task.id, "approval_status": task.approval_status})


@app.post("/leader/sponsors")
@role_required("leader", "supervisor")
def create_sponsor():
    data = submitted()
    name = text_field(data, "name")[:200]
    tier = (text_field(data, "tier") or "Partner")[:50]
    logo_input = text_field(data, "logo_path")
    if not name:
        return jsonify({"error": "name required"}), 400
    rel = _safe_static_rel(logo_input) if logo_input else None
    if logo_input and (rel is None or not _static_file_exists(rel)):
        return jsonify(
            {"error": "logo_path must point to an existing file under static/"}
        ), 400
    sponsor = Sponsor(name=name, logo_path=rel, tier=tier)
    db.session.add(sponsor)
    db.session.commit()
    return jsonify({
        "id": sponsor.id,
        "name": sponsor.name,
        "logo_path": sponsor.logo_path,
        "tier": sponsor.tier,
    }), 201


@app.post("/leader/sponsors/<int:sponsor_id>/delete")
@role_required("leader", "supervisor")
def delete_sponsor(sponsor_id):
    sponsor = db.session.get(Sponsor, sponsor_id)
    if sponsor is None:
        abort(404)
    db.session.delete(sponsor)
    db.session.commit()
    return jsonify({"deleted": sponsor_id})


@app.post("/leader/members/<int:user_id>/committee")
@role_required("leader", "supervisor")
def set_member_committee(user_id):
    target = db.session.get(User, user_id)
    if target is None:
        abort(404)
    if target.role not in ("member", "leader"):
        return jsonify({"error": "لا يمكن تعيين لجنة إلا للأعضاء"}), 400
    committee = text_field(submitted(), "committee")[:120] or None
    target.committee = committee
    db.session.commit()
    return jsonify({"id": target.id, "committee": target.committee})


def _parse_iso_datetime(date_str, time_str):
    """Combine a YYYY-MM-DD date and optional HH:MM time into a datetime.
    Returns None if the date is missing or malformed. Time defaults to 00:00."""
    if not isinstance(date_str, str) or not date_str.strip():
        return None
    date_str = date_str.strip()
    time_str = (time_str or "").strip() or "00:00"
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


@app.post("/leader/events")
@role_required("leader", "supervisor")
def create_event():
    data = submitted()
    title = text_field(data, "title")[:200]
    if not title:
        return jsonify({"error": "يرجى إدخال عنوان الفعالية"}), 400
    date_raw = data.get("date")
    time_raw = data.get("time")
    event_dt = _parse_iso_datetime(date_raw, time_raw)
    if event_dt is None:
        return jsonify({"error": "التاريخ أو الوقت غير صالح (الصيغة YYYY-MM-DD و HH:MM)"}), 400
    raw_public = data.get("is_public")
    is_public = str(raw_public).lower() in ("1", "true", "on", "yes") if raw_public is not None else False
    logo_input = text_field(data, "image_path")
    image_path = None
    if logo_input:
        rel = _safe_static_rel(logo_input)
        if rel is None or not _static_file_exists(rel):
            return jsonify({"error": "image_path يجب أن يشير إلى ملف موجود داخل static/"}), 400
        image_path = rel
    event = Event(title=title, image_path=image_path, is_public=is_public, date=event_dt)
    db.session.add(event)
    db.session.commit()
    return jsonify({
        "id": event.id,
        "title": event.title,
        "date": event.date.isoformat(),
        "is_public": event.is_public,
        "image_path": event.image_path,
    }), 201


@app.post("/leader/events/<int:event_id>/delete")
@role_required("leader", "supervisor")
def delete_event(event_id):
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    # Clear FK on any task that referenced this event to avoid a dangling FK.
    for t in Task.query.filter_by(event_id=event_id).all():
        t.event_id = None
    db.session.delete(event)
    db.session.commit()
    return jsonify({"deleted": event_id})


@app.get("/supervisor/dashboard")
@role_required("supervisor")
def supervisor_dashboard():
    return render_template("supervisor-dashboard.html")


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
