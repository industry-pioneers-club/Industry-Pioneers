# Phase 2 Merge Proposal — Member Dashboard Full Implementation

Tested in isolation on `_isolated_phase2a/`, `_isolated_phase2b/`, `_isolated_phase2c/`, `_isolated_phase2d/`. **No live code touched, no shared-DB write performed.** Shared DB sha identical to baseline `3591ba52190d5a6d6344f78c33564013008eb772a5334fe17cf6b77b09c1c275` across all four phases.

## Scope delivered

### Phase 2A — Profile + points balance
- `User.committee` (nullable VARCHAR 120) — leader-assignable.
- `User.points` (NOT NULL INTEGER default 0).
- Member dashboard shows real committee, real points, progress bar `points / 500`.
- New route `POST /leader/members/<id>/committee`.

### Phase 2B — Approval workflow + activity log + auto-award
- `Task.approval_status` (default 'pending'), `Task.approved_by` (FK user), `Task.approved_at`.
- New `activity_log` table (user_id, task_id, event_id, action, points_delta, recorded_at).
- Partial unique index `uq_activity_task_approved` on `(task_id)` WHERE `action='task_approved'` — DB-level duplicate-award guard.
- Routes `POST /leader/tasks/<id>/approve` and `POST /leader/tasks/<id>/reject`:
  - Atomic approve: mark task → ledger insert (unique index enforced via `flush()`) → increment user points → commit.
  - Reject: mark task → ledger insert with `points_delta=0` → commit.
  - 403 for non-leader/supervisor, 404 for missing, 400 for unassigned, 409 for duplicate-approve or reject-after-approve.
- Member dashboard shows latest 20 ActivityLog entries with color-coded Arabic labels.

### Phase 2C — Tasks grouped by event + approval badges on `/member/tasks`
- Member tasks grouped by event; null-event tasks in "مهام عامة" bucket.
- Each task card shows member-status + approval-state badge (معتمد/مرفوض/قيد المراجعة).
- Approved tasks have the status dropdown hidden (immutable).

### Phase 2D — Leader approval UI
- New "اعتماد مهام الأعضاء" section on `/leader/dashboard` listing tasks where member set `status='مكتملة'` and `approval_status='pending'`.
- Approve / reject buttons with confirm dialog + toast feedback.
- JS removes the row from the pending list on success; falls back to empty-state on last row.
- End-to-end flow verified: member marks مكتملة → leader sees in pending list → leader clicks approve → member sees updated points + activity log entry.

## Test totals

| Phase | Tests | Result |
|---|---|---|
| 2A | 15 | **15/15 PASS** |
| 2B | 15 | **15/15 PASS** |
| 2C | 7 | **7/7 PASS** |
| 2D | 15 | **15/15 PASS** |
| **Total** | **52** | **52/52 PASS** |

All invariants verified:
- Member/visitor cannot approve tasks (403).
- Member cannot modify other members' tasks (ownership check from Phase 0 preserved).
- Approval → points awarded exactly once (duplicate POST returns 409 and points stay fixed).
- Rejection → no points added.
- Approve-then-reject → 409.
- Reject-then-approve → OK (status transitions pending → rejected → pending reset needed to re-approve; current implementation does not reset so this case returns 409 if attempted).
- Points persist across server restart (verified in Phase 2B tests on disk).
- Role separation preserved across all phases.
- Idempotent schema migrations (safe to re-run on boot).

## Files touched in isolation (NOT in live project)

```
_isolated_phase2a/   app.py (+2A edits), templates/, static/, _run.py, _tests.py
_isolated_phase2b/   app.py (+2A+2B edits), templates/member-dashboard.html (activity log), _run.py, _tests.py
_isolated_phase2c/   app.py (+2A+2B+2C edits), templates/tasks.html (grouped+badges), _run.py, _tests.py
_isolated_phase2d/   app.py (+2A+2B+2C+2D edits), templates/leader-dashboard.html (approval UI),
                     static/js/main.js (approval handlers), _run.py, _tests.py
```

Isolated test DBs:
```
instance/club.phase2a-test.db
instance/club.phase2b-test.db
instance/club.phase2c-test.db
instance/club.phase2d-test.db
```

## Proposed shared-DB migration — EXACT operations

Would run inside `initialize_database()` under the existing fcntl seed-lock, via an idempotent `_upgrade_schema()` helper. **All operations additive and non-destructive.**

### SQLite dialect (local dev + the current shared `club.db`)

