import hmac
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from functools import wraps

try:
    import fcntl
except ImportError:  # Non-Unix interpreters have no file locks.
    fcntl = None

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for
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

logger = logging.getLogger(__name__)


def _writable_dir():
    """Return a directory the app can write to.

    - On a normal host (local dev, Render, etc.) `app.instance_path`
      lives inside the project tree and is writable → use it.
    - On a serverless host with a read-only package filesystem
      (Vercel, AWS Lambda) `app.instance_path` is read-only but `/tmp`
      is writable (and ephemeral per cold-start) → fall back to it.

    The result is cached on the Flask app so every subsequent call is
    cheap and consistent.
    """
    cached = getattr(app, "_writable_dir", None)
    if cached:
        return cached

    # Explicit override wins — ops can point at any writable mount.
    override = os.environ.get("INSTANCE_DIR", "").strip()
    candidates = []
    if override:
        candidates.append(override)
    candidates.append(app.instance_path)
    # Honor $TMPDIR, then fall back to /tmp (POSIX) or the system temp dir.
    candidates.append(os.environ.get("TMPDIR") or "/tmp")

    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            # Prove the dir really is writable with a one-byte probe.
            probe = os.path.join(path, ".write_probe")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("x")
            os.remove(probe)
            app._writable_dir = path
            return path
        except OSError:
            continue
    # Last resort — tempfile.gettempdir() always exists.
    import tempfile
    path = tempfile.gettempdir()
    app._writable_dir = path
    return path


def _database_uri():
    # DATABASE_URL overrides the local file (REQUIRED on serverless hosts
    # like Vercel where /tmp is wiped between invocations). Default is a
    # SQLite file in the writable dir — fine for local dev and single-worker
    # Render deployments; emphatically NOT fine on Vercel.
    uri = os.environ.get("DATABASE_URL", "").strip()
    if not uri:
        return "sqlite:///" + os.path.join(_writable_dir(), "club.db")
    # Normalize legacy Render / Heroku `postgres://` → `postgresql://`.
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    # Pin the psycopg (v3) driver explicitly. SQLAlchemy 2.x defaults to
    # psycopg2 when it sees `postgresql://`, which we don't ship. Rewriting
    # to `postgresql+psycopg://` tells SQLAlchemy to use psycopg v3 —
    # the driver pinned in requirements.txt.
    if uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
    return uri


def _engine_options():
    """Connection-pool settings tuned for serverless (short-lived workers
    on Vercel) + managed Postgres (Neon). pool_pre_ping drops dead
    connections after Neon's idle-timeout; pool_recycle keeps every
    connection younger than 5 minutes so the SSL handshake stays fresh.
    SQLite ignores these entirely."""
    uri = os.environ.get("DATABASE_URL", "")
    if not uri or uri.startswith("sqlite"):
        return {}
    return {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }


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
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_options()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# On when FLASK_ENV=production or Render sets RENDER=true. Off for local http.
app.config["SESSION_COOKIE_SECURE"] = _secure_session_cookie()
# Phase 5+: cap request body so an attacker cannot post gigabytes of
# file content. Article images are also validated against this below.
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # 5 MB

db = SQLAlchemy(app)


_ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def _is_allowed_image(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in _ALLOWED_IMAGE_EXTENSIONS


_IMAGE_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _save_event_image_upload(file_storage):
    """Persist an uploaded event cover into the EventImage table and
    return the virtual path ('event-image/<id>') to store on the Event
    row. Returns (path, None) on success or (None, error_message)
    on validation failure. Flask's MAX_CONTENT_LENGTH (5MB) already
    caps the request body, so no extra size check is needed here."""
    if file_storage is None or not file_storage.filename:
        return None, None
    if not _is_allowed_image(file_storage.filename):
        return None, "نوع الملف غير مدعوم. المسموح: JPG, JPEG, PNG, WEBP."
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    mime = _IMAGE_MIME_BY_EXT.get(ext, "application/octet-stream")
    blob = file_storage.read()
    if not blob:
        return None, "الملف المرفوع فارغ."
    img = EventImage(mime=mime, data=blob)
    db.session.add(img)
    db.session.flush()   # populate img.id without committing yet
    return f"event-image/{img.id}", None


def _save_article_image_upload(file_storage):
    """Same contract as _save_event_image_upload but writes to
    ArticleImage. Returns (virtual_path, None) on success,
    (None, None) when no file was supplied, (None, error) on
    validation failure."""
    if file_storage is None or not file_storage.filename:
        return None, None
    if not _is_allowed_image(file_storage.filename):
        return None, "نوع الملف غير مدعوم. المسموح: JPG, JPEG, PNG, WEBP."
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    mime = _IMAGE_MIME_BY_EXT.get(ext, "application/octet-stream")
    blob = file_storage.read()
    if not blob:
        return None, "الملف المرفوع فارغ."
    img = ArticleImage(mime=mime, data=blob)
    db.session.add(img)
    db.session.flush()
    return f"article-image/{img.id}", None


def _safe_static_rel(path):
    if not isinstance(path, str):
        return None
    rel = path.strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    return rel


_EVENT_IMAGE_PREFIX = "event-image/"
_ARTICLE_IMAGE_PREFIX = "article-image/"


@app.template_filter("static_image")
def static_image(path):
    # Virtual paths for uploaded images stored in the DB. The actual bytes
    # are served by serve_event_image / serve_article_image. We don't
    # verify existence here to keep this filter cheap on list pages — a
    # broken reference just renders a missing image, same as the legacy
    # static-file path.
    if isinstance(path, str):
        if path.startswith(_EVENT_IMAGE_PREFIX):
            tail = path[len(_EVENT_IMAGE_PREFIX):]
            if tail.isdigit():
                return url_for("serve_event_image", image_id=int(tail))
        if path.startswith(_ARTICLE_IMAGE_PREFIX):
            tail = path[len(_ARTICLE_IMAGE_PREFIX):]
            if tail.isdigit():
                return url_for("serve_article_image", image_id=int(tail))
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


@app.context_processor
def _inject_shared_chrome():
    """Make the club identity available to every template render so
    the shared footer include can reference it without each route
    having to pass it explicitly. Fails safe when the row doesn't
    exist yet (e.g. during the very first boot before seed data runs).
    """
    try:
        identity = ClubIdentity.query.first()
    except Exception:   # noqa: BLE001 — context processors must never raise
        identity = None
    # Phase 10: event_categories is a plain Python list (no DB roundtrip);
    # templates / inline scripts use it to render the "نوع الفعالية" select
    # and the matching chip filter without hard-coding the vocabulary.
    return {
        "club_identity": identity,
        "event_categories": EVENT_CATEGORIES,
    }


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    image_path = db.Column(db.String(300))
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    date = db.Column(db.DateTime, nullable=False)
    # Phase 6: optional registration-close datetime. NULL means "no deadline"
    # and the backend treats the event's own date as the effective cutoff.
    registration_deadline = db.Column(db.DateTime, nullable=True)
    # Phase 6: optional confirmed-seat capacity. NULL = unlimited (back-compat).
    capacity = db.Column(db.Integer, nullable=True)
    # Phase 6: free-text comma-separated tags used to match user interests.
    # Stored lowercase; empty string on legacy rows is treated as "no tags".
    tags = db.Column(db.String(300), nullable=True)
    # Phase 10: structured "نوع الفعالية" — one of EVENT_CATEGORIES. Nullable
    # for back-compat with pre-existing event rows that predate this column.
    category = db.Column(db.String(40), nullable=True)
    # Optional venue name + maps URL for the event details page.
    location_name = db.Column(db.String(200), nullable=True)
    location_url = db.Column(db.String(500), nullable=True)


# Phase 10: fixed vocabulary for the "نوع الفعالية" dropdown. The exact
# strings here MUST match the labels of the filter chips in events.html
# so the chip filter can compare against Event.category directly.
EVENT_CATEGORIES = ["ورش", "زيارات", "ملتقيات", "مسابقات"]


class EventImage(db.Model):
    """Binary storage for event cover images uploaded via the leader form.
    Kept in a separate table so list queries over Event don't pay the
    blob cost. One row per uploaded image; Event.image_path references
    it via the virtual path 'event-image/<id>' which the static_image
    filter resolves to /events/<id>/image."""
    id = db.Column(db.Integer, primary_key=True)
    mime = db.Column(db.String(60), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class ArticleImage(db.Model):
    """Binary storage for article cover images uploaded via the member
    upload form. Vercel's filesystem is read-only outside /tmp (which is
    ephemeral), so files written there vanish between invocations and
    the UI renders the empty placeholder. Storing bytes in the DB keeps
    uploaded images available across invocations.

    Article.image_path references it via the virtual path
    'article-image/<id>', resolved by the static_image filter to
    /articles/<id>/image."""
    id = db.Column(db.Integer, primary_key=True)
    mime = db.Column(db.String(60), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author_name = db.Column(db.String(120), nullable=False)
    author_sector = db.Column(db.String(120), nullable=False)
    date_published = db.Column(db.DateTime, nullable=False)
    likes_count = db.Column(db.Integer, nullable=False, default=0)
    image_path = db.Column(db.String(300))
    # Phase 4: approval workflow. Existing rows get 'approved' via migration
    # backfill so the public gazette stays unchanged for pre-existing content.
    status = db.Column(db.String(20), nullable=False, default="pending")
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    # Phase 4+: FK to the author's user row. Nullable because legacy rows
    # (seed data + pre-upgrade submissions) have no FK; approve_article
    # falls back to a name match for those.
    author_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    # Phase 5+: full article body (plain text, line breaks preserved via CSS).
    # Nullable so legacy seed articles without content remain readable.
    content = db.Column(db.Text, nullable=True)


class Sponsor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_path = db.Column(db.String(300))
    tier = db.Column(db.String(50), nullable=False)
    # Phase 9: flag separating historical ("شركاء سابقون") from active
    # ("رعاة حاليون") entries. Defaults to False (= current) so every
    # newly created sponsor from the leader dashboard is current.
    is_previous = db.Column(db.Boolean, nullable=False, default=False)


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
    # Phase 2A: free-text committee NAME. Kept as a denormalized mirror of
    # committee.name so every existing read path (templates, filters,
    # supervisor stats) keeps working without changes. Phase 7 writes the
    # FK below and syncs this column from Committee.name.
    committee = db.Column(db.String(120), nullable=True)
    # Phase 7: FK to the structured Committee row. Nullable → the member
    # is not assigned to any committee (default for newly registered users).
    committee_id = db.Column(db.Integer, db.ForeignKey("committee.id"), nullable=True)
    # Phase 2A: running total of points awarded via approved tasks.
    # Starts at 0; incremented atomically on leader approval (Phase 2B).
    points = db.Column(db.Integer, nullable=False, default=0)
    # Phase 6: comma-separated interest tags (lowercase, trimmed). NULL/""
    # means "no interests selected" and matches nothing.
    interests = db.Column(db.String(500), nullable=True)


class Committee(db.Model):
    """Phase 7: structured club committee. One leader (user_id, nullable
    before assignment), many members. A member joins via User.committee_id
    and User.committee (name mirror) is kept in sync on every write.

    Deleting a committee NEVER deletes member accounts — the delete path
    nulls out committee_id/committee on every assigned user first.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    description = db.Column(db.String(400), nullable=True)
    leader_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    leader = db.relationship("User", foreign_keys=[leader_user_id])
    members = db.relationship(
        "User",
        primaryjoin="User.committee_id == Committee.id",
        foreign_keys="User.committee_id",
        lazy="dynamic",
    )


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
    # Phase 5+: free-text role associated with this task assignment
    # (e.g. "منسق", "منفذ", "مراجع", "تصميم بوستر").
    role = db.Column(db.String(50), nullable=True)

    event = db.relationship("Event", lazy="joined")
    assigned_user = db.relationship(
        "User", lazy="joined", foreign_keys=[assigned_user_id]
    )


class ActivityLog(db.Model):
    """Phase 2B+: audit trail + source of truth for points awarded.

    UNIQUE partial indexes prevent duplicate-award races at the DB level:
      - (task_id)              WHERE action='task_approved'
      - (article_id)           WHERE action='article_approved'
      - (event_id, user_id)    WHERE action='event_attended'
      - (event_id, user_id)    WHERE action='event_organized'
      - (initiative_id)        WHERE action='initiative_approved'
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)
    # Phase 4+: track article-based point grants.
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=True)
    # Phase 5: track initiative-based point grants.
    initiative_id = db.Column(db.Integer, db.ForeignKey("initiative.id"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    # 'task_approved' | 'task_rejected' | 'event_attended' | 'event_organized'
    # | 'article_approved' | 'initiative_approved' | 'manual_award'
    points_delta = db.Column(db.Integer, nullable=False, default=0)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # Phase 8: free-form description used by manual awards given by a
    # committee leader. NULL for every row created by the automated
    # award paths (task approval, event attendance, etc.) so legacy rows
    # keep working untouched.
    description = db.Column(db.String(500), nullable=True)
    # Phase 8: user_id of the committee leader who awarded manual points.
    # NULL for every automated grant.
    awarded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    user = db.relationship("User", lazy="joined", foreign_keys=[user_id])
    task = db.relationship("Task", lazy="joined", foreign_keys=[task_id])
    event = db.relationship("Event", lazy="joined", foreign_keys=[event_id])
    article = db.relationship("Article", lazy="joined", foreign_keys=[article_id])
    initiative = db.relationship("Initiative", lazy="joined", foreign_keys=[initiative_id])


class MembershipRequest(db.Model):
    """Phase 4: public membership applications from /visitor.
    Leader-only review. Approval does NOT auto-create a user account."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    student_id = db.Column(db.String(50), nullable=False)
    major = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    reviewer = db.relationship("User", lazy="joined", foreign_keys=[reviewed_by])


class EventRegistration(db.Model):
    """Phase 4: public event signups from /visitor.
    Supports both anonymous (user_id=NULL) and logged-in registrations.
    Unique partial index on (event_id, user_id) WHERE user_id IS NOT NULL
    blocks logged-in duplicates at DB level; anonymous dedup is enforced
    at app level via (event_id, email).

    Phase 6: adds waitlist support. `is_waitlisted=False` means confirmed;
    `is_waitlisted=True` means queued. Historical rows default to False
    (confirmed) — the backfill never silently reclassifies them."""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    registered_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    is_waitlisted = db.Column(db.Boolean, nullable=False, default=False)
    waitlisted_at = db.Column(db.DateTime, nullable=True)

    event = db.relationship("Event", lazy="joined", foreign_keys=[event_id])
    user = db.relationship("User", lazy="joined", foreign_keys=[user_id])


class Notification(db.Model):
    """Phase 5: in-app notifications routed to specific users (typically
    leaders). Current triggers:
      - kind='task_submitted'  — fires when a member marks a task 'مكتملة'
    A UNIQUE partial index on (kind, task_id) WHERE kind='task_submitted'
    prevents duplicate notifications for repeat submissions of the same
    task before the leader has acted."""
    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)
    # Phase 6: notifications may reference an event (interest match /
    # waitlist promotion). Nullable for back-compat with existing rows.
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)
    message = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(300), nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    recipient = db.relationship("User", lazy="joined", foreign_keys=[recipient_user_id])
    task = db.relationship("Task", lazy="joined", foreign_keys=[task_id])
    event = db.relationship("Event", lazy="joined", foreign_keys=[event_id])


class Initiative(db.Model):
    """Phase 5: member-proposed initiatives. Points awarded on leader
    approval only. Submission alone does NOT award points.
    Unique partial index on (id) WHERE action='initiative_approved' in
    activity_log blocks duplicate awards even under race conditions."""
    id = db.Column(db.Integer, primary_key=True)
    proposer_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    # 'pending' | 'approved' | 'rejected'
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    proposer = db.relationship("User", lazy="joined", foreign_keys=[proposer_user_id])
    reviewer = db.relationship("User", lazy="joined", foreign_keys=[reviewed_by])


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
                vision=(
                    "أن يكون نادي رواد الصناعة بجامعة طيبة بيئة رائدة في تمكين "
                    "طلابها وطالباتها، وتعزيز الابتكار في مجالات التصنيع والتقنيات "
                    "الحديثة، بما يسهم في إعداد جيل جامعي متميز يقود الصناعة "
                    "الوطنية ويدعم مستهدفات رؤية المملكة."
                ),
                mission=(
                    "يسعى نادي رواد الصناعة إلى تمكين الطلاب والطالبات من اكتساب "
                    "المهارات الصناعية والتقنية، وتعزيز الابتكار في مجالات التصنيع "
                    "والتقنيات الحديثة، بما يدعم الصناعة الوطنية ويجهز الجيل "
                    "القادر لقيادة المستقبل الصناعي في المملكة."
                ),
                description=(
                    "نادي رواد الصناعة بجامعة طيبة — منصة طلابية تربط البيئة "
                    "الأكاديمية بالقطاع الصناعي من خلال الزيارات الميدانية، "
                    "والفعاليات، والمشاريع التطبيقية."
                ),
            )
        )
        db.session.commit()
    ensure_sample_rows()
    repair_image_paths()


def ensure_sample_rows():
    """One-shot seed for a brand-new database. Each table is seeded only
    while it is completely empty — once the leader has created, edited,
    or deleted any row the auto-seed is permanently disabled for that
    table, so a deleted sample row cannot be resurrected on cold start."""
    changed = False
    if Event.query.first() is None:
        for event in _sample_events():
            db.session.add(event)
        changed = True
    if Article.query.first() is None:
        for article in _sample_articles():
            db.session.add(article)
        changed = True
    if Sponsor.query.first() is None:
        for sponsor in _sample_sponsors():
            db.session.add(sponsor)
        changed = True
    if changed:
        db.session.commit()


def _canonical_image(path, fallbacks, row_id):
    # Virtual DB-blob paths (event-image/<id>, article-image/<id>) are
    # served by their own routes, not from static/. Leave them alone —
    # otherwise repair_image_paths() would overwrite freshly uploaded
    # images with a static fallback every cold start.
    if isinstance(path, str) and (
        path.startswith(_EVENT_IMAGE_PREFIX) or path.startswith(_ARTICLE_IMAGE_PREFIX)
    ):
        return path
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


def _ensure_sqlite_column(table, column, type_sql, default_sql="NULL"):
    """Phase 2: add a column via ALTER TABLE only if it does not already exist.
    SQLite only; Postgres path uses ADD COLUMN IF NOT EXISTS below."""
    rows = db.session.execute(db.text(f"PRAGMA table_info({table})")).fetchall()
    cols = {r[1] for r in rows}
    if column in cols:
        return False
    db.session.execute(db.text(
        f"ALTER TABLE {table} ADD COLUMN {column} {type_sql} DEFAULT {default_sql}"
    ))
    db.session.commit()
    return True


def _phase7_backfill_committees():
    """Phase 7: for each distinct non-empty User.committee string that
    does not yet have a Committee row, create one and point
    User.committee_id at it. Idempotent — re-runs produce no changes
    once the mapping is in place. Preserves existing accounts and
    their denormalized committee-name field."""
    distinct_names = {
        u.committee.strip()
        for u in User.query.filter(
            User.committee.isnot(None), User.committee != ""
        ).all()
        if isinstance(u.committee, str) and u.committee.strip()
    }
    created = False
    for name in distinct_names:
        existing = Committee.query.filter_by(name=name).first()
        if existing is None:
            db.session.add(Committee(name=name, description=None, leader_user_id=None))
            created = True
    if created:
        db.session.commit()
    # Second pass: link users whose committee_id is still NULL.
    needs_link = User.query.filter(
        User.committee.isnot(None),
        User.committee != "",
        User.committee_id.is_(None),
    ).all()
    if needs_link:
        name_to_id = {c.name: c.id for c in Committee.query.all()}
        for u in needs_link:
            cid = name_to_id.get((u.committee or "").strip())
            if cid is not None:
                u.committee_id = cid
        db.session.commit()


def _upgrade_schema():
    """Phase 2 + Phase 4: idempotent schema upgrades. Safe to run on every boot."""
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
        # entries in activity_log. The table itself is created by db.create_all().
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_task_approved "
            "ON activity_log(task_id) WHERE action = 'task_approved'"
        ))
        # Phase 4: Article gains status / reviewer columns.
        # Existing articles get status='approved' via DEFAULT so the public
        # gazette stays unchanged. New uploads from /member/upload-article
        # explicitly set status='pending'.
        _ensure_sqlite_column("article", "status", "VARCHAR(20) NOT NULL", "'approved'")
        _ensure_sqlite_column("article", "reviewed_by", "INTEGER", "NULL")
        _ensure_sqlite_column("article", "reviewed_at", "DATETIME", "NULL")
        # Phase 4+: Article FK to the author's user row + ActivityLog FK to
        # article, so article approvals can grant points through the same
        # audit trail that tasks use.
        _ensure_sqlite_column("article", "author_user_id", "INTEGER", "NULL")
        _ensure_sqlite_column("activity_log", "article_id", "INTEGER", "NULL")
        # Phase 4: unique partial index blocks logged-in duplicate event
        # registrations. Anonymous dedup is enforced at app level by email.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_registration_user "
            "ON event_registration(event_id, user_id) WHERE user_id IS NOT NULL"
        ))
        # Phase 4+: block duplicate article point grants.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_article_approved "
            "ON activity_log(article_id) WHERE action = 'article_approved'"
        ))
        # Phase 5: event attendance + organizer credit + initiatives.
        _ensure_sqlite_column("activity_log", "initiative_id", "INTEGER", "NULL")
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_event_attended "
            "ON activity_log(event_id, user_id) WHERE action = 'event_attended'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_event_organized "
            "ON activity_log(event_id, user_id) WHERE action = 'event_organized'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_initiative_approved "
            "ON activity_log(initiative_id) WHERE action = 'initiative_approved'"
        ))
        # Phase 5+: Task gains an optional role string (e.g. منسق/منفذ/مراجع).
        _ensure_sqlite_column("task", "role", "VARCHAR(50)", "NULL")
        # Phase 5+: notifications uniqueness — one unread task_submitted
        # notification per (task, recipient) pair; prevents duplicate pings
        # when a member toggles status repeatedly but still allows every
        # leader to receive their own copy.
        # An earlier version of this file created the index on (task_id) alone,
        # which prevented inserts for multiple leaders. Drop any stale version
        # before creating the correct one.
        db.session.execute(db.text("DROP INDEX IF EXISTS uq_notification_task_submitted"))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_task_submitted "
            "ON notification(task_id, recipient_user_id) "
            "WHERE kind = 'task_submitted' AND read_at IS NULL"
        ))
        # Phase 5+: Article gains optional full-text content.
        _ensure_sqlite_column("article", "content", "TEXT", "NULL")
        # Phase 6: smart notifications + countdown + capacity + waitlist.
        _ensure_sqlite_column("event", "registration_deadline", "DATETIME", "NULL")
        _ensure_sqlite_column("event", "capacity", "INTEGER", "NULL")
        _ensure_sqlite_column("event", "tags", "VARCHAR(300)", "NULL")
        _ensure_sqlite_column("user", "interests", "VARCHAR(500)", "NULL")
        # Phase 10: event.category (one of EVENT_CATEGORIES). Nullable so
        # pre-existing event rows (created before this column existed)
        # survive the migration without a forced value.
        _ensure_sqlite_column("event", "category", "VARCHAR(40)", "NULL")
        _ensure_sqlite_column("event", "location_name", "VARCHAR(200)", "NULL")
        _ensure_sqlite_column("event", "location_url", "VARCHAR(500)", "NULL")
        # EventRegistration gains waitlist flags. Existing rows get is_waitlisted=0
        # (confirmed) via the DEFAULT clause, so historical data is never
        # silently reclassified. waitlisted_at stays NULL for confirmed rows.
        _ensure_sqlite_column("event_registration", "is_waitlisted",
                              "BOOLEAN NOT NULL", "0")
        _ensure_sqlite_column("event_registration", "waitlisted_at",
                              "DATETIME", "NULL")
        # Notification gains an optional event_id FK so interest-match and
        # waitlist-promotion rows can link to the event they refer to.
        _ensure_sqlite_column("notification", "event_id", "INTEGER", "NULL")
        # Phase 7: structured committee + FK on user. The Committee table
        # itself is created by db.create_all(); here we only add the FK
        # column to the existing user table so previously-registered users
        # survive the migration.
        _ensure_sqlite_column("user", "committee_id", "INTEGER", "NULL")
        # Phase 7: backfill — turn each pre-existing distinct User.committee
        # string into a real Committee row and point committee_id at it.
        # Runs AFTER create_all so the committee table exists.
        _phase7_backfill_committees()
        # Phase 8: ActivityLog gains description (manual-award context) + the
        # committee leader who issued the award. Both nullable so every
        # legacy row survives unchanged.
        _ensure_sqlite_column("activity_log", "description", "VARCHAR(500)", "NULL")
        _ensure_sqlite_column("activity_log", "awarded_by_user_id", "INTEGER", "NULL")
        # Phase 9: sponsors gain an is_previous flag (default 0 = current,
        # so new rows created from the leader dashboard are "current"
        # sponsors). After adding the column we flip every existing row
        # to "previous" exactly once — gated by a marker file so re-runs
        # don't re-flip sponsors that a leader may have deliberately
        # created or marked as current afterwards.
        _ensure_sqlite_column("sponsor", "is_previous",
                              "BOOLEAN NOT NULL", "0")
        _marker = os.path.join(_writable_dir(), ".sponsor_backfill_v1")
        if not os.path.exists(_marker):
            db.session.execute(db.text("UPDATE sponsor SET is_previous = 1"))
            db.session.commit()
            try:
                open(_marker, "w", encoding="utf-8").close()
            except OSError:
                pass
        # Partial unique index: block duplicate event_match notifications
        # per (event, recipient) regardless of read status — one is enough.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_event_match "
            "ON notification(event_id, recipient_user_id) "
            "WHERE kind = 'event_match'"
        ))
        # Partial unique index: block duplicate waitlist-promotion
        # notifications per (event, recipient).
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_waitlist_promoted "
            "ON notification(event_id, recipient_user_id) "
            "WHERE kind = 'waitlist_promoted'"
        ))
        # Partial unique indexes: one active (pending) MembershipRequest
        # per student_id, and per lower(email) when email is provided.
        # Historical approved/rejected rows are unaffected.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_membership_pending_student "
            "ON membership_request(student_id) WHERE status = 'pending'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_membership_pending_email "
            "ON membership_request(lower(email)) "
            "WHERE status = 'pending' AND email IS NOT NULL"
        ))
        db.session.commit()
    elif dialect == "postgresql":
        db.session.execute(db.text(
            'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS committee VARCHAR(120)'
        ))
        db.session.execute(db.text(
            'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS points INTEGER NOT NULL DEFAULT 0'
        ))
        db.session.execute(db.text(
            "ALTER TABLE task ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) NOT NULL DEFAULT 'pending'"
        ))
        db.session.execute(db.text(
            "ALTER TABLE task ADD COLUMN IF NOT EXISTS approved_by INTEGER"
        ))
        db.session.execute(db.text(
            "ALTER TABLE task ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_task_approved "
            "ON activity_log(task_id) WHERE action = 'task_approved'"
        ))
        # Phase 4+: article points.
        db.session.execute(db.text(
            'ALTER TABLE article ADD COLUMN IF NOT EXISTS author_user_id INTEGER'
        ))
        db.session.execute(db.text(
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS article_id INTEGER"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_article_approved "
            "ON activity_log(article_id) WHERE action = 'article_approved'"
        ))
        # Phase 5: event attendance + organizer credit + initiatives.
        db.session.execute(db.text(
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS initiative_id INTEGER"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_event_attended "
            "ON activity_log(event_id, user_id) WHERE action = 'event_attended'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_event_organized "
            "ON activity_log(event_id, user_id) WHERE action = 'event_organized'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_initiative_approved "
            "ON activity_log(initiative_id) WHERE action = 'initiative_approved'"
        ))
        # Phase 5+
        db.session.execute(db.text(
            "ALTER TABLE task ADD COLUMN IF NOT EXISTS role VARCHAR(50)"
        ))
        db.session.execute(db.text("DROP INDEX IF EXISTS uq_notification_task_submitted"))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_task_submitted "
            "ON notification(task_id, recipient_user_id) "
            "WHERE kind = 'task_submitted' AND read_at IS NULL"
        ))
        # Phase 5+: Article gains optional full-text content.
        db.session.execute(db.text(
            "ALTER TABLE article ADD COLUMN IF NOT EXISTS content TEXT"
        ))
        # Phase 6: smart notifications + countdown + capacity + waitlist.
        db.session.execute(db.text(
            "ALTER TABLE event ADD COLUMN IF NOT EXISTS registration_deadline TIMESTAMP"
        ))
        db.session.execute(db.text(
            "ALTER TABLE event ADD COLUMN IF NOT EXISTS capacity INTEGER"
        ))
        db.session.execute(db.text(
            "ALTER TABLE event ADD COLUMN IF NOT EXISTS tags VARCHAR(300)"
        ))
        # Phase 10: structured event category — ورش / زيارات / ملتقيات / مسابقات.
        db.session.execute(db.text(
            "ALTER TABLE event ADD COLUMN IF NOT EXISTS category VARCHAR(40)"
        ))
        db.session.execute(db.text(
            "ALTER TABLE event ADD COLUMN IF NOT EXISTS location_name VARCHAR(200)"
        ))
        db.session.execute(db.text(
            "ALTER TABLE event ADD COLUMN IF NOT EXISTS location_url VARCHAR(500)"
        ))
        db.session.execute(db.text(
            'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS interests VARCHAR(500)'
        ))
        db.session.execute(db.text(
            "ALTER TABLE event_registration ADD COLUMN IF NOT EXISTS "
            "is_waitlisted BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        db.session.execute(db.text(
            "ALTER TABLE event_registration ADD COLUMN IF NOT EXISTS "
            "waitlisted_at TIMESTAMP"
        ))
        db.session.execute(db.text(
            "ALTER TABLE notification ADD COLUMN IF NOT EXISTS event_id INTEGER"
        ))
        # Phase 7: structured committees. Table created by create_all().
        db.session.execute(db.text(
            'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS committee_id INTEGER'
        ))
        _phase7_backfill_committees()
        # Phase 8: manual-award context on ActivityLog (nullable, back-compat).
        db.session.execute(db.text(
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS description VARCHAR(500)"
        ))
        db.session.execute(db.text(
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS awarded_by_user_id INTEGER"
        ))
        # Phase 9: sponsor.is_previous (default false). The one-shot
        # backfill flips every pre-existing row to true exactly once,
        # gated by a marker file so re-runs don't flip sponsors that a
        # leader may have deliberately marked current afterwards.
        db.session.execute(db.text(
            "ALTER TABLE sponsor ADD COLUMN IF NOT EXISTS is_previous "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # NB: on Postgres we deliberately DO NOT run the one-shot
        # UPDATE sponsor SET is_previous = TRUE. The SQLite→Postgres
        # migration script copies the already-correct is_previous value
        # for every row; running the UPDATE here would overwrite those
        # explicit values on the first boot after the migration.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_event_match "
            "ON notification(event_id, recipient_user_id) "
            "WHERE kind = 'event_match'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_waitlist_promoted "
            "ON notification(event_id, recipient_user_id) "
            "WHERE kind = 'waitlist_promoted'"
        ))
        # Membership request dedup: one active pending request per student
        # and per normalized email. Existing rows are untouched.
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_membership_pending_student "
            "ON membership_request(student_id) WHERE status = 'pending'"
        ))
        db.session.execute(db.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_membership_pending_email "
            "ON membership_request(lower(email)) "
            "WHERE status = 'pending' AND email IS NOT NULL"
        ))
        db.session.commit()


def initialize_database():
    # One worker at a time. The next worker then sees the rows and skips seeding.
    # IntegrityError covers a unique-email race if the lock is unavailable.
    # On a read-only filesystem the lock file cannot be created; in that
    # case we skip the file-lock (serverless hosts only ever have one
    # worker per invocation anyway) and still run the init path.
    lock_path = os.path.join(_writable_dir(), ".seed.lock")
    lock_file = None
    locked = False
    try:
        try:
            lock_file = open(lock_path, "a", encoding="utf-8")
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                locked = True
        except OSError as exc:
            logger.warning("seed lock unavailable (%s); proceeding without it", exc)
        try:
            db.create_all()
            _upgrade_schema()
            seed_if_empty()
        except (IntegrityError, OperationalError) as exc:
            db.session.rollback()
            logger.warning("initialize_database rolled back: %s", exc)
    finally:
        if lock_file is not None:
            if locked and fcntl is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            lock_file.close()


# Boot-time initialization. We wrap in try/except so a database that is
# briefly unreachable (serverless cold-start on an external Postgres,
# say) doesn't prevent the Flask app itself from importing — the first
# request will retry via the before-request hook below.
_db_ready = False
try:
    with app.app_context():
        initialize_database()
        _db_ready = True
except Exception as _db_init_exc:   # noqa: BLE001 — boot must not crash
    logger.exception("initialize_database failed at import: %s", _db_init_exc)


@app.before_request
def _ensure_db_ready():
    """Retry schema init once per cold start if boot-time init failed."""
    global _db_ready
    if _db_ready:
        return
    try:
        with app.app_context():
            initialize_database()
            _db_ready = True
    except Exception as exc:   # noqa: BLE001
        logger.exception("deferred initialize_database failed: %s", exc)


def public_events():
    return (
        Event.query.filter_by(is_public=True).order_by(Event.date.desc()).all()
    )


def published_articles():
    # Phase 4: only approved articles are publicly visible.
    return (
        Article.query
        .filter_by(status="approved")
        .order_by(Article.date_published.desc())
        .all()
    )


def club_context():
    # Home page intentionally lists only previous sponsors ("الشركاء
    # السابقون"); current partners live on /partners.
    return {
        "club_identity": ClubIdentity.query.first(),
        "events": public_events(),
        "articles": published_articles(),
        "sponsors": (
            Sponsor.query.filter_by(is_previous=True)
            .order_by(Sponsor.id.asc())
            .all()
        ),
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


@app.get("/events/<int:event_id>")
def event_detail_page(event_id):
    """Phase 6: public event detail page. Hosts the live countdown,
    capacity badge, and the register/waitlist/cancel actions."""
    event = db.session.get(Event, event_id)
    if event is None or not event.is_public:
        abort(404)
    status = _event_registration_snapshot(event)
    tags = _normalize_tag_list(event.tags)
    return render_template(
        "event-detail.html",
        event=event,
        status=status,
        tags=tags,
    )


@app.get("/gazette")
def gazette_page():
    return render_template("gazette.html", articles=published_articles())


@app.get("/gazette/<int:article_id>")
def gazette_article(article_id):
    """Phase 5+: public article detail page.
    Only approved articles are visible publicly."""
    article = db.session.get(Article, article_id)
    if article is None or article.status != "approved":
        abort(404)
    return render_template("gazette-article.html", article=article)


@app.get("/partners")
def partners_page():
    all_sponsors = Sponsor.query.order_by(Sponsor.id.asc()).all()
    return render_template(
        "partners.html",
        sponsors=all_sponsors,   # kept for back-compat with any legacy template
        current_sponsors=[s for s in all_sponsors if not s.is_previous],
        previous_sponsors=[s for s in all_sponsors if s.is_previous],
    )


@app.get("/events/<int:image_id>/image")
def serve_event_image(image_id):
    """Serve the binary bytes for an uploaded event cover. Backed by the
    EventImage table so uploads persist across Vercel invocations
    (serverless filesystems are ephemeral; the DB is not)."""
    img = db.session.get(EventImage, image_id)
    if img is None:
        abort(404)
    resp = Response(img.data, mimetype=img.mime)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.get("/articles/<int:image_id>/image")
def serve_article_image(image_id):
    """Serve binary bytes for an uploaded article cover. Mirror of
    serve_event_image — backed by the ArticleImage table so uploads
    survive Vercel's ephemeral filesystem."""
    img = db.session.get(ArticleImage, image_id)
    if img is None:
        abort(404)
    resp = Response(img.data, mimetype=img.mime)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.get("/visitor")
def visitor_portal():
    return render_template("visitor.html", events=public_events())


@app.post("/visitor/membership-request")
def submit_membership_request():
    """Phase 4: public membership application submission."""
    data = submitted()
    name = text_field(data, "name")[:120]
    student_id = text_field(data, "student_id")[:50]
    major = text_field(data, "major")[:120]
    email = normalize_email(text_field(data, "email"))[:120] or None
    reason = text_field(data, "reason")[:2000] or None
    if not name or not student_id or not major:
        return jsonify({"error": "الاسم والرقم الجامعي والتخصص مطلوبة"}), 400
    if email and not is_valid_email_format(email):
        return jsonify({"error": "صيغة البريد الإلكتروني غير صحيحة"}), 400
    # Block duplicate active applications by student_id OR email.
    duplicate_q = MembershipRequest.query.filter_by(status="pending")
    if email:
        from sqlalchemy import or_, func
        duplicate = duplicate_q.filter(
            or_(
                MembershipRequest.student_id == student_id,
                func.lower(MembershipRequest.email) == email,
            )
        ).first()
    else:
        duplicate = duplicate_q.filter_by(student_id=student_id).first()
    if duplicate is not None:
        return jsonify({"error": "يوجد طلب نشط بنفس البيانات قيد المراجعة بالفعل"}), 409
    mr = MembershipRequest(
        name=name,
        student_id=student_id,
        major=major,
        email=email,
        reason=reason,
        status="pending",
    )
    db.session.add(mr)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "يوجد طلب نشط بنفس البيانات قيد المراجعة بالفعل"}), 409
    return jsonify({"id": mr.id, "status": mr.status}), 201


@app.post("/visitor/events/<int:event_id>/register")
def register_for_event(event_id):
    """Phase 4 + Phase 6: public event registration with capacity + deadline
    + waitlist enforcement. Anonymous allowed. Clients can set
    `allow_waitlist=1` (JSON or form) to opt into the waitlist when full.
    Without that flag a full event returns 409 so the UI can prompt."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    if not event.is_public:
        return jsonify({"error": "الفعالية غير متاحة للتسجيل"}), 400
    if _registration_is_closed(event):
        return jsonify({
            "error": "التسجيل مغلق لهذه الفعالية",
            "code": "registration_closed",
        }), 400
    data = submitted()
    name = text_field(data, "name")[:120]
    email = text_field(data, "email")[:120]
    phone = text_field(data, "phone")[:40] or None
    allow_waitlist_raw = data.get("allow_waitlist")
    allow_waitlist = (
        str(allow_waitlist_raw).lower() in ("1", "true", "on", "yes")
        if allow_waitlist_raw is not None else False
    )
    if not name or not email:
        return jsonify({"error": "الاسم والبريد مطلوبان"}), 400
    user_id = current_user.id if current_user.is_authenticated else None

    # Lock the event row for the duration of this transaction so the
    # confirmed-count check and the INSERT are atomic. SQLite uses an
    # upgraded immediate transaction; Postgres uses SELECT ... FOR UPDATE.
    locked = _lock_event_for_registration(event_id)
    if locked is None:
        db.session.rollback()
        abort(404)

    if user_id is not None:
        dup = EventRegistration.query.filter_by(
            event_id=event_id, user_id=user_id
        ).first()
    else:
        dup = EventRegistration.query.filter_by(
            event_id=event_id, user_id=None, email=email
        ).first()
    if dup is not None:
        db.session.rollback()
        if dup.is_waitlisted:
            msg = "أنت في قائمة الانتظار لهذه الفعالية بالفعل"
        else:
            msg = "أنت مسجّل بالفعل في هذه الفعالية"
        return jsonify({"error": msg, "code": "duplicate"}), 409

    is_full = _event_is_full(locked)
    if is_full and not allow_waitlist:
        snapshot = _event_registration_snapshot(locked)
        db.session.rollback()
        return jsonify({
            "error": "الفعالية مكتملة. يمكنك الانضمام لقائمة الانتظار.",
            "code": "full",
            "status": snapshot,
        }), 409

    is_waitlisted = bool(is_full)
    waitlisted_at = datetime.now() if is_waitlisted else None
    reg = EventRegistration(
        event_id=event_id,
        user_id=user_id,
        name=name,
        email=email,
        phone=phone,
        is_waitlisted=is_waitlisted,
        waitlisted_at=waitlisted_at,
    )
    db.session.add(reg)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "أنت مسجّل بالفعل في هذه الفعالية",
            "code": "duplicate",
        }), 409

    snapshot = _event_registration_snapshot(locked)
    return jsonify({
        "id": reg.id,
        "event_id": event_id,
        "event_title": event.title,
        "is_waitlisted": reg.is_waitlisted,
        "status": snapshot,
    }), 201


@app.post("/visitor/events/<int:event_id>/cancel")
def cancel_event_registration(event_id):
    """Phase 6: cancel a confirmed or waitlisted registration. If a
    confirmed seat is freed and the event has a waitlist, promote the
    earliest waitlisted row inside the same transaction and notify the
    promoted registrant."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    data = submitted()
    email = text_field(data, "email")[:120]
    user_id = current_user.id if current_user.is_authenticated else None

    locked = _lock_event_for_registration(event_id)
    if locked is None:
        db.session.rollback()
        abort(404)

    if user_id is not None:
        reg = EventRegistration.query.filter_by(
            event_id=event_id, user_id=user_id
        ).first()
    else:
        if not email:
            db.session.rollback()
            return jsonify({"error": "البريد مطلوب لإلغاء التسجيل"}), 400
        reg = EventRegistration.query.filter_by(
            event_id=event_id, user_id=None, email=email
        ).first()

    if reg is None:
        db.session.rollback()
        return jsonify({"error": "لا يوجد تسجيل لإلغائه"}), 404

    was_confirmed = not reg.is_waitlisted
    db.session.delete(reg)

    promoted = None
    if was_confirmed:
        # Fill the freed seat with the earliest waitlisted registrant.
        promoted = (
            EventRegistration.query
            .filter_by(event_id=event_id, is_waitlisted=True)
            .order_by(EventRegistration.waitlisted_at.asc(),
                      EventRegistration.id.asc())
            .first()
        )
        if promoted is not None:
            promoted.is_waitlisted = False
            promoted.waitlisted_at = None

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "تعذر إلغاء التسجيل"}), 500

    if promoted is not None:
        _notify_waitlist_promotion(promoted, locked)

    return jsonify({
        "cancelled": True,
        "promoted_registration_id": promoted.id if promoted else None,
        "status": _event_registration_snapshot(locked),
    })


