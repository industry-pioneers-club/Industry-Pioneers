# Phase 0 — Live Integration Steps (requires server stop)

This document describes exactly what will happen to go from the current state
(Tier 1 tested in isolation on `instance/club.event-test.db`) to Tier 1
features live on `instance/club.db` via port 5000.

**I will not execute any of this without your explicit "proceed" per step,
and you must stop the project server (PID 43692) before I begin step 3.**

---

## Why the server must stop first

`app.py` currently runs via `app.run(debug=True)` which enables Werkzeug's
auto-reloader. The reloader watches every `.py` file in the project directory
and restarts the process when any one of them is edited. On restart,
`initialize_database()` runs against the shared DB (`instance/club.db`).

If I edit `app.py` while the server is running:
1. Reloader restarts the server.
2. `initialize_database()` runs — includes `db.create_all()`.
3. Phase 0 adds no new tables, so `db.create_all()` is a no-op; no schema
   change would land.
4. The 3 seed functions all check for existing rows and return — no row
   change.
5. So in principle Phase 0 editing while the server is up would be safe.

BUT:
- The team's rule is explicit: "do not stop or restart any running process
  without my explicit authorization" and "do not modify the shared database
  without my explicit approval."
- A reloader restart is a server restart.
- A reloader restart runs code against the shared DB, even if that code
  happens to be a no-op.

Per the rules, you stop the server; I edit; you restart.

---

## Files that will change on merge (Phase 0 only)

| File | Change |
|---|---|
| `app.py` | Replace `member_tasks()` body with the DB query from `_app_tier1.py` lines 657-682. Add `_ALLOWED_TASK_STATUSES` tuple and `update_my_task_status()` route (both already defined in `_app_tier1.py`). Add `signup_form()` route. 3 code blocks, ~45 lines total added, ~10 lines removed. |
| `templates/login.html` | Add 1 anchor line below the submit button pointing to `/signup`. |
| `templates/tasks.html` | Replace with the content of `templates/tasks_tier1.html` (which uses real Task fields). |
| `static/js/main.js` | Append the two handlers from `main_tier1.js` (signup form + task status update). |

## Files that will be deleted after merge (test scaffolding)

| File | Reason |
|---|---|
| `_app_tier1.py` | Content merged into `app.py` |
| `_test_server_tier1.py` | No longer needed |
| `templates/tasks_tier1.html` | Content moved into `templates/tasks.html` |
| `static/js/main_tier1.js` | Content merged into `static/js/main.js` |
| `_phase0_tests.py` | Phase 0 test runner, no longer needed |

Keep:
- `templates/signup.html` — now a live template referenced by `app.py`.
- `_backup_db.py` — ongoing utility.
- `_test_server.py` — ongoing dev utility (not Tier 1 specific).
- All backup files `instance/club.db.pre-*` — safety record.

---

## No schema change in Phase 0

Phase 0 does NOT add any columns or tables to the shared DB. The `task`
table already has `assigned_user_id` and `status` columns. The three new
routes read/write only existing columns.

**Shared DB sha before and after Phase 0 should be IDENTICAL** (unless
your server was separately interacting with the DB).

---

## Step-by-step merge procedure

### Phase 0.A — You do (before I start)

1. Decide a time when the project server can be briefly offline (~30 sec).
2. In the terminal running the project server, press `Ctrl+C` (or close the
   terminal). Confirm port 5000 is clear.
3. Tell me "server stopped, proceed with Phase 0 merge".

### Phase 0.B — I do (automated, with your "proceed")

4. Capture `shared sha BEFORE` and store it. No DB write.
5. Create new backup `instance/club.db.pre-phase0-merge` via SQLite online
   backup API. Verify integrity + row counts.
6. Edit `app.py`:
   - Replace the `member_tasks()` body with the real-DB query.
   - Add `_ALLOWED_TASK_STATUSES` constant.
   - Add `update_my_task_status()` route.
   - Add `signup_form()` route.
7. Edit `templates/login.html` to add the signup link.
8. Replace `templates/tasks.html` with the content of
   `templates/tasks_tier1.html` (template reference updated to `tasks.html`).