```sql
-- Phase 2A
ALTER TABLE user ADD COLUMN committee VARCHAR(120) DEFAULT NULL;
ALTER TABLE user ADD COLUMN points INTEGER NOT NULL DEFAULT 0;

-- Phase 2B
ALTER TABLE task ADD COLUMN approval_status VARCHAR(20) NOT NULL DEFAULT 'pending';
ALTER TABLE task ADD COLUMN approved_by INTEGER DEFAULT NULL;
ALTER TABLE task ADD COLUMN approved_at DATETIME DEFAULT NULL;

-- Phase 2B new table (created by db.create_all() from the ActivityLog model)
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    task_id INTEGER,
    event_id INTEGER,
    action VARCHAR(50) NOT NULL,
    points_delta INTEGER NOT NULL,
    recorded_at DATETIME NOT NULL,
    FOREIGN KEY(user_id) REFERENCES user(id),
    FOREIGN KEY(task_id) REFERENCES task(id),
    FOREIGN KEY(event_id) REFERENCES event(id)
);

-- Phase 2B unique partial index
CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_task_approved
    ON activity_log(task_id) WHERE action = 'task_approved';
```

Each ALTER wrapped in a `PRAGMA table_info` existence check (`_ensure_sqlite_column`) so re-running is a no-op.

### Postgres dialect (if `DATABASE_URL` points at Postgres)

```sql
ALTER TABLE "user"
    ADD COLUMN IF NOT EXISTS committee VARCHAR(120),
    ADD COLUMN IF NOT EXISTS points INTEGER NOT NULL DEFAULT 0;

ALTER TABLE task
    ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES "user"(id),
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    task_id INTEGER REFERENCES task(id),
    event_id INTEGER REFERENCES event(id),
    action VARCHAR(50) NOT NULL,
    points_delta INTEGER NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_activity_task_approved
    ON activity_log(task_id) WHERE action = 'task_approved';
```

(Phase 2A/2B/2C/2D isolation only exercised the SQLite path. Postgres path shown for completeness; would be tested against a disposable Postgres instance before any Render deployment.)

### Backfill behavior

| Table | Behavior |
|---|---|
| `user` (3 existing rows) | New `committee` = NULL (unassigned), new `points` = 0. **No row data changed.** |
| `task` (1 existing row — "زياره") | New `approval_status` = 'pending', `approved_by` = NULL, `approved_at` = NULL. **No row data changed.** |
| `activity_log` | Table starts empty. |

### Backup + verification plan (before migration)

Executed in sequence:

1. **Create backup** via SQLite online backup API:
   ```python
   # _backup_db.py-style, src=instance/club.db, dst=instance/club.db.pre-phase2-full
   src = sqlite3.connect('instance/club.db')
   dst = sqlite3.connect('instance/club.db.pre-phase2-full')
   with dst: src.backup(dst)
   ```
   (Refuses to overwrite if `pre-phase2-full` already exists.)

2. **Verify backup**:
   - Byte size matches source.
   - Row counts for `article`, `event`, `sponsor`, `user`, `club_identity`, `task` IDENTICAL to source.
   - `PRAGMA integrity_check` on backup → `('ok',)`.
   - SHA-256 of both files logged (expected to differ slightly due to defragmentation during backup — row-count check is the authoritative data check).

3. **Only if all four verifications pass**, migration proceeds.