@app.get("/visitor/events/<int:event_id>/status")
def event_registration_status(event_id):
    """Public JSON endpoint used by the countdown / capacity badges on the
    public pages. Returns None for capacity when unlimited."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    if not event.is_public:
        abort(404)
    return jsonify(_event_registration_snapshot(event))


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


def _valid_http_url(v):
    """True iff v is a non-empty string starting with http:// or https://.
    Kept intentionally permissive so Google Maps, maps.app.goo.gl, and
    any plain maps URL pass without extra parsing."""
    return isinstance(v, str) and (v.startswith("http://") or v.startswith("https://"))


# Pragmatic email format check: one '@', at least one '.' in the domain,
# no whitespace. Kept deliberately permissive — we rely on delivery to
# flag deeper problems. No university-domain assumption.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(raw):
    """Trim surrounding whitespace and lowercase so comparisons are
    case-insensitive and resilient to accidental padding. Returns an
    empty string for falsy / non-string input."""
    if not isinstance(raw, str):
        return ""
    return raw.strip().lower()


def is_valid_email_format(value):
    return bool(_EMAIL_RE.match(value or ""))


# --------- Email delivery (Resend) ---------
# Config lives entirely in env vars so no secret ever lands in the repo:
#   RESEND_API_KEY         — API key from https://resend.com (required to send)
#   RESEND_FROM            — verified sender, e.g. "النادي <noreply@yourdomain.com>"
# When RESEND_API_KEY is unset we log and skip — callers must not claim
# success to users unless this returns True.
_RESEND_URL = "https://api.resend.com/emails"


def _email_enabled():
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("RESEND_FROM"))


def send_email(to_address, subject, html_body, text_body=None):
    """Send a transactional email via Resend. Returns True on success,
    False if the provider is unconfigured or the request fails. Never
    raises — callers decide how to surface failures."""
    if not to_address or not _email_enabled():
        return False
    api_key = os.environ["RESEND_API_KEY"]
    sender = os.environ["RESEND_FROM"]
    payload = {
        "from": sender,
        "to": [to_address],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _RESEND_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("Resend send failed for %s: %s", to_address, exc)
        return False


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
        "approval_status": t.approval_status,
        "role": t.role,
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
    email = normalize_email(text_field(data, "email"))
    password = data.get("password")
    if not name or not email or not isinstance(password, str) or password == "":
        return jsonify({"error": "الاسم والبريد الإلكتروني وكلمة المرور مطلوبة"}), 400
    if not is_valid_email_format(email):
        return jsonify({"error": "صيغة البريد الإلكتروني غير صحيحة"}), 400
    if User.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "هذا البريد الإلكتروني مسجل مسبقاً"}), 409
    # Role comes from either (a) a valid invite code, or (b) an existing
    # approved MembershipRequest for the same email. Any client-supplied
    # role is ignored.
    has_invite = invite_grants_member(data.get("invite_code"))
    has_approved_request = (
        MembershipRequest.query
        .filter_by(email=email, status="approved")
        .first()
        is not None
    )
    role = "member" if (has_invite or has_approved_request) else "visitor"
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
        return jsonify({"error": "هذا البريد الإلكتروني مسجل مسبقاً"}), 409
    email_sent = send_email(
        user.email,
        subject="تم إنشاء حسابك في نادي رواد الصناعة",
        html_body=(
            f"<p>مرحباً {user.name}،</p>"
            "<p>تم إنشاء حسابك بنجاح في نادي رواد الصناعة.</p>"
            "<p>بإمكانك الآن تسجيل الدخول واستكشاف الفعاليات والمحتوى.</p>"
            "<p>— إدارة النادي</p>"
        ),
        text_body=(
            f"مرحباً {user.name}،\n\n"
            "تم إنشاء حسابك بنجاح في نادي رواد الصناعة.\n"
            "بإمكانك الآن تسجيل الدخول واستكشاف الفعاليات والمحتوى.\n\n"
            "— إدارة النادي"
        ),
    )
    return jsonify({**public_user(user), "email_sent": email_sent}), 201


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


# Points are unlimited — no maximum cap. The former POINTS_TARGET=500
# fixed-cap display is removed; the member dashboard shows the raw total.
# ---- Points configuration (keep in sync with points-guide.html) ----
# Override via env for ops/tuning without touching code.
EVENT_ATTENDANCE_POINTS = int(os.environ.get("EVENT_ATTENDANCE_POINTS", "10"))
EVENT_ORGANIZER_POINTS = int(os.environ.get("EVENT_ORGANIZER_POINTS", "20"))
ARTICLE_POINTS = int(os.environ.get("ARTICLE_POINTS", "30"))
INITIATIVE_POINTS = int(os.environ.get("INITIATIVE_POINTS", "50"))


def _points_rules():
    """Single source of truth for both the backend and the guide template."""
    return {
        "event_attendance": EVENT_ATTENDANCE_POINTS,
        "event_organizer": EVENT_ORGANIZER_POINTS,
        "article": ARTICLE_POINTS,
        "initiative": INITIATIVE_POINTS,
    }


@app.get("/member/profile")
@role_required("member", "leader", "supervisor")
def member_profile():
    pts = int(current_user.points or 0)
    # Scoped to one member; newest-first. The template renders only the
    # first 4 rows by default and reveals the rest via the "عرض الكل" toggle.
    activity = (
        ActivityLog.query
        .filter_by(user_id=current_user.id)
        .order_by(ActivityLog.recorded_at.desc())
        .all()
    )
    return render_template(
        "member-dashboard.html",
        points=pts,
        committee=current_user.committee,
        activity=activity,
        # Phase 6: expose interests + choices for the picker UI.
        user_interests=_normalize_tag_list(current_user.interests),
        interest_choices=INTEREST_CHOICES,
        # Phase 8: list of committees this user leads so the dashboard
        # can conditionally show the "أعضاء اللجنة" card.
        led_committees=_committees_led_by(current_user),
    )


@app.post("/member/interests")
@role_required("member", "leader", "supervisor")
def update_my_interests():
    """Phase 6: update the current user's interests. Accepts either a JSON
    body with {"interests": [...]} or form data with repeated 'interests'
    keys. Empty list → NULL stored (back to 'no interests selected')."""
    data = submitted()
    raw = data.getlist("interests") if hasattr(data, "getlist") else data.get("interests")
    normalized = _normalize_tag_list(raw)
    current_user.interests = ", ".join(normalized) if normalized else None
    db.session.commit()
    return jsonify({
        "interests": normalized,
        "available": INTEREST_CHOICES,
    })


@app.get("/member/tasks")
@role_required("member", "leader", "supervisor")
def member_tasks():
    tasks = (
        Task.query
        .filter_by(assigned_user_id=current_user.id)
        .order_by(Task.created_at.desc())
        .all()
    )
    # Phase 2C: group by event (None bucket for tasks with no event).
    groups = {}
    group_order = []
    for t in tasks:
        key = t.event.title if t.event else None
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(t)
    grouped = [(k, groups[k]) for k in group_order]
    return render_template("tasks.html", tasks=tasks, grouped=grouped)


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
    was_completed = task.status == "مكتملة"
    task.status = new_status
    db.session.commit()
    # Notification: fire when a member first flips to مكتملة, provided
    # the task has not yet been approved/rejected.
    if (new_status == "مكتملة" and not was_completed
            and task.approval_status == "pending"):
        _notify_leaders_of_task_submission(task)
    return jsonify({"id": task.id, "status": task.status})


def _notify_leaders_of_task_submission(task):
    """Create one Notification row per leader for a newly-submitted task.
    The unique partial index on (task_id, recipient_user_id) WHERE
    kind='task_submitted' AND read_at IS NULL blocks duplicates per
    (task, leader) pair. Uses SAVEPOINTs so one duplicate does not
    discard other leaders' successful inserts."""
    leaders = User.query.filter_by(role="leader").all()
    msg = f"المهمة «{task.title[:80]}» بانتظار الاعتماد"
    link = url_for("leader_dashboard")
    for leader in leaders:
        try:
            with db.session.begin_nested():
                db.session.add(Notification(
                    recipient_user_id=leader.id,
                    kind="task_submitted",
                    task_id=task.id,
                    message=msg,
                    link=link,
                ))
        except IntegrityError:
            # Unread notification for this (task, leader) already exists.
            pass
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