9. Append `main_tier1.js` handlers into `main.js` and update their template
   loader references.
10. Delete `_app_tier1.py`, `_test_server_tier1.py`,
    `templates/tasks_tier1.html`, `static/js/main_tier1.js`,
    `_phase0_tests.py`.
11. Run `python -c "import py_compile; py_compile.compile('app.py', doraise=True)"`
    and `node -c static/js/main.js`.
12. Capture `shared sha AFTER edits`. Must equal `BEFORE` — no DB writes
    occurred.

### Phase 0.C — You do

13. Restart the project server: `python app.py` (debug server restarts the
    Werkzeug reloader; this is normal and expected).
14. Verify in your browser:
    - `GET /signup` renders the signup form.
    - `GET /login` has a "ليس لديك حساب؟ سجل الآن" link.
    - Login as leader; `GET /member/tasks` shows the real "زياره" task from
      the DB (not the old hard-coded 3-item list).
    - Click "تحديث الحالة" on the task; it posts to the new route and
      updates the badge.

### Phase 0.D — I do (verify shared DB post-restart)

15. On your word that the server is running, I'll fetch `/healthz` and the
    public pages read-only.
16. Capture `shared sha AFTER restart`. Expected: unchanged, because the
    reloader fired `initialize_database()` → seed functions all noop +
    `db.create_all()` is a no-op (no new tables).

---

## Rollback plan (if anything fails during Phase 0.B)

Each edit is a single `Edit` tool call. I will NOT amend to fix a broken
edit; I will:
1. Stop and tell you.
2. Describe the exact state of each file.
3. Wait for your instruction.

If the merge is partway through and you want to abort:
- You already have `instance/club.db.pre-phase0-merge` as a DB backup.
- The code edits are text-level reversible by re-pasting from this document.
- No shared DB write would have occurred (the edits don't open the DB).

---

## What's NOT in Phase 0

Phase 0 is **integration of already-tested features only.** It does NOT
add:
- Article approval workflow (Phase 1)
- Points ledger (Phase 2)
- Committees (Phase 3)
- Activity log (Phase 4)
- Any new DB column or table
- Any schema migration

Those are later phases, each proposed and approved separately.

---

## Phase 0 test results (reference)

### Tier 1 (A1-A12): all PASS on `instance/club.event-test.db`
- A1: `GET /signup` unauth → 200 + Arabic form
- A2: `POST /register` new visitor → 201
- A3: duplicate email → 409
- A4: missing password → 400
- A5: valid invite code → 201 + role=member
- A6: no invite → role=visitor
- A7: member sees own TEST TASK, not leader's "زياره"
- A8: visitor → `/member/tasks` → 403
- A9: member updates own task → 200 + DB updated to "مكتملة"
- A10: member → other's task → 403 (ownership check works)
- A11: member → nonexistent task → 404
- A12: member → invalid status "garbage" → 400

### Regression (B1-B10): all PASS
- B1-B5: public pages (home, about, events, gazette, partners) → 200
- B6: leader login → 200
- B7: leader → `/leader/dashboard` → 200
- B8: leader → `/supervisor/dashboard` → 403 (strict separation preserved)
- B9: supervisor stats → 200 + correct JSON shape
- B10: leader → `/leader/tasks` → 200

### Persistence across server restart
- TEST TASK status "مكتملة" survived test server stop + start.
- Previously-registered test user `mem1@test.local` could still log in
  after restart.

### Shared DB impact
- Before Phase 0 testing: `6559d9e0ce587089522e0b2d7ebd8d4153dbb16e9391189fd95085b0610cbe97`
- After Phase 0 testing:  `6559d9e0ce587089522e0b2d7ebd8d4153dbb16e9391189fd95085b0610cbe97`
- **Identical. No write occurred.**

---

## Ready to merge

Phase 0 integration is **tested and ready to merge.** It requires:
- 2-3 minutes of server downtime (steps 0.A and 0.C).
- Your explicit "proceed" at the start of 0.B.
- Your explicit "server stopped" between 0.A and 0.B.

Once you give both signals, the merge is a sequence of file edits with no
DB writes.