4. **Capture shared DB sha BEFORE and AFTER migration**:
   - BEFORE: `3591ba52190d5a6d6344f78c33564013008eb772a5334fe17cf6b77b09c1c275` (current, won't change until migration runs)
   - AFTER: expected to differ (schema change); row-level data preserved exactly.

5. **Rollback plan**:
   ```bash
   cp instance/club.db.pre-phase2-full instance/club.db
   ```
   Fully reversible. The migration touches no existing row's values.

## Live merge steps (to execute AFTER your migration approval)

Prerequisites:
- You stop :5000 (`Ctrl+C` in the terminal running `python app.py`).
- You tell me "proceed with Phase 2 live merge."

Then I execute (no new approval needed per step, since the merge is the thing you approved):

1. Verify port 5000 clear + no python process holds shared DB.
2. Capture shared DB sha BEFORE.
3. Create `instance/club.db.pre-phase2-full` backup via SQLite online backup API. Verify integrity.
4. Edit live `app.py`:
   - Add `committee` + `points` columns on `User` model.
   - Add `approval_status`, `approved_by`, `approved_at` columns on `Task` model.
   - Add `ActivityLog` model.
   - Add `_ensure_sqlite_column` + `_upgrade_schema` helpers.
   - Wire `_upgrade_schema()` into `initialize_database()` (one new line).
   - Add `POINTS_TARGET = 500` constant.
   - Change `member_profile()` to pass `points`, `points_target`, `points_pct`, `committee`, `activity`.
   - Change `member_tasks()` to compute `grouped`.
   - Change `leader_dashboard()` to compute `pending_approval`.
   - Add `POST /leader/members/<id>/committee` route.
   - Add `POST /leader/tasks/<id>/approve` and `/reject` routes.
5. Edit live `templates/member-dashboard.html`: committee info-box, points-display, progress bar bound to points_pct, activity-log section.
6. Edit live `templates/tasks.html`: grouped layout + approval badges, hide status dropdown on approved tasks.
7. Edit live `templates/leader-dashboard.html`: new "اعتماد مهام الأعضاء" section.
8. Append approval handlers to `static/js/main.js`.
9. Static checks: `py_compile app.py` + `node -c static/js/main.js`.
10. Capture shared DB sha AFTER editing (should match BEFORE — edits don't open DB).
11. You restart the server. On startup, `initialize_database()` runs `_upgrade_schema()` which performs the ALTERs + CREATE TABLE + CREATE INDEX. The shared DB sha WILL change at this point (schema change). Row-level data preserved.
12. You browser-test, I report final verification.

## Remaining requirements beyond Phase 2

Not covered by Phases 2A-2D:

### Backend models still missing
- **Badges + achievement history** (BADGE / USER_BADGE tables; award rules keyed to points thresholds). Spec section "Points and Gamification" item (badges).
- **Notifications** (NOTIFICATION table + poll/display endpoint). Spec item: "Notify leader when a member marks a task complete."
- **Event participation / attendance records** (EVENT_PARTICIPATION join table + routes to mark attendance). The `event_attended` ActivityLog.action is defined but no code writes it. Spec: "activity log should include participated events."
- **MembershipRequest / VisitorRegistration tables** for the two forms on `/visitor`. Spec: "connect visitor event registration and membership applications to the database."
- **Article status** (approve/reject workflow for articles — Phase B1 originally deferred). Spec: "Only approved articles appear publicly."

### Backend routes still missing
- `GET /leader/notifications` + mark-read endpoint.
- `POST /visitor/event-signup` + `POST /visitor/membership-request`.
- Article approve/reject + `published_articles()` filter.
- Event attendance mark route (`POST /leader/events/<id>/attendance`).

### Frontend still needing work
- Article approve/reject buttons on leader dashboard (currently local-only JS mock).
- Visitor forms are currently toast-only.
- Members' leaderboard page sorts by name, not points — needs re-sort in `member_leaderboard` route to `.order_by(User.points.desc())`. One-line fix post-Phase-2 migration.
- Badges UI section on member dashboard.
- Notifications bell/panel on leader dashboard.
- Article image upload field on `upload-article.html`.
- Points-guide text alignment with actual configured Task.points.

### Security still needing work
- CSRF protection (Flask-WTF not installed; team's own comment at `app.py:567-568` flags this).
- `/like_article` rate limit + auth (team flags IDOR at `app.py:477-478`).

### Nice-to-have polish
- Event-category column + per-category stats on supervisor dashboard.
- Admin UI to re-open a rejected task (currently requires DB write).

## What stays untouched by this proposal

- Live `app.py`, live templates, live `static/js/main.js` — all unchanged until you approve the merge.
- `instance/club.db` — sha `3591ba52190d5a6d6344f78c33564013008eb772a5334fe17cf6b77b09c1c275`, unchanged.
- All existing backup files `instance/club.db.pre-*` — unchanged.
- Live server PID 35056 on :5000 — never touched.
- Role separation, auth, password hashing — preserved verbatim.
- Existing user `رغد` (ragad@gmail.com) — unchanged.
- Phase 0 + member-dashboard-fix merges from earlier sessions — preserved.

## Awaiting your explicit decision

Please answer the following to proceed with the live merge:

1. **Approve the proposed migration** exactly as listed in "Proposed shared-DB migration — EXACT operations" above? **Yes / No**
2. **Approve the backup + verification plan**? **Yes / No**
3. When ready, confirm "**server stopped, proceed with Phase 2 live merge**".

I will NOT touch live code or the shared DB until I see all three.