@app.get("/notifications")
@login_required
def list_notifications():
    rows = (
        Notification.query
        .filter_by(recipient_user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(30)
        .all()
    )
    return jsonify({
        "unread_count": Notification.query.filter_by(
            recipient_user_id=current_user.id, read_at=None
        ).count(),
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "task_id": r.task_id,
                "message": r.message,
                "link": r.link,
                "read": r.read_at is not None,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for r in rows
        ],
    })


@app.post("/notifications/<int:nid>/read")
@login_required
def mark_notification_read(nid):
    n = db.session.get(Notification, nid)
    if n is None or n.recipient_user_id != current_user.id:
        abort(404)
    if n.read_at is None:
        n.read_at = datetime.now()
        db.session.commit()
    return jsonify({"id": nid, "read": True})


@app.post("/notifications/read-all")
@login_required
def mark_all_notifications_read():
    now = datetime.now()
    (Notification.query
        .filter_by(recipient_user_id=current_user.id, read_at=None)
        .update({"read_at": now}, synchronize_session=False))
    db.session.commit()
    return jsonify({"ok": True})


@app.get("/member/points-guide")
@role_required("member", "leader", "supervisor")
def points_guide():
    return render_template("points-guide.html", rules=_points_rules())


@app.get("/member/leaderboard")
@role_required("member", "leader", "supervisor")
def member_leaderboard():
    # Phase 4: rank by actual points (desc), name as tie-breaker.
    members = (
        User.query
        .filter_by(role="member")
        .order_by(User.points.desc(), User.name.asc())
        .all()
    )
    return render_template("leaderboard.html", members=members)


@app.route("/member/upload-article", methods=["GET", "POST"])
@role_required("member", "leader", "supervisor")
def upload_article():
    categories = [
        "الصناعة", "الابتكار", "التقنية",
        "ريادة الأعمال", "الاستدامة", "اللوجستيات", "السلامة",
    ]
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        content = request.form.get("content", "").strip()

        # Validate the three required text fields.
        if not title or not category or not content:
            return render_template(
                "upload-article.html",
                categories=categories,
                error="يرجى إدخال العنوان والتصنيف والمحتوى.",
                form={"title": title, "category": category, "content": content},
            ), 400
        if len(title) > 200 or len(category) > 120:
            return render_template(
                "upload-article.html",
                categories=categories,
                error="العنوان أو التصنيف أطول من الحد المسموح.",
                form={"title": title, "category": category, "content": content},
            ), 400
        if len(content) > 20000:
            return render_template(
                "upload-article.html",
                categories=categories,
                error="المحتوى طويل جداً (الحد الأقصى 20,000 حرف).",
                form={"title": title, "category": category, "content": content},
            ), 400

        # Optional image upload. Persist bytes in the DB so uploads survive
        # Vercel's ephemeral filesystem; the previous /tmp fallback silently
        # lost files between invocations.
        image_rel_path, img_err = _save_article_image_upload(request.files.get("image"))
        if img_err:
            return render_template(
                "upload-article.html",
                categories=categories,
                error=img_err,
                form={"title": title, "category": category, "content": content},
            ), 400

        article = Article(
            title=title,
            author_name=current_user.name,
            author_sector=category,
            date_published=datetime.now(),
            likes_count=0,
            # Phase 4: new submissions enter the moderation queue.
            status="pending",
            # Phase 4+: FK to the uploader so approval can award points
            # even if the display name later changes.
            author_user_id=current_user.id,
            # Phase 5+: full body + optional image.
            content=content,
            image_path=image_rel_path,
        )
        db.session.add(article)
        db.session.commit()
        return render_template(
            "upload-article.html",
            categories=categories,
            success="تم إرسال المقال للمراجعة. سيظهر في جريدة الصناعة بعد اعتماد القائد.",
        )

    return render_template("upload-article.html", categories=categories)


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
    # Phase 2D: tasks awaiting leader approval (member set status='مكتملة',
    # approval_status still 'pending', must be assigned to a user).
    pending_approval = (
        Task.query
        .filter(
            Task.status == "مكتملة",
            Task.approval_status == "pending",
            Task.assigned_user_id.isnot(None),
        )
        .order_by(Task.created_at.desc())
        .all()
    )
    # Phase 4: membership applications.
    membership_requests = (
        MembershipRequest.query
        .order_by(MembershipRequest.submitted_at.desc())
        .all()
    )
    membership_counts = {
        "pending": sum(1 for m in membership_requests if m.status == "pending"),
        "approved": sum(1 for m in membership_requests if m.status == "approved"),
        "rejected": sum(1 for m in membership_requests if m.status == "rejected"),
    }
    # Phase 4: per-event registration counts (dict event_id -> count).
    reg_counts = dict(
        db.session.query(EventRegistration.event_id, db.func.count(EventRegistration.id))
        .group_by(EventRegistration.event_id)
        .all()
    )
    # Phase 5+: full list of visitor registrations for the dashboard
    # section. Joined-load the event eagerly to avoid an N+1 query.
    visitor_registrations = (
        EventRegistration.query
        .order_by(EventRegistration.registered_at.desc())
        .all()
    )
    # Phase 5+: per-event task-completion summary (dict event_id -> {...}).
    event_progress = {}
    for ev in events:
        ev_tasks = Task.query.filter_by(event_id=ev.id)
        total = ev_tasks.count()
        if total == 0:
            event_progress[ev.id] = {
                "total": 0, "approved": 0, "pending": 0,
                "remaining": 0, "pct": 0,
            }
            continue
        approved = ev_tasks.filter_by(approval_status="approved").count()
        pending = ev_tasks.filter(
            Task.status == "مكتملة", Task.approval_status == "pending"
        ).count()
        event_progress[ev.id] = {
            "total": total,
            "approved": approved,
            "pending": pending,
            "remaining": total - approved - pending,
            "pct": round(100 * approved / total),
        }
    # Phase 5: pending initiatives awaiting leader approval.
    pending_initiatives = (
        Initiative.query
        .filter_by(status="pending")
        .order_by(Initiative.submitted_at.desc())
        .all()
    )
    # Phase 7: structured committees + the pool of unassigned members.
    committees = Committee.query.order_by(Committee.name.asc()).all()
    unassigned_members = [
        u for u in members
        if u.committee_id is None and u.role in ("member", "leader")
    ]
    return render_template(
        "leader-dashboard.html",
        articles=articles,
        tasks=tasks,
        events=events,
        members=members,
        sponsors=sponsors,
        pending_approval=pending_approval,
        membership_requests=membership_requests,
        membership_counts=membership_counts,
        reg_counts=reg_counts,
        visitor_registrations=visitor_registrations,
        event_progress=event_progress,
        pending_initiatives=pending_initiatives,
        committees=committees,
        unassigned_members=unassigned_members,
    )


def _compute_supervisor_stats():
    """Single source of truth for every supervisor metric. Used by both
    the JSON stats endpoint and the CSV report."""
    now = datetime.now()
    today = now.date()
    # An event is "ongoing" on its scheduled day (midnight → next midnight)
    # — covers daytime sessions regardless of start time granularity.
    public_q = Event.query.filter_by(is_public=True)
    events_total = Event.query.count()
    events_public = public_q.count()
    events_past = public_q.filter(db.func.date(Event.date) < today).count()
    events_ongoing = public_q.filter(db.func.date(Event.date) == today).count()
    events_upcoming = public_q.filter(db.func.date(Event.date) > today).count()

    tasks_total = Task.query.count()
    tasks_marked_done = Task.query.filter_by(status="مكتملة").count()
    tasks_approved = Task.query.filter_by(approval_status="approved").count()
    tasks_pending_review = Task.query.filter(
        Task.status == "مكتملة",
        Task.approval_status == "pending",
    ).count()
    tasks_rejected = Task.query.filter_by(approval_status="rejected").count()
    # "Incomplete" = anything not yet approved. Mirrors spec: approved vs pending vs incomplete.
    tasks_incomplete = tasks_total - tasks_approved - tasks_pending_review
    approved_pct = round(100 * tasks_approved / tasks_total) if tasks_total else 0

    # Overdue tasks (deadline passed, not approved). Deadline is a Date.
    overdue_q = Task.query.filter(
        Task.deadline.isnot(None),
        Task.deadline < today,
        Task.approval_status != "approved",
    )
    overdue_count = overdue_q.count()

    # Per-event completion (approved tasks / total tasks) for events with tasks.
    per_event = []
    for ev in Event.query.order_by(Event.date.desc()).all():
        ev_tasks = Task.query.filter_by(event_id=ev.id)
        total = ev_tasks.count()
        if total == 0:
            continue
        approved = ev_tasks.filter_by(approval_status="approved").count()
        pending = ev_tasks.filter(
            Task.status == "مكتملة", Task.approval_status == "pending"
        ).count()
        remaining = total - approved - pending
        completion_pct = round(100 * approved / total)
        ev_date = ev.date.date() if ev.date else None
        if ev_date is None:
            status = "upcoming"
        elif ev_date < today:
            status = "completed"
        elif ev_date == today:
            status = "ongoing"
        else:
            status = "upcoming"
        is_past = ev_date is not None and ev_date < today
        # Deadline-vs-completion flag: event date has passed but tasks aren't 100%.
        behind_schedule = is_past and completion_pct < 100
        per_event.append({
            "event_id": ev.id,
            "event_title": ev.title,
            "event_date": ev.date.isoformat() if ev.date else None,
            "status": status,
            "is_past": is_past,
            "behind_schedule": behind_schedule,
            "total": total,
            "approved": approved,
            "pending_review": pending,
            "remaining": remaining,
            "completion_pct": completion_pct,
        })

    # Committee aggregation. Uses actual User.committee + User.points
    # + tasks assigned to those users.
    committees = {}
    for u in User.query.filter(User.committee.isnot(None), User.committee != "").all():
        c = committees.setdefault(u.committee, {
            "name": u.committee,
            "members": 0,
            "tasks_total": 0,
            "tasks_approved": 0,
            "tasks_pending": 0,
            "tasks_incomplete": 0,
            "points_earned": 0,
        })
        c["members"] += 1
        c["points_earned"] += int(u.points or 0)
        user_tasks = Task.query.filter_by(assigned_user_id=u.id)
        ut_total = user_tasks.count()
        ut_approved = user_tasks.filter_by(approval_status="approved").count()
        ut_pending = user_tasks.filter(
            Task.status == "مكتملة", Task.approval_status == "pending"
        ).count()
        c["tasks_total"] += ut_total
        c["tasks_approved"] += ut_approved
        c["tasks_pending"] += ut_pending
        c["tasks_incomplete"] += ut_total - ut_approved - ut_pending
    for c in committees.values():
        c["completion_pct"] = (
            round(100 * c["tasks_approved"] / c["tasks_total"]) if c["tasks_total"] else 0
        )

    # ===== Alerts =====
    # Threshold for "low-completion committee": committees with ≥3 tasks and
    # under 50% approved. 3-task floor avoids flagging brand-new committees
    # with 0/1/2 tasks as "low".
    LOW_COMPLETION_THRESHOLD = 50
    LOW_COMPLETION_MIN_TASKS = 3
    alerts = []
    if overdue_count:
        alerts.append({
            "kind": "overdue_tasks",
            "severity": "high",
            "label": f"{overdue_count} مهمة متأخرة عن موعدها",
            "count": overdue_count,
        })
    behind_events = [e for e in per_event if e["behind_schedule"]]
    if behind_events:
        alerts.append({
            "kind": "events_behind_schedule",
            "severity": "high",
            "label": f"{len(behind_events)} فعالية انتهى موعدها قبل اكتمال مهامها",
            "count": len(behind_events),
        })
    if tasks_pending_review:
        alerts.append({
            "kind": "pending_review",
            "severity": "medium",
            "label": f"{tasks_pending_review} مهمة بانتظار مراجعة القائد",
            "count": tasks_pending_review,
        })
    low_committees = [
        c for c in committees.values()
        if c["tasks_total"] >= LOW_COMPLETION_MIN_TASKS
        and c["completion_pct"] < LOW_COMPLETION_THRESHOLD
    ]
    if low_committees:
        alerts.append({
            "kind": "low_completion_committees",
            "severity": "medium",
            "label": (
                f"{len(low_committees)} لجنة تحت نسبة إنجاز "
                f"{LOW_COMPLETION_THRESHOLD}%"
            ),
            "count": len(low_committees),
            "committees": [c["name"] for c in low_committees],
        })

    return {
        "events": {
            "total": events_total,
            "public_total": events_public,
            "completed": events_past,       # kept for backward compatibility
            "ongoing": events_ongoing,
            "upcoming": events_upcoming,
            "completion_pct": (
                round(100 * events_past / events_public) if events_public else 0
            ),  # % of public events whose date has passed — label clearly
        },
        "tasks": {
            "total": tasks_total,
            "marked_done": tasks_marked_done,
            "approved": tasks_approved,
            "pending_review": tasks_pending_review,
            "incomplete": tasks_incomplete,
            "rejected": tasks_rejected,
            "overdue": overdue_count,
            "approved_pct": approved_pct,
        },
        "articles": {
            "total": Article.query.count(),
            "approved": Article.query.filter_by(status="approved").count(),
        },
        "initiatives": {
            "total": Initiative.query.count(),
            "approved": Initiative.query.filter_by(status="approved").count(),
            "pending": Initiative.query.filter_by(status="pending").count(),
        },
        "sponsors": {"total": Sponsor.query.count()},
        "members": {
            "total": User.query.filter_by(role="member").count(),
            "with_points": User.query.filter(
                User.role == "member", User.points > 0
            ).count(),
            "total_points": int(db.session.query(
                db.func.coalesce(db.func.sum(User.points), 0)
            ).filter(User.role == "member").scalar() or 0),
        },
        "per_event": per_event,
        "committees": sorted(committees.values(), key=lambda c: -c["completion_pct"]),
        "alerts": alerts,
    }


