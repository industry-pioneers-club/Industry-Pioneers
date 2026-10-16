"""Phase 2B test matrix: approval workflow + activity log + points award + duplicate guard."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(HERE, '..', 'instance', 'club.phase2b-test.db')

def session():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def req(opener, path, method='GET', data=None, is_json=False):
    headers = {'Accept': 'application/json'}
    body = None
    if data is not None:
        if is_json:
            body = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        else:
            body = urllib.parse.urlencode(data).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with opener.open(r) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')

def login(email, password):
    op = session()
    s, _ = req(op, '/login', 'POST', {'email': email, 'password': password}, is_json=True)
    assert s == 200, f'login failed {email}: {s}'
    return op

def reset_test_state():
    c = sqlite3.connect(TEST_DB)
    c.execute("UPDATE user SET points=0, committee=NULL WHERE email='p2a-member@test.local'")
    c.execute("UPDATE task SET status='مكتملة', approval_status='pending', approved_by=NULL, approved_at=NULL WHERE title='مهمة اختبار 2B'")
    c.execute("DELETE FROM activity_log WHERE user_id=(SELECT id FROM user WHERE email='p2a-member@test.local')")
    c.commit()
    c.close()

reset_test_state()

results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

c = sqlite3.connect(TEST_DB).cursor()
mid = c.execute("SELECT id FROM user WHERE email='p2a-member@test.local'").fetchone()[0]
tid = c.execute("SELECT id FROM task WHERE title='مهمة اختبار 2B'").fetchone()[0]

# B1
cols = [r[1] for r in c.execute('PRAGMA table_info(task)').fetchall()]
check('B1 task has approval_status/approved_by/approved_at',
      all(x in cols for x in ('approval_status','approved_by','approved_at')), True)
# B2
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
check('B2 activity_log table exists', 'activity_log' in tables, True)
# B3
idx = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
check('B3 uq_activity_task_approved index exists', 'uq_activity_task_approved' in idx, True)

# B4: leader approves -> 200 + points=25 + 1 log entry
leader_op = login('leader@club.com', 'password123')
s, body = req(leader_op, f'/leader/tasks/{tid}/approve', 'POST')
d = json.loads(body) if body.startswith('{') else {}
new_points = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log_count = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_approved'", (mid,)).fetchone()[0]
check('B4 leader approves 200 + points=25 + 1 log entry',
      s == 200 and new_points == 25 and log_count == 1 and d.get('assignee_points') == 25, True)

# B5: duplicate approve -> 409 + points unchanged
s, body = req(leader_op, f'/leader/tasks/{tid}/approve', 'POST')
new_points2 = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
check('B5 duplicate approve 409 + points unchanged',
      s == 409 and new_points2 == 25, True)

# B6: member dashboard shows updated points + activity entry
member_op = login('p2a-member@test.local', 'testpass')
s, body = req(member_op, '/member/profile')
check('B6 member dashboard shows 25 points + activity entry',
      s == 200 and '25' in body and 'اعتماد مهمة' in body and 'مهمة اختبار 2B' in body, True)

# B7: reset + leader rejects -> 200 + points not awarded + rejection logged
reset_test_state()
s, body = req(leader_op, f'/leader/tasks/{tid}/reject', 'POST')
pts_after = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log_rej = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_rejected'", (mid,)).fetchone()[0]
check('B7 leader rejects 200 + points=0 + 1 reject log',
      s == 200 and pts_after == 0 and log_rej == 1, True)

# B8: cannot reject after already approved
reset_test_state()
req(leader_op, f'/leader/tasks/{tid}/approve', 'POST')
s, _ = req(leader_op, f'/leader/tasks/{tid}/reject', 'POST')
check('B8 cannot reject approved task 409', s == 409, True)

# B9: member cannot approve
reset_test_state()
member_op = login('p2a-member@test.local', 'testpass')
s, _ = req(member_op, f'/leader/tasks/{tid}/approve', 'POST')
check('B9 member -> /approve 403', s == 403, True)

# B10: no cookie -> 403
op_no = session()
s, _ = req(op_no, f'/leader/tasks/{tid}/approve', 'POST')
check('B10 no-cookie -> /approve 403', s == 403, True)

# B11: nonexistent task -> 404
s, _ = req(leader_op, '/leader/tasks/999999/approve', 'POST')
check('B11 nonexistent task approve -> 404', s == 404, True)

# B12: unassigned task -> 400
c2 = sqlite3.connect(TEST_DB)
c2.execute("DELETE FROM task WHERE title='orphan'")
c2.execute("INSERT INTO task (title,points,status,assigned_user_id,approval_status,created_at) VALUES ('orphan',5,'مكتملة',NULL,'pending',datetime('now'))")
orphan_id = c2.execute("SELECT id FROM task WHERE title='orphan'").fetchone()[0]
c2.commit(); c2.close()
s, _ = req(leader_op, f'/leader/tasks/{orphan_id}/approve', 'POST')
check('B12 unassigned task approve -> 400', s == 400, True)

# B13: supervisor can also approve
reset_test_state()
sup_op = login('supervisor@club.com', 'password1234')
s, _ = req(sup_op, f'/leader/tasks/{tid}/approve', 'POST')
check('B13 supervisor can approve', s == 200, True)

# B14: strict role separation preserved
s, _ = req(sup_op, '/leader/dashboard')
check('B14 supervisor /leader/dashboard 403', s == 403, True)

# B15: disk persistence — read directly from DB
pts = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_approved'", (mid,)).fetchone()[0]
check('B15 persistence on disk: points=25, 1 approve log', pts == 25 and log == 1, True)

reset_test_state()
print(f'{"test":<60} pass')
print('-' * 68)
all_pass = True
for name, got, want, ok in results:
    all_pass = all_pass and ok
    msg = 'PASS' if ok else f'FAIL (got={got} want={want})'
    print(f'{name:<60} {msg}')
print()
print('ALL PASS' if all_pass else 'FAILURES PRESENT')
sys.exit(0 if all_pass else 1)