@app.get("/supervisor/stats")
@role_required("supervisor", "leader")
def supervisor_stats():
    return jsonify(_compute_supervisor_stats())


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
        role=(text_field(data, "role") or None),
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
    if "role" in data:
        role_raw = text_field(data, "role")
        task.role = role_raw[:50] if role_raw else None
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


_SPONSOR_STATUS_VALUES = {"current", "previous"}


def _parse_sponsor_status(data):
    """Required 'حالة الراعي' field. Accepts 'current' or 'previous'
    (also tolerates boolean-ish 'is_previous=1/0' for legacy clients).
    Returns (is_previous_bool, error_message_or_None)."""
    raw = text_field(data, "status").lower()
    if raw in _SPONSOR_STATUS_VALUES:
        return (raw == "previous"), None
    legacy = data.get("is_previous")
    if legacy is not None:
        return (str(legacy).lower() in ("1", "true", "on", "yes", "previous")), None
    return None, "حالة الراعي مطلوبة (حالي أو سابق)"


@app.post("/leader/sponsors")
@role_required("leader", "supervisor")
def create_sponsor():
    data = submitted()
    name = text_field(data, "name")[:200]
    tier = (text_field(data, "tier") or "Partner")[:50]
    logo_input = text_field(data, "logo_path")
    if not name:
        return jsonify({"error": "name required"}), 400
    is_previous, status_err = _parse_sponsor_status(data)
    if status_err:
        return jsonify({"error": status_err}), 400
    rel = _safe_static_rel(logo_input) if logo_input else None
    if logo_input and (rel is None or not _static_file_exists(rel)):
        return jsonify(
            {"error": "logo_path must point to an existing file under static/"}
        ), 400
    sponsor = Sponsor(name=name, logo_path=rel, tier=tier, is_previous=is_previous)
    db.session.add(sponsor)
    db.session.commit()
    return jsonify({
        "id": sponsor.id,
        "name": sponsor.name,
        "logo_path": sponsor.logo_path,
        "tier": sponsor.tier,
        "is_previous": sponsor.is_previous,
    }), 201


@app.post("/leader/sponsors/<int:sponsor_id>/edit")
@role_required("leader", "supervisor")
def edit_sponsor(sponsor_id):
    sponsor = db.session.get(Sponsor, sponsor_id)
    if sponsor is None:
        abort(404)
    data = submitted()
    name = text_field(data, "name")[:200]
    if not name:
        return jsonify({"error": "name required"}), 400
    is_previous, status_err = _parse_sponsor_status(data)
    if status_err:
        return jsonify({"error": status_err}), 400
    tier = (text_field(data, "tier") or "Partner")[:50]
    if "logo_path" in data:
        logo_input = text_field(data, "logo_path")
        if logo_input == "":
            sponsor.logo_path = None
        else:
            rel = _safe_static_rel(logo_input)
            if rel is None or not _static_file_exists(rel):
                return jsonify(
                    {"error": "logo_path must point to an existing file under static/"}
                ), 400
            sponsor.logo_path = rel
    sponsor.name = name
    sponsor.tier = tier
    sponsor.is_previous = is_previous
    db.session.commit()
    return jsonify({
        "id": sponsor.id,
        "name": sponsor.name,
        "logo_path": sponsor.logo_path,
        "tier": sponsor.tier,
        "is_previous": sponsor.is_previous,
    })


@app.post("/leader/sponsors/<int:sponsor_id>/delete")
@role_required("leader", "supervisor")
def delete_sponsor(sponsor_id):
    sponsor = db.session.get(Sponsor, sponsor_id)
    if sponsor is None:
        abort(404)
    db.session.delete(sponsor)
    db.session.commit()
    return jsonify({"deleted": sponsor_id})


@app.post("/leader/membership-requests/<int:req_id>/approve")
@role_required("leader")
def approve_membership_request(req_id):
    """Phase 4: leader-only membership approval. Does NOT auto-create a user."""
    mr = db.session.get(MembershipRequest, req_id)
    if mr is None:
        abort(404)
    if mr.status != "pending":
        return jsonify({"error": "تم البت في هذا الطلب مسبقاً"}), 409
    mr.status = "approved"
    mr.reviewed_by = current_user.id
    mr.reviewed_at = datetime.now()
    # If the applicant already registered (same email), promote them to member
    # so their next login lands on /member/profile instead of the visitor view.
    promoted_user_id = None
    if mr.email:
        existing = User.query.filter_by(email=mr.email).first()
        if existing is not None and existing.role == "visitor":
            existing.role = "member"
            promoted_user_id = existing.id
    db.session.commit()
    email_sent = send_email(
        mr.email,
        subject="تم قبول طلب العضوية في نادي رواد الصناعة",
        html_body=(
            f"<p>مرحباً {mr.name}،</p>"
            "<p>يسعدنا إبلاغك بأنه <strong>تم قبول طلب العضوية</strong> في نادي رواد الصناعة.</p>"
            "<p>إذا كنت قد سجّلت حساباً بنفس البريد فقد تمّت ترقيته تلقائياً إلى عضو؛"
            " وإلا بإمكانك إنشاء حساب عبر صفحة التسجيل.</p>"
            "<p>— إدارة النادي</p>"
        ),
        text_body=(
            f"مرحباً {mr.name}،\n\n"
            "تم قبول طلب العضوية في نادي رواد الصناعة.\n"
            "إذا كنت قد سجّلت حساباً بنفس البريد فقد رُقّي تلقائياً إلى عضو؛"
            " وإلا بإمكانك إنشاء حساب عبر صفحة التسجيل.\n\n"
            "— إدارة النادي"
        ),
    ) if mr.email else False
    return jsonify({
        "id": mr.id,
        "status": mr.status,
        "promoted_user_id": promoted_user_id,
        "email_sent": email_sent,
        "note": "تمت الموافقة. إذا كان المتقدم مسجلاً بنفس البريد فسيُفعَّل كعضو تلقائياً، وإلا يمكنه التسجيل عبر /signup برمز الدعوة.",
    })


@app.post("/leader/membership-requests/<int:req_id>/reject")
@role_required("leader")
def reject_membership_request(req_id):
    mr = db.session.get(MembershipRequest, req_id)
    if mr is None:
        abort(404)
    if mr.status != "pending":
        return jsonify({"error": "تم البت في هذا الطلب مسبقاً"}), 409
    mr.status = "rejected"
    mr.reviewed_by = current_user.id
    mr.reviewed_at = datetime.now()
    db.session.commit()
    email_sent = send_email(
        mr.email,
        subject="تحديث بشأن طلب العضوية في نادي رواد الصناعة",
        html_body=(
            f"<p>مرحباً {mr.name}،</p>"
            "<p>نشكر اهتمامك بالانضمام إلى نادي رواد الصناعة."
            " بعد المراجعة، <strong>لم يتم قبول طلب العضوية</strong> في هذه المرحلة.</p>"
            "<p>يمكنك متابعة فعاليات النادي والتقدم مجدداً مستقبلاً.</p>"
            "<p>— إدارة النادي</p>"
        ),
        text_body=(
            f"مرحباً {mr.name}،\n\n"
            "نشكر اهتمامك بالانضمام إلى نادي رواد الصناعة.\n"
            "بعد المراجعة لم يتم قبول طلب العضوية في هذه المرحلة.\n"
            "يمكنك متابعة فعاليات النادي والتقدم مجدداً مستقبلاً.\n\n"
            "— إدارة النادي"
        ),
    ) if mr.email else False
    return jsonify({"id": mr.id, "status": mr.status, "email_sent": email_sent})


def _award_points(user_id, action, points, **ref_ids):
    """Atomically record a points grant in ActivityLog and bump User.points.

    `action` must match the pattern name used in the matching
    uq_activity_* partial index (e.g. 'event_attended').
    `ref_ids` can be any subset of {task_id, event_id, article_id,
    initiative_id} — exactly matching the FKs on ActivityLog.

    Returns a tuple (awarded_bool, user_or_None, new_total_or_None):
      - (True, user, new_total)   on first grant
      - (False, user, user.points) if the partial index blocks duplicate
      - (False, None, None)        if user_id is invalid

    Caller is responsible for the surrounding db.session.commit() OR
    passing commit=True via the context it controls — this function
    only flushes so that the IntegrityError on duplicates is raised
    synchronously and can be converted to a graceful rollback.
    """
    if user_id is None or points is None or points <= 0:
        return (False, None, None)
    user = db.session.get(User, user_id)
    if user is None:
        return (False, None, None)
    log = ActivityLog(
        user_id=user_id,
        action=action,
        points_delta=int(points),
        **ref_ids,
    )
    db.session.add(log)
    try:
        db.session.flush()
    except IntegrityError:
        # Partial-index violation = already awarded. Roll back the log row
        # ONLY; the caller may have other pending changes.
        db.session.rollback()
        # After rollback the user object is detached; re-fetch for the caller.
        user = db.session.get(User, user_id)
        return (False, user, int(user.points or 0) if user else None)
    user.points = int(user.points or 0) + int(points)
    return (True, user, int(user.points))


def _resolve_article_author(article):
    """Return the User who authored this article, or None.
    Prefer the stored FK (new submissions); fall back to a unique
    name match for legacy rows that pre-date the author_user_id column."""
    if article.author_user_id is not None:
        return db.session.get(User, article.author_user_id)
    if not article.author_name:
        return None
    matches = User.query.filter_by(name=article.author_name).limit(2).all()
    # Only award if the name match is unambiguous. Ambiguous → no award.
    return matches[0] if len(matches) == 1 else None


def _apply_article_approval(article_id):
    """Set article.status='approved' and persist reviewer stamp.
    Idempotent at the status level: safe to call after a rollback."""
    article = db.session.get(Article, article_id)
    if article is None:
        return None
    article.status = "approved"
    article.reviewed_by = current_user.id
    article.reviewed_at = datetime.now()
    return article


@app.post("/leader/articles/<int:article_id>/approve")
@role_required("leader")
def approve_article(article_id):
    """Phase 4+: leader-only article approval. Approved articles become
    visible on /gazette; others are hidden. Also awards ARTICLE_POINTS
    to the author (duplicate-safe via activity_log partial index)."""
    article = db.session.get(Article, article_id)
    if article is None:
        abort(404)
    if article.status == "approved":
        return jsonify({"error": "المقال معتمد مسبقاً"}), 409

    _apply_article_approval(article_id)
    author = _resolve_article_author(article)

    awarded, author, new_total = (False, author, None)
    if author is not None:
        awarded, author, new_total = _award_points(
            author.id, "article_approved", ARTICLE_POINTS, article_id=article.id
        )
        if not awarded and new_total is not None:
            # Duplicate award blocked by partial index — rollback cleared
            # the status change too, so reapply + commit.
            _apply_article_approval(article_id)

    db.session.commit()
    return jsonify({
        "id": article.id,
        "status": "approved",
        "author_user_id": author.id if author else None,
        "author_points": new_total,
        "points_awarded": ARTICLE_POINTS if awarded else 0,
    })


@app.post("/leader/events/<int:event_id>/attendance/<int:user_id>")
@role_required("leader", "supervisor")
def mark_event_attendance(event_id, user_id):
    """Phase 5: leader confirms a specific user attended a specific event
    and awards EVENT_ATTENDANCE_POINTS. Idempotent via partial index on
    activity_log(event_id, user_id) WHERE action='event_attended'."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    awarded, user, new_total = _award_points(
        user_id, "event_attended", EVENT_ATTENDANCE_POINTS, event_id=event_id
    )
    if not awarded and user is not None:
        db.session.commit()  # no-op commit for consistency
        return jsonify({
            "event_id": event_id,
            "user_id": user_id,
            "points_awarded": 0,
            "user_points": new_total,
            "note": "attendance already recorded",
        })
    db.session.commit()
    return jsonify({
        "event_id": event_id,
        "user_id": user_id,
        "points_awarded": EVENT_ATTENDANCE_POINTS,
        "user_points": new_total,
    })


@app.post("/leader/events/<int:event_id>/organizer/<int:user_id>")
@role_required("leader", "supervisor")
def credit_event_organizer(event_id, user_id):
    """Phase 5: leader credits a specific user as an organizer of a
    specific event and awards EVENT_ORGANIZER_POINTS. Idempotent via
    partial index on activity_log(event_id, user_id) WHERE
    action='event_organized'."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    awarded, user, new_total = _award_points(
        user_id, "event_organized", EVENT_ORGANIZER_POINTS, event_id=event_id
    )
    if not awarded and user is not None:
        db.session.commit()
        return jsonify({
            "event_id": event_id,
            "user_id": user_id,
            "points_awarded": 0,
            "user_points": new_total,
            "note": "organizer credit already recorded",
        })
    db.session.commit()
    return jsonify({
        "event_id": event_id,
        "user_id": user_id,
        "points_awarded": EVENT_ORGANIZER_POINTS,
        "user_points": new_total,
    })


# ---- Initiatives (Phase 5) ----
@app.get("/member/initiatives")
@role_required("member", "leader", "supervisor")
def initiatives_page():
    """Member page: submit a new initiative + see one's own history."""
    mine = (
        Initiative.query
        .filter_by(proposer_user_id=current_user.id)
        .order_by(Initiative.submitted_at.desc())
        .all()
    )
    return render_template(
        "initiatives.html",
        mine=mine,
        points_value=INITIATIVE_POINTS,
    )


@app.post("/member/initiatives")
@role_required("member", "leader", "supervisor")
def submit_initiative():
    """Phase 5: member proposes an initiative. No points on submission —
    points only on leader approval. Accepts both JSON (API clients) and
    form-encoded (HTML form on /member/initiatives)."""
    data = submitted()
    title = text_field(data, "title")[:200]
    description = text_field(data, "description")[:2000] or None
    if not title:
        if prefers_json():
            return jsonify({"error": "عنوان المبادرة مطلوب"}), 400
        return redirect(url_for("initiatives_page"))
    initiative = Initiative(
        proposer_user_id=current_user.id,
        title=title,
        description=description,
        status="pending",
    )
    db.session.add(initiative)
    db.session.commit()
    if prefers_json():
        return jsonify({
            "id": initiative.id,
            "status": initiative.status,
            "proposer_user_id": initiative.proposer_user_id,
        }), 201
    return redirect(url_for("initiatives_page"))


@app.get("/leader/initiatives")
@role_required("leader", "supervisor")
def list_initiatives():
    rows = Initiative.query.order_by(Initiative.submitted_at.desc()).all()
    return jsonify([
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "status": r.status,
            "proposer_user_id": r.proposer_user_id,
            "proposer_name": r.proposer.name if r.proposer else None,
            "submitted_at": r.submitted_at.strftime("%Y-%m-%d %H:%M"),
        }
        for r in rows
    ])


@app.post("/leader/initiatives/<int:initiative_id>/approve")
@role_required("leader")
def approve_initiative(initiative_id):
    """Phase 5: leader approves an initiative; proposer gets
    INITIATIVE_POINTS once. Idempotent via activity_log partial index."""
    initiative = db.session.get(Initiative, initiative_id)
    if initiative is None:
        abort(404)
    if initiative.status == "approved":
        return jsonify({"error": "المبادرة معتمدة مسبقاً"}), 409

    initiative.status = "approved"
    initiative.reviewed_by = current_user.id
    initiative.reviewed_at = datetime.now()

    awarded, user, new_total = _award_points(
        initiative.proposer_user_id,
        "initiative_approved",
        INITIATIVE_POINTS,
        initiative_id=initiative.id,
    )
    if not awarded and user is not None:
        # Duplicate blocked — rollback erased the status change; reapply.
        fresh = db.session.get(Initiative, initiative_id)
        fresh.status = "approved"
        fresh.reviewed_by = current_user.id
        fresh.reviewed_at = datetime.now()
        db.session.commit()
        return jsonify({
            "id": initiative_id,
            "status": "approved",
            "points_awarded": 0,
            "proposer_points": new_total,
            "note": "points previously awarded",
        })

    db.session.commit()
    return jsonify({
        "id": initiative.id,
        "status": initiative.status,
        "proposer_user_id": initiative.proposer_user_id,
        "proposer_points": new_total,
        "points_awarded": INITIATIVE_POINTS if awarded else 0,
    })


@app.post("/leader/initiatives/<int:initiative_id>/reject")
@role_required("leader")
def reject_initiative(initiative_id):
    initiative = db.session.get(Initiative, initiative_id)
    if initiative is None:
        abort(404)
    if initiative.status == "rejected":
        return jsonify({"error": "المبادرة مرفوضة مسبقاً"}), 409
    initiative.status = "rejected"
    initiative.reviewed_by = current_user.id
    initiative.reviewed_at = datetime.now()
    db.session.commit()
    return jsonify({"id": initiative.id, "status": initiative.status})


@app.post("/leader/articles/<int:article_id>/reject")
@role_required("leader")
def reject_article(article_id):
    article = db.session.get(Article, article_id)
    if article is None:
        abort(404)
    if article.status == "rejected":
        return jsonify({"error": "المقال مرفوض مسبقاً"}), 409
    article.status = "rejected"
    article.reviewed_by = current_user.id
    article.reviewed_at = datetime.now()
    db.session.commit()
    return jsonify({"id": article.id, "status": article.status})


@app.get("/leader/events/<int:event_id>/registrations")
@role_required("leader", "supervisor")
def list_event_registrations(event_id):
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    regs = (
        EventRegistration.query
        .filter_by(event_id=event_id)
        .order_by(EventRegistration.registered_at.desc())
        .all()
    )
    return jsonify({
        "event_id": event_id,
        "event_title": event.title,
        "count": len(regs),
        "registrations": [
            {
                "id": r.id,
                "name": r.name,
                "email": r.email,
                "phone": r.phone,
                "user_id": r.user_id,
                "registered_at": r.registered_at.strftime("%Y-%m-%d %H:%M"),
            }
            for r in regs
        ],
    })


def _committee_dict(c):
    leader = db.session.get(User, c.leader_user_id) if c.leader_user_id else None
    members = User.query.filter_by(committee_id=c.id).order_by(User.name.asc()).all()
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "leader": (
            {"id": leader.id, "name": leader.name, "email": leader.email}
            if leader else None
        ),
        "members": [
            {"id": u.id, "name": u.name, "email": u.email,
             "role": u.role, "points": int(u.points or 0),
             "is_leader": (u.id == c.leader_user_id)}
            for u in members
        ],
        "members_count": len(members),
    }


def _assign_user_to_committee(user, committee):
    """Move `user` into `committee` (or clear if None). Keeps the
    denormalized User.committee name in sync. If `user` was previously
    the leader of another committee, that committee's leader_user_id
    is cleared so no stale leader pointer survives."""
    if user is None:
        return
    # If this user leads some OTHER committee, strip that leader pointer
    # before moving them so a committee is never left with a leader who
    # isn't a member of it.
    if user.committee_id and (committee is None or committee.id != user.committee_id):
        old = db.session.get(Committee, user.committee_id)
        if old is not None and old.leader_user_id == user.id:
            old.leader_user_id = None
    if committee is None:
        user.committee_id = None
        user.committee = None
    else:
        user.committee_id = committee.id
        user.committee = committee.name


def _eligible_member(user):
    """Only registered members or leaders may be assigned. Visitors and
    supervisors are not committee members."""
    return user is not None and user.role in ("member", "leader")


@app.get("/leader/committees")
@role_required("leader", "supervisor")
def list_committees():
    rows = Committee.query.order_by(Committee.name.asc()).all()
    unassigned = (
        User.query
        .filter(User.role.in_(("member", "leader")), User.committee_id.is_(None))
        .order_by(User.name.asc())
        .all()
    )
    return jsonify({
        "committees": [_committee_dict(c) for c in rows],
        "unassigned_members": [
            {"id": u.id, "name": u.name, "email": u.email, "role": u.role}
            for u in unassigned
        ],
    })


@app.get("/leader/committees/<int:committee_id>")
@role_required("leader", "supervisor")
def get_committee(committee_id):
    c = db.session.get(Committee, committee_id)
    if c is None:
        abort(404)
    return jsonify(_committee_dict(c))


@app.post("/leader/committees")
@role_required("leader", "supervisor")
def create_committee():
    data = submitted()
    name = text_field(data, "name")[:120]
    description = text_field(data, "description")[:400] or None
    leader_user_id = _int_or_none(data.get("leader_user_id"))
    if not name:
        return jsonify({"error": "اسم اللجنة مطلوب"}), 400
    if Committee.query.filter_by(name=name).first() is not None:
        return jsonify({"error": "يوجد لجنة بنفس الاسم"}), 409
    committee = Committee(name=name, description=description, leader_user_id=None)
    db.session.add(committee)
    try:
        db.session.flush()  # need committee.id for the leader assignment below
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "يوجد لجنة بنفس الاسم"}), 409
    if leader_user_id is not None:
        leader = db.session.get(User, leader_user_id)
        if not _eligible_member(leader):
            db.session.rollback()
            return jsonify({"error": "القائد يجب أن يكون عضواً مسجلاً"}), 400
        _assign_user_to_committee(leader, committee)
        committee.leader_user_id = leader.id
    db.session.commit()
    return jsonify(_committee_dict(committee)), 201


@app.post("/leader/committees/<int:committee_id>/edit")
@role_required("leader", "supervisor")
def edit_committee(committee_id):
    c = db.session.get(Committee, committee_id)
    if c is None:
        abort(404)
    data = submitted()
    if "name" in data:
        new_name = text_field(data, "name")[:120]
        if not new_name:
            return jsonify({"error": "اسم اللجنة مطلوب"}), 400
        if new_name != c.name:
            dup = Committee.query.filter_by(name=new_name).first()
            if dup is not None and dup.id != c.id:
                return jsonify({"error": "يوجد لجنة بنفس الاسم"}), 409
            c.name = new_name
            # Sync the denormalized name on every member of this committee.
            for u in User.query.filter_by(committee_id=c.id).all():
                u.committee = new_name
    if "description" in data:
        c.description = text_field(data, "description")[:400] or None
    db.session.commit()
    return jsonify(_committee_dict(c))


@app.post("/leader/committees/<int:committee_id>/delete")
@role_required("leader", "supervisor")
def delete_committee(committee_id):
    """Delete the committee. Does NOT delete member accounts — just
    clears their committee_id + committee name so they return to the
    unassigned pool and can be reassigned later."""
    c = db.session.get(Committee, committee_id)
    if c is None:
        abort(404)
    affected = User.query.filter_by(committee_id=c.id).all()
    for u in affected:
        u.committee_id = None
        u.committee = None
    db.session.delete(c)
    db.session.commit()
    return jsonify({
        "deleted": committee_id,
        "members_detached": len(affected),
    })


@app.post("/leader/committees/<int:committee_id>/add-member")
@role_required("leader", "supervisor")
def committee_add_member(committee_id):
    c = db.session.get(Committee, committee_id)
    if c is None:
        abort(404)
    user_id = _int_or_none(submitted().get("user_id"))
    user = db.session.get(User, user_id) if user_id else None
    if not _eligible_member(user):
        return jsonify({"error": "يُسمح فقط بإضافة أعضاء مسجلين"}), 400
    if user.committee_id == c.id:
        return jsonify({"error": "العضو موجود بالفعل في هذه اللجنة"}), 409
    _assign_user_to_committee(user, c)
    db.session.commit()
    return jsonify({
        "committee_id": c.id,
        "member": {"id": user.id, "name": user.name, "email": user.email},
    })


@app.post("/leader/committees/<int:committee_id>/remove-member")
@role_required("leader", "supervisor")
def committee_remove_member(committee_id):
    c = db.session.get(Committee, committee_id)
    if c is None:
        abort(404)
    user_id = _int_or_none(submitted().get("user_id"))
    user = db.session.get(User, user_id) if user_id else None
    if user is None or user.committee_id != c.id:
        return jsonify({"error": "العضو ليس في هذه اللجنة"}), 404
    # If they were the leader, strip the leader pointer first.
    if c.leader_user_id == user.id:
        c.leader_user_id = None
    _assign_user_to_committee(user, None)
    db.session.commit()
    return jsonify({"committee_id": c.id, "removed_user_id": user.id})


@app.post("/leader/committees/<int:committee_id>/set-leader")
@role_required("leader", "supervisor")
def committee_set_leader(committee_id):
    """Promote one of the committee's members to leader. Pass user_id=0
    (or omit) to clear the leader pointer."""
    c = db.session.get(Committee, committee_id)
    if c is None:
        abort(404)
    user_id = _int_or_none(submitted().get("user_id"))
    if not user_id:
        c.leader_user_id = None
        db.session.commit()
        return jsonify({"committee_id": c.id, "leader_user_id": None})
    user = db.session.get(User, user_id)
    if not _eligible_member(user):
        return jsonify({"error": "القائد يجب أن يكون عضواً مسجلاً"}), 400
    # If they aren't already in this committee, pull them in first.
    if user.committee_id != c.id:
        _assign_user_to_committee(user, c)
    c.leader_user_id = user.id
    db.session.commit()
    return jsonify({"committee_id": c.id, "leader_user_id": user.id})


@app.post("/leader/members/<int:user_id>/committee")
@role_required("leader", "supervisor")
def set_member_committee(user_id):
    """Legacy endpoint — preserved for backward compatibility with the
    previous "committee as free-text string" workflow. Accepts a
    committee NAME; if the committee doesn't exist, one is created on
    the fly. Empty string / omitted → unassign."""
    target = db.session.get(User, user_id)
    if target is None:
        abort(404)
    if not _eligible_member(target):
        return jsonify({"error": "لا يمكن تعيين لجنة إلا للأعضاء"}), 400
    name = text_field(submitted(), "committee")[:120] or None
    if name is None:
        _assign_user_to_committee(target, None)
    else:
        committee = Committee.query.filter_by(name=name).first()
        if committee is None:
            committee = Committee(name=name)
            db.session.add(committee)
            db.session.flush()
        _assign_user_to_committee(target, committee)
    db.session.commit()
    return jsonify({"id": target.id, "committee": target.committee})


# ===========================================================
# Phase 8 — Committee Leader Management (self-service)
#
# A "committee leader" is any logged-in user whose user.id matches at
# least one Committee.leader_user_id. They get a scoped dashboard page
# where they can:
#   - view their committee's members
#   - add existing registered members (visitors are rejected)
#   - manually award points with a task description
#
# Club leaders + supervisors retain full access and can manage any committee.
# All checks are enforced server-side on every request.
# ===========================================================

def _committees_led_by(user):
    """Return the list of Committee rows this user leads. Empty for
    non-leaders. Club leader / supervisor roles are not auto-promoted —
    they must still be the designated leader of a committee to appear
    here (they have the main dashboard for cross-committee work)."""
    if user is None or not user.is_authenticated:
        return []
    return (
        Committee.query
        .filter_by(leader_user_id=user.id)
        .order_by(Committee.name.asc())
        .all()
    )


def _is_club_admin(user):
    return (
        user is not None
        and user.is_authenticated
        and getattr(user, "role", None) in ("leader", "supervisor")
    )


def _get_managed_committee(committee_id):
    """Return (committee, error_response_tuple). The caller must either
    hold a leader_user_id pointer at this committee OR be a club admin.
    Otherwise 403."""
    c = db.session.get(Committee, committee_id)
    if c is None:
        return None, (jsonify({"error": "اللجنة غير موجودة"}), 404)
    if _is_club_admin(current_user):
        return c, None
    if c.leader_user_id == current_user.id:
        return c, None
    return None, (jsonify({"error": "ليست لديك صلاحية على هذه اللجنة"}), 403)


@app.get("/committee-leader/members")
@login_required
def committee_leader_members_page():
    """Dedicated per-committee-leader page. If the caller leads exactly
    one committee, we auto-pick it. If they lead several, the page
    lists them all. Club admins see every committee."""
    led = _committees_led_by(current_user)
    is_admin = _is_club_admin(current_user)
    if not led and not is_admin:
        abort(403)
    # Which committee are we showing? Query-string override wins (admins
    # need this to pick any committee); the authorization check inside
    # _get_managed_committee enforces leaders can only pick their own.
    requested_id = request.args.get("committee_id", type=int)
    if requested_id is not None:
        c, err = _get_managed_committee(requested_id)
        if err is not None:
            abort(err[1])
        committee = c
    elif led:
        committee = led[0]
    else:
        # Admin with no selection → first committee in the system.
        committee = Committee.query.order_by(Committee.name.asc()).first()
    committees_managed = led if not is_admin else Committee.query.order_by(Committee.name.asc()).all()
    members = []
    if committee is not None:
        members = (
            User.query
            .filter_by(committee_id=committee.id)
            .order_by(User.name.asc())
            .all()
        )
    return render_template(
        "committee-members.html",
        committee=committee,
        committees_managed=committees_managed,
        members=members,
        committee_leader=(
            db.session.get(User, committee.leader_user_id)
            if committee and committee.leader_user_id else None
        ),
    )


@app.get("/committee-leader/<int:committee_id>/eligible")
@login_required
def committee_leader_eligible_members(committee_id):
    """List users eligible to be ADDED to this committee: role in
    (member, leader), currently unassigned (committee_id IS NULL)."""
    _, err = _get_managed_committee(committee_id)
    if err is not None:
        return err
    rows = (
        User.query
        .filter(User.role.in_(("member", "leader")),
                User.committee_id.is_(None))
        .order_by(User.name.asc())
        .all()
    )
    return jsonify({
        "committee_id": committee_id,
        "eligible": [
            {"id": u.id, "name": u.name, "email": u.email, "role": u.role}
            for u in rows
        ],
    })


@app.post("/committee-leader/<int:committee_id>/add-member")
@login_required
def committee_leader_add_member(committee_id):
    c, err = _get_managed_committee(committee_id)
    if err is not None:
        return err
    user_id = _int_or_none(submitted().get("user_id"))
    user = db.session.get(User, user_id) if user_id else None
    if not _eligible_member(user):
        return jsonify({"error": "يُسمح فقط بإضافة أعضاء مسجلين"}), 400
    if user.committee_id is not None and user.committee_id != c.id:
        return jsonify({
            "error": "العضو مُعيّن بالفعل في لجنة أخرى. يجب نزعه منها أولاً.",
            "code": "already_assigned",
        }), 409
    if user.committee_id == c.id:
        return jsonify({"error": "العضو موجود بالفعل في هذه اللجنة",
                        "code": "duplicate"}), 409
    _assign_user_to_committee(user, c)
    db.session.commit()
    return jsonify({
        "committee_id": c.id,
        "member": {"id": user.id, "name": user.name, "email": user.email,
                   "points": int(user.points or 0)},
    })


@app.post("/committee-leader/<int:committee_id>/award-points")
@login_required
def committee_leader_award_points(committee_id):
    """Manual points award to a member of THIS committee only.
    Validation + authorization both happen here; the frontend's hidden
    fields are untrusted."""
    c, err = _get_managed_committee(committee_id)
    if err is not None:
        return err
    data = submitted()
    user_id = _int_or_none(data.get("user_id"))
    points_raw = data.get("points")
    description = text_field(data, "description")[:500]
    # Validation
    try:
        points = int(points_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "النقاط يجب أن تكون رقماً صحيحاً"}), 400
    if points <= 0:
        return jsonify({"error": "النقاط يجب أن تكون رقماً موجباً"}), 400
    if points > 1000:
        return jsonify({"error": "النقاط يجب أن تكون أقل من 1000"}), 400
    if not description:
        return jsonify({"error": "وصف المهمة مطلوب"}), 400
    user = db.session.get(User, user_id) if user_id else None
    if user is None:
        return jsonify({"error": "العضو غير موجود"}), 404
    # Hard check: user must be in THIS committee (prevents URL/payload tampering).
    if user.committee_id != c.id:
        return jsonify({"error": "العضو ليس عضواً في هذه اللجنة"}), 403
    # Record the award. We use ActivityLog directly (not _award_points)
    # because manual awards have no uniqueness index to collide with —
    # a leader may legitimately award points for several tasks. We still
    # protect against double-submit by requiring the frontend to disable
    # the submit button, which is tested in the Playwright suite.
    log = ActivityLog(
        user_id=user.id,
        action="manual_award",
        points_delta=points,
        description=description,
        awarded_by_user_id=current_user.id,
    )
    db.session.add(log)
    user.points = int(user.points or 0) + points
    db.session.commit()
    return jsonify({
        "awarded": points,
        "new_total": int(user.points),
        "member": {"id": user.id, "name": user.name},
        "activity_id": log.id,
        "description": description,
    })


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
        db.session.flush()
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


# ============================================================
# Phase 6: shared helpers for interests / tags / deadline / capacity
# ============================================================

# Canonical interest/tag list exposed in the UI. Leaders/members may store
# additional free-text tags, but these are what the member dashboard offers
# as checkboxes and what we match case-insensitively.
INTEREST_CHOICES = [
    "الابتكار",
    "ورش هندسية",
    "زيارات ميدانية",
    "التصنيع",
    "ريادة الأعمال",
    "الاستدامة",
    "اللوجستيات",
    "السلامة",
    "التقنية",
]


def _normalize_tag_list(raw):
    """Accept a list OR a comma/newline-separated string; return a sorted,
    de-duplicated list of trimmed, lowercase tags. Empty inputs → []."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = raw
    else:
        parts = str(raw).replace("\n", ",").split(",")
    seen = []
    for p in parts:
        tag = (p or "").strip().lower()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def _tags_to_storage(tag_list):
    """Serialize a tag list for storage. Empty list → None (so the column
    stays NULL and queries using `WHERE tags IS NULL` keep working)."""
    tags = _normalize_tag_list(tag_list)
    return ", ".join(tags) if tags else None


def _tags_match(user_interests, event_tags):
    """True iff user and event share at least one tag (case-insensitive)."""
    u = set(_normalize_tag_list(user_interests))
    e = set(_normalize_tag_list(event_tags))
    return bool(u & e)


def _effective_deadline(event):
    """The datetime after which registration is no longer accepted.
    Precedence: explicit registration_deadline > event start date."""
    if event is None:
        return None
    return event.registration_deadline or event.date


def _registration_is_closed(event, now=None):
    """True iff the deadline has passed. Missing deadline AND missing date
    → treat as open (safe default; the normal UI never allows this)."""
    deadline = _effective_deadline(event)
    if deadline is None:
        return False
    return (now or datetime.now()) > deadline


def _confirmed_count(event_id):
    return (
        EventRegistration.query
        .filter_by(event_id=event_id, is_waitlisted=False)
        .count()
    )


def _waitlist_count(event_id):
    return (
        EventRegistration.query
        .filter_by(event_id=event_id, is_waitlisted=True)
        .count()
    )


def _remaining_seats(event):
    """Int remaining seats, or None if capacity is unlimited (NULL)."""
    if event is None or event.capacity is None:
        return None
    remaining = int(event.capacity) - _confirmed_count(event.id)
    return max(0, remaining)


def _event_is_full(event):
    """True iff capacity is set and all seats are taken. Unlimited → False."""
    rem = _remaining_seats(event)
    return rem is not None and rem <= 0


def _event_registration_snapshot(event):
    """Payload embedded in registration responses and surfaced by the
    public JSON stat endpoint. Safe to serialize."""
    now = datetime.now()
    deadline = _effective_deadline(event)
    return {
        "event_id": event.id,
        "capacity": event.capacity,
        "confirmed": _confirmed_count(event.id),
        "waitlist": _waitlist_count(event.id),
        "remaining": _remaining_seats(event),
        "is_full": _event_is_full(event),
        "registration_deadline": (
            event.registration_deadline.isoformat()
            if event.registration_deadline else None
        ),
        "effective_deadline": deadline.isoformat() if deadline else None,
        "registration_closed": _registration_is_closed(event, now),
    }


# ------------------------------------------------------------
# Phase 6: concurrency control for registration.
#
# SQLite serializes writers via BEGIN IMMEDIATE, so a single-row lock is not
# meaningful — the entire transaction holds a reserved lock. Postgres (and
# MySQL/MariaDB) support SELECT ... FOR UPDATE on a specific row, which gives
# us a per-event lock without serializing the whole DB.
#
# `_lock_event_for_registration` returns the (re-queried) Event with an
# appropriate lock held for the duration of the current transaction. All
# capacity math + the INSERT must happen inside that same transaction.
# ------------------------------------------------------------
def _lock_event_for_registration(event_id):
    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        # BEGIN IMMEDIATE acquires a RESERVED lock up-front; subsequent
        # writers wait. We only trigger this once per transaction because
        # SQLite upgrades automatically on first write, but calling it
        # explicitly removes a race between the SELECT and the INSERT.
        try:
            db.session.execute(db.text("BEGIN IMMEDIATE"))
        except OperationalError:
            # A transaction is already open with a write lock — fine.
            pass
        return db.session.get(Event, event_id)
    # Postgres / MySQL path: per-row lock, lets other events proceed.
    q = Event.query.filter_by(id=event_id).with_for_update()
    return q.one_or_none()


# ------------------------------------------------------------
# Phase 6: optional outbound email delivery.
#
# Driven exclusively by environment variables. If MAIL_HOST is unset, every
# call is a no-op and the in-app notification path still runs normally.
# Never log credentials; never raise — email is best-effort.
# ------------------------------------------------------------
def _mail_enabled():
    return bool(os.environ.get("MAIL_HOST", "").strip())


def _send_email_safe(to_address, subject, body):
    if not _mail_enabled() or not to_address:
        return False
    host = os.environ.get("MAIL_HOST", "").strip()
    port = int(os.environ.get("MAIL_PORT", "587") or 587)
    user = os.environ.get("MAIL_USERNAME", "").strip() or None
    password = os.environ.get("MAIL_PASSWORD", "") or None
    sender = os.environ.get("MAIL_FROM", "").strip() or user or "no-reply@localhost"
    use_tls = (os.environ.get("MAIL_USE_TLS", "1").strip().lower()
               in ("1", "true", "yes", "on"))
    try:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.set_content(body)
        if use_tls:
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.starttls()
                if user and password:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                if user and password:
                    s.login(user, password)
                s.send_message(msg)
        return True
    except Exception as exc:   # noqa: BLE001 — best-effort delivery
        logger.warning("Email send failed to %s: %s", to_address, exc)
        return False


def _notify_matching_members_for_event(event):
    """When a leader publishes an event with tags, create one notification
    row for each member whose interests intersect those tags. Idempotent:
    the partial unique index on (event_id, recipient_user_id) WHERE
    kind='event_match' blocks duplicates even on repeated calls."""
    if event is None or not event.is_public or not event.tags:
        return 0
    event_tags = _normalize_tag_list(event.tags)
    if not event_tags:
        return 0
    members = User.query.filter(
        User.role.in_(("member", "leader", "supervisor")),
        User.interests.isnot(None),
        User.interests != "",
    ).all()
    link = url_for("event_detail_page", event_id=event.id)
    created = 0
    for m in members:
        if not _tags_match(m.interests, event_tags):
            continue
        try:
            with db.session.begin_nested():
                db.session.add(Notification(
                    recipient_user_id=m.id,
                    kind="event_match",
                    event_id=event.id,
                    message=f"فعالية جديدة تناسب اهتماماتك: «{event.title[:80]}»",
                    link=link,
                ))
            created += 1
            # Best-effort email, driven by env config. Failures are swallowed.
            _send_email_safe(
                m.email,
                f"فعالية جديدة: {event.title}",
                f"مرحباً {m.name}،\n\nتم نشر فعالية جديدة تطابق اهتماماتك: "
                f"{event.title}\n\nرابط الفعالية: {link}\n",
            )
        except IntegrityError:
            # Duplicate (event, recipient) — already notified.
            pass
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return created


def _notify_waitlist_promotion(registration, event):
    """In-app + optional email notification when a waitlisted registrant
    is promoted. Only called when the promoted row has a user_id (anonymous
    waitlisters get an email if available but no Notification row)."""
    link = url_for("event_detail_page", event_id=event.id)
    msg = f"تم تأكيد مقعدك في الفعالية: «{event.title[:80]}»"
    if registration.user_id is not None:
        try:
            with db.session.begin_nested():
                db.session.add(Notification(
                    recipient_user_id=registration.user_id,
                    kind="waitlist_promoted",
                    event_id=event.id,
                    message=msg,
                    link=link,
                ))
        except IntegrityError:
            pass
    _send_email_safe(
        registration.email,
        f"تم تأكيد مقعدك: {event.title}",
        f"مرحباً {registration.name}،\n\n{msg}\n\nرابط الفعالية: {link}\n",
    )


@app.post("/leader/events")
@role_required("leader", "supervisor")
def create_event():
    data = submitted()
    title = text_field(data, "title")[:200]
    if not title:
        return jsonify({"error": "يرجى إدخال عنوان الفعالية"}), 400
    # Phase 10: category is REQUIRED and must be one of EVENT_CATEGORIES.
    category = text_field(data, "category")[:40]
    if not category:
        return jsonify({"error": "نوع الفعالية مطلوب"}), 400
    if category not in EVENT_CATEGORIES:
        return jsonify({
            "error": "نوع الفعالية غير صالح. القيم المسموحة: " + "، ".join(EVENT_CATEGORIES)
        }), 400
    date_raw = data.get("date")
    time_raw = data.get("time")
    event_dt = _parse_iso_datetime(date_raw, time_raw)
    if event_dt is None:
        return jsonify({"error": "التاريخ أو الوقت غير صالح (الصيغة YYYY-MM-DD و HH:MM)"}), 400
    raw_public = data.get("is_public")
    is_public = str(raw_public).lower() in ("1", "true", "on", "yes") if raw_public is not None else False
    # Image: prefer an uploaded file (field name "image"); fall back to the
    # legacy "image_path" text field pointing at a file inside static/.
    image_path = None
    uploaded = request.files.get("image")
    virtual, up_err = _save_event_image_upload(uploaded)
    if up_err:
        return jsonify({"error": up_err}), 400
    if virtual:
        image_path = virtual
    else:
        logo_input = text_field(data, "image_path")
        if logo_input:
            rel = _safe_static_rel(logo_input)
            if rel is None or not _static_file_exists(rel):
                return jsonify({"error": "image_path يجب أن يشير إلى ملف موجود داخل static/"}), 400
            image_path = rel
    # Phase 6: optional capacity / registration deadline / tags.
    capacity = _int_or_none(data.get("capacity"))
    if capacity is not None and capacity < 0:
        return jsonify({"error": "السعة يجب أن تكون صفراً أو أكبر"}), 400
    reg_deadline_dt = None
    if data.get("registration_deadline_date"):
        reg_deadline_dt = _parse_iso_datetime(
            data.get("registration_deadline_date"),
            data.get("registration_deadline_time") or "23:59",
        )
        if reg_deadline_dt is None:
            return jsonify({
                "error": "موعد إغلاق التسجيل غير صالح"
            }), 400
        if reg_deadline_dt > event_dt:
            return jsonify({
                "error": "موعد إغلاق التسجيل يجب أن يكون قبل أو عند موعد الفعالية"
            }), 400
    tags_value = _tags_to_storage(data.get("tags"))
    # Optional venue fields.
    location_name = text_field(data, "location_name")[:200] or None
    location_url_raw = text_field(data, "location_url")[:500]
    location_url = None
    if location_url_raw:
        if not _valid_http_url(location_url_raw):
            return jsonify({"error": "رابط الموقع يجب أن يبدأ بـ http:// أو https://"}), 400
        location_url = location_url_raw

    event = Event(
        title=title,
        image_path=image_path,
        is_public=is_public,
        date=event_dt,
        registration_deadline=reg_deadline_dt,
        capacity=capacity,
        tags=tags_value,
        category=category,
        location_name=location_name,
        location_url=location_url,
    )
    db.session.add(event)
    db.session.commit()

    # Phase 6: fire interest-match notifications only for public events.
    notified = _notify_matching_members_for_event(event)

    return jsonify({
        "id": event.id,
        "title": event.title,
        "date": event.date.isoformat(),
        "is_public": event.is_public,
        "image_path": event.image_path,
        "registration_deadline": (
            event.registration_deadline.isoformat()
            if event.registration_deadline else None
        ),
        "capacity": event.capacity,
        "tags": _normalize_tag_list(event.tags),
        "category": event.category,
        "location_name": event.location_name,
        "location_url": event.location_url,
        "notified_members": notified,
    }), 201


@app.post("/leader/events/<int:event_id>/edit")
@role_required("leader", "supervisor")
def edit_event(event_id):
    """Phase 5+: update an existing event in place. The event id,
    attached tasks (via task.event_id FK), and visitor registrations
    (via event_registration.event_id FK) are preserved."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
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
    is_public = (str(raw_public).lower() in ("1", "true", "on", "yes")
                 if raw_public is not None else event.is_public)

    # Image handling. Priority:
    #   1) If a file was uploaded (multipart field "image"), replace.
    #   2) Else if the client sent "image_path" (legacy static path):
    #        empty string → clear; non-empty → must resolve inside static/.
    #   3) Else leave the current image untouched.
    uploaded = request.files.get("image")
    virtual, up_err = _save_event_image_upload(uploaded)
    if up_err:
        return jsonify({"error": up_err}), 400
    if virtual:
        event.image_path = virtual
    elif "image_path" in data:
        logo_input = text_field(data, "image_path")
        if logo_input == "":
            event.image_path = None
        else:
            rel = _safe_static_rel(logo_input)
            if rel is None or not _static_file_exists(rel):
                return jsonify({"error": "image_path يجب أن يشير إلى ملف موجود داخل static/"}), 400
            event.image_path = rel

    # Phase 6: capacity / registration deadline / tags updates.
    if "capacity" in data:
        new_capacity = _int_or_none(data.get("capacity"))
        if new_capacity is not None and new_capacity < 0:
            return jsonify({"error": "السعة يجب أن تكون صفراً أو أكبر"}), 400
        event.capacity = new_capacity
    if "registration_deadline_date" in data:
        rd_raw = data.get("registration_deadline_date") or ""
        if not rd_raw.strip():
            event.registration_deadline = None
        else:
            reg_deadline_dt = _parse_iso_datetime(
                rd_raw,
                data.get("registration_deadline_time") or "23:59",
            )
            if reg_deadline_dt is None:
                return jsonify({"error": "موعد إغلاق التسجيل غير صالح"}), 400
            if reg_deadline_dt > event_dt:
                return jsonify({
                    "error": "موعد إغلاق التسجيل يجب أن يكون قبل أو عند موعد الفعالية"
                }), 400
            event.registration_deadline = reg_deadline_dt
    if "tags" in data:
        event.tags = _tags_to_storage(data.get("tags"))
    # Phase 10: category — accept only values in EVENT_CATEGORIES. Empty
    # string clears (back to NULL) for parity with the other optional fields.
    if "category" in data:
        new_category = text_field(data, "category")[:40]
        if new_category and new_category not in EVENT_CATEGORIES:
            return jsonify({
                "error": "نوع الفعالية غير صالح. القيم المسموحة: " + "، ".join(EVENT_CATEGORIES)
            }), 400
        event.category = new_category or None
    # Optional venue fields — empty string clears, non-empty replaces.
    if "location_name" in data:
        event.location_name = text_field(data, "location_name")[:200] or None
    if "location_url" in data:
        url_raw = text_field(data, "location_url")[:500]
        if url_raw and not _valid_http_url(url_raw):
            return jsonify({"error": "رابط الموقع يجب أن يبدأ بـ http:// أو https://"}), 400
        event.location_url = url_raw or None

    was_public = event.is_public
    event.title = title
    event.date = event_dt
    event.is_public = is_public
    db.session.commit()

    # Phase 6: promote waitlisters if capacity was raised and seats opened.
    promoted_total = 0
    while True:
        remaining = _remaining_seats(event)
        if remaining is None or remaining <= 0:
            break
        candidate = (
            EventRegistration.query
            .filter_by(event_id=event.id, is_waitlisted=True)
            .order_by(EventRegistration.waitlisted_at.asc(),
                      EventRegistration.id.asc())
            .first()
        )
        if candidate is None:
            break
        candidate.is_waitlisted = False
        candidate.waitlisted_at = None
        db.session.commit()
        _notify_waitlist_promotion(candidate, event)
        promoted_total += 1

    # Phase 6: if the event just became public (or stayed public but tags
    # changed), re-run the match pass. Duplicate inserts are blocked by the
    # unique partial index on (event_id, recipient_user_id).
    notified = 0
    if event.is_public:
        notified = _notify_matching_members_for_event(event)

    return jsonify({
        "id": event.id,
        "title": event.title,
        "date": event.date.isoformat(),
        "is_public": event.is_public,
        "image_path": event.image_path,
        "registration_deadline": (
            event.registration_deadline.isoformat()
            if event.registration_deadline else None
        ),
        "capacity": event.capacity,
        "tags": _normalize_tag_list(event.tags),
        "category": event.category,
        "location_name": event.location_name,
        "location_url": event.location_url,
        "promoted": promoted_total,
        "notified_members": notified,
        "was_public": was_public,
    })


@app.post("/leader/events/<int:event_id>/delete")
@role_required("leader", "supervisor")
def delete_event(event_id):
    """Phase 5+: delete an event. By default refuses when visitor
    registrations or assigned tasks exist, so the leader cannot
    silently discard committed data. Pass ?force=1 to proceed anyway;
    tasks are unlinked (FK cleared, task row preserved) and
    registrations are deleted together with the event."""
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    reg_count = EventRegistration.query.filter_by(event_id=event_id).count()
    task_count = Task.query.filter_by(event_id=event_id).count()

    data = submitted()
    force_raw = (data.get("force") if hasattr(data, "get") else None) or request.args.get("force")
    force = str(force_raw).lower() in ("1", "true", "yes")

    if (reg_count > 0 or task_count > 0) and not force:
        return jsonify({
            "error": "الفعالية مرتبطة بسجلات أخرى. أعد الإرسال مع force=1 للمتابعة.",
            "registrations": reg_count,
            "tasks": task_count,
        }), 409

    # Unlink tasks (preserve the task row), delete registrations with the event.
    for t in Task.query.filter_by(event_id=event_id).all():
        t.event_id = None
    for r in EventRegistration.query.filter_by(event_id=event_id).all():
        db.session.delete(r)
    db.session.delete(event)
    db.session.commit()
    return jsonify({
        "deleted": event_id,
        "registrations_removed": reg_count,
        "tasks_unlinked": task_count,
    })


def _serialize_task(t):
    """Compact serializer used by every supervisor task-list endpoint."""
    return {
        "id": t.id,
        "title": t.title,
        "event_id": t.event_id,
        "event_title": t.event.title if t.event else None,
        "assigned_user_id": t.assigned_user_id,
        "assigned_user_name": t.assigned_user.name if t.assigned_user else None,
        "committee": (
            t.assigned_user.committee
            if (t.assigned_user and t.assigned_user.committee) else None
        ),
        "role": t.role,
        "points": t.points,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "status": t.status,
        "approval_status": t.approval_status,
    }


def _filtered_tasks_query():
    """Shared filter/search parser for the supervisor dashboard + API.
    Reads request.args; returns (query, filters_dict)."""
    q = Task.query
    event_id = request.args.get("event_id", type=int)
    committee = (request.args.get("committee") or "").strip()
    status = (request.args.get("status") or "").strip()
    approval = (request.args.get("approval") or "").strip()
    search = (request.args.get("q") or "").strip()

    if event_id:
        q = q.filter(Task.event_id == event_id)
    if committee:
        q = q.join(User, Task.assigned_user_id == User.id).filter(
            User.committee == committee
        )
    if status in ("قيد التنفيذ", "مكتملة"):
        q = q.filter(Task.status == status)
    if approval in ("pending", "approved", "rejected"):
        q = q.filter(Task.approval_status == approval)
    if search:
        pattern = f"%{search}%"
        # Only join User once; already joined above if committee filter is set.
        if not committee:
            q = q.outerjoin(User, Task.assigned_user_id == User.id)
        q = q.filter(db.or_(Task.title.ilike(pattern), User.name.ilike(pattern)))

    return q, {
        "event_id": event_id,
        "committee": committee,
        "status": status,
        "approval": approval,
        "q": search,
    }


@app.get("/supervisor/dashboard")
@role_required("supervisor", "leader")
def supervisor_dashboard():
    stats = _compute_supervisor_stats()

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 25
    tasks_q, filters = _filtered_tasks_query()
    total_tasks = tasks_q.count()
    tasks = (
        tasks_q.order_by(Task.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    total_pages = max(1, (total_tasks + per_page - 1) // per_page)

    # Distinct committees for the filter dropdown — pulled from live users
    # so a renamed/removed committee disappears automatically.
    committee_names = sorted({
        u.committee for u in User.query.filter(
            User.committee.isnot(None), User.committee != ""
        ).all()
    })

    return render_template(
        "supervisor-dashboard.html",
        stats=stats,
        tasks=tasks,
        task_filters=filters,
        task_page=page,
        task_total_pages=total_pages,
        task_total=total_tasks,
        committee_names=committee_names,
    )


@app.get("/supervisor/tasks.json")
@role_required("supervisor", "leader")
def supervisor_tasks_json():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(5, request.args.get("per_page", 25, type=int)))
    q, filters = _filtered_tasks_query()
    total = q.count()
    rows = (
        q.order_by(Task.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return jsonify({
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "filters": filters,
        "tasks": [_serialize_task(t) for t in rows],
    })


@app.get("/supervisor/events/<int:event_id>/tasks.json")
@role_required("supervisor", "leader")
def supervisor_event_tasks(event_id):
    event = db.session.get(Event, event_id)
    if event is None:
        abort(404)
    rows = (
        Task.query.filter_by(event_id=event_id)
        .order_by(Task.created_at.desc())
        .all()
    )
    return jsonify({
        "event": {
            "id": event.id,
            "title": event.title,
            "date": event.date.isoformat() if event.date else None,
            "is_public": event.is_public,
        },
        "tasks": [_serialize_task(t) for t in rows],
    })


@app.get("/supervisor/committees/<path:name>/tasks.json")
@role_required("supervisor", "leader")
def supervisor_committee_tasks(name):
    members = User.query.filter_by(committee=name).all()
    if not members:
        abort(404)
    member_ids = [u.id for u in members]
    rows = (
        Task.query.filter(Task.assigned_user_id.in_(member_ids))
        .order_by(Task.created_at.desc())
        .all()
    )
    return jsonify({
        "committee": {
            "name": name,
            "members": [
                {"id": u.id, "name": u.name, "points": int(u.points or 0)}
                for u in members
            ],
        },
        "tasks": [_serialize_task(t) for t in rows],
    })


@app.get("/supervisor/report.csv")
@role_required("supervisor", "leader")
def supervisor_report_csv():
    """Phase 5+: real CSV export with task-level, event-progress, and
    committee data pulled live from the database."""
    import csv, io
    s = _compute_supervisor_stats()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["تقرير أداء النادي — نادي رواد الصناعة"])
    w.writerow(["تاريخ التقرير", datetime.now().strftime("%Y-%m-%d %H:%M")])
    w.writerow([])
    w.writerow(["=== إحصائيات عامة ==="])
    w.writerow(["إجمالي الفعاليات العامة", s["events"]["public_total"]])
    w.writerow(["الفعاليات المنتهية", s["events"]["completed"]])
    w.writerow(["الفعاليات القادمة", s["events"]["upcoming"]])
    w.writerow(["إجمالي المهام", s["tasks"]["total"]])
    w.writerow(["المهام المعتمدة", s["tasks"]["approved"]])
    w.writerow(["المهام قيد المراجعة", s["tasks"]["pending_review"]])
    w.writerow(["المهام المرفوضة", s["tasks"]["rejected"]])
    w.writerow(["نسبة إنجاز المهام (معتمد)", f'{s["tasks"]["approved_pct"]}%'])
    w.writerow(["إجمالي المقالات المعتمدة", s["articles"]["approved"]])
    w.writerow(["إجمالي المبادرات المعتمدة", s["initiatives"]["approved"]])
    w.writerow(["عدد الأعضاء", s["members"]["total"]])
    w.writerow(["إجمالي النقاط الموزعة", s["members"]["total_points"]])
    w.writerow([])
    w.writerow(["=== تقدم الفعاليات ==="])
    w.writerow(["الفعالية", "إجمالي المهام", "معتمد", "قيد المراجعة", "متبقي", "نسبة الإنجاز"])
    for ev in s["per_event"]:
        w.writerow([
            ev["event_title"], ev["total"], ev["approved"],
            ev["pending_review"], ev["remaining"], f'{ev["completion_pct"]}%'
        ])
    w.writerow([])
    w.writerow(["=== تقدم اللجان ==="])
    w.writerow(["اللجنة", "عدد الأعضاء", "إجمالي المهام", "معتمد", "قيد المراجعة",
                "نسبة الإنجاز", "إجمالي النقاط"])
    for c in s["committees"]:
        w.writerow([
            c["name"], c["members"], c["tasks_total"], c["tasks_approved"],
            c["tasks_pending"], f'{c["completion_pct"]}%', c["points_earned"]
        ])
    w.writerow([])
    w.writerow(["=== سجل المهام ==="])
    w.writerow(["المهمة", "الفعالية", "العضو", "اللجنة", "الدور",
                "النقاط", "الموعد", "الحالة", "الاعتماد"])
    for t in Task.query.order_by(Task.created_at.desc()).all():
        w.writerow([
            t.title,
            t.event.title if t.event else "—",
            t.assigned_user.name if t.assigned_user else "—",
            t.assigned_user.committee if (t.assigned_user and t.assigned_user.committee) else "—",
            t.role or "—",
            t.points,
            t.deadline.isoformat() if t.deadline else "—",
            t.status,
            t.approval_status,
        ])
    csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    from flask import Response
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="club-report-{datetime.now().strftime("%Y%m%d-%H%M")}.csv"'},
    )


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.get("/leader/db-info")
@role_required("leader", "supervisor")
def db_info():
    """Leader/supervisor-only read-only probe. Reports which backend
    SQLAlchemy is actually talking to on this deploy, with the host
    redacted enough that no secret is exposed. Also runs a trivial
    SELECT to confirm the connection is live. No writes."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "") or ""
    dialect = (uri.split("://", 1)[0] or "unknown").split("+", 1)[0]
    host_hint = ""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(uri)
        hostname = parts.hostname or ""
        if hostname:
            # Keep enough to recognize the Neon project (ep-xxxx) but
            # never show user/password or query string.
            labels = hostname.split(".")
            head = labels[0]
            tld = ".".join(labels[-2:]) if len(labels) >= 2 else ""
            host_hint = f"{head[:12]}***.{tld}" if head and tld else "***"
    except Exception:   # noqa: BLE001 — never let a probe crash
        host_hint = "***"
    live = False
    try:
        db.session.execute(db.text("SELECT 1")).scalar()
        live = True
    except Exception as exc:   # noqa: BLE001
        logger.warning("db-info SELECT 1 failed: %s", exc)
    return jsonify({
        "dialect": dialect,
        "host_hint": host_hint,
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
        "live": live,
    })


if __name__ == "__main__":
    app.run(debug=True)
