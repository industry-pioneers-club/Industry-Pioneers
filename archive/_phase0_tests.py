"""Phase 0 verification: Tier 1 (A1-A12) + regression (B1-B10)."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
TEST_DB = 'instance/club.event-test.db'

def session():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def req(opener, path, method='GET', data=None, is_json=False):
    headers = {'Accept': 'application/json'}
    body = None
    if data is not None:
        if is_json:
            body = json.dumps(data).encode('utf-8'); headers['Content-Type'] = 'application/json'
        else:
            body = urllib.parse.urlencode(data).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with opener.open(r) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')

results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

# Clean up any lingering test registrations (test DB only)
c = sqlite3.connect(TEST_DB)
c.execute("DELETE FROM user WHERE email LIKE '%@test.local'")
c.commit()
c.close()

# ===== TIER 1 =====
op = session()
s, body = req(op, '/signup')
check('A1 GET /signup unauth 200+form', s == 200 and 'إنشاء حساب' in body, True)

op = session()
s, _ = req(op, '/register', 'POST',
           {'name': 'VISITOR', 'email': 'visitor1@test.local', 'password': 'password12'}, is_json=True)
check('A2 POST /register visitor 201', s == 201, True)

s, _ = req(op, '/register', 'POST',
           {'name': 'DUP', 'email': 'visitor1@test.local', 'password': 'password12'}, is_json=True)
check('A3 POST /register duplicate 409', s == 409, True)

s, _ = req(op, '/register', 'POST',
           {'name': 'X', 'email': 'x@test.local'}, is_json=True)
check('A4 POST /register missing password 400', s == 400, True)

s, b = req(op, '/register', 'POST',
           {'name': 'M1', 'email': 'mem1@test.local', 'password': 'password12', 'invite_code': 'PIONEERS2026'},
           is_json=True)
d = json.loads(b) if b.startswith('{') else {}
check('A5 POST /register invite -> role=member', s == 201 and d.get('role') == 'member', True)

s, b = req(op, '/register', 'POST',
           {'name': 'V2', 'email': 'vis2@test.local', 'password': 'password12'}, is_json=True)
d = json.loads(b) if b.startswith('{') else {}
check('A6 POST /register no invite -> role=visitor', s == 201 and d.get('role') == 'visitor', True)

c = sqlite3.connect(TEST_DB).cursor()
member_task_id = c.execute(
    "SELECT id FROM task WHERE assigned_user_id=(SELECT id FROM user WHERE email='member-test@club.test')"
).fetchone()[0]
leader_task_id = c.execute(
    "SELECT id FROM task WHERE assigned_user_id=(SELECT id FROM user WHERE email='leader@club.com')"
).fetchone()[0]
c.close()

op_m = session()
s, _ = req(op_m, '/login', 'POST',
           {'email': 'member-test@club.test', 'password': 'testpass'}, is_json=True)
assert s == 200, f'member login failed: {s}'
s, body = req(op_m, '/member/tasks')
check('A7 member sees own task not others',
      s == 200 and 'TEST TASK' in body and 'زياره' not in body, True)

op_v = session()
req(op_v, '/login', 'POST', {'email': 'vis2@test.local', 'password': 'password12'}, is_json=True)
s, _ = req(op_v, '/member/tasks')
check('A8 visitor -> /member/tasks 403', s == 403, True)

c = sqlite3.connect(TEST_DB)
c.execute("UPDATE task SET status=? WHERE id=?", ('قيد التنفيذ', member_task_id))
c.commit()
c.close()

s, b = req(op_m, f'/member/tasks/{member_task_id}/status', 'POST', {'status': 'مكتملة'})
d = json.loads(b) if b.startswith('{') else {}
c = sqlite3.connect(TEST_DB).cursor()
new_status = c.execute("SELECT status FROM task WHERE id=?", (member_task_id,)).fetchone()[0]
c.close()
check('A9 member updates own task 200+DB updated',
      s == 200 and d.get('status') == 'مكتملة' and new_status == 'مكتملة', True)

s, _ = req(op_m, f'/member/tasks/{leader_task_id}/status', 'POST', {'status': 'مكتملة'})
check('A10 member -> others task 403', s == 403, True)

s, _ = req(op_m, '/member/tasks/999999/status', 'POST', {'status': 'مكتملة'})
check('A11 member -> nonexistent task 404', s == 404, True)

s, _ = req(op_m, f'/member/tasks/{member_task_id}/status', 'POST', {'status': 'garbage'})
check('A12 member -> invalid status 400', s == 400, True)

# ===== REGRESSION =====
op = session()
s, _ = req(op, '/')
check('B1 GET / 200', s == 200, True)
s, _ = req(op, '/about')
check('B2 GET /about 200', s == 200, True)
s, _ = req(op, '/events')
check('B3 GET /events 200', s == 200, True)
s, _ = req(op, '/gazette')
check('B4 GET /gazette 200', s == 200, True)
s, _ = req(op, '/partners')
check('B5 GET /partners 200', s == 200, True)

op_l = session()
s, _ = req(op_l, '/login', 'POST',
           {'email': 'leader@club.com', 'password': 'password123'}, is_json=True)
check('B6 leader login 200', s == 200, True)
s, _ = req(op_l, '/leader/dashboard')
check('B7 leader -> /leader/dashboard 200', s == 200, True)
s, _ = req(op_l, '/supervisor/dashboard')
check('B8 leader -> /supervisor/dashboard 403', s == 403, True)

op_s = session()
req(op_s, '/login', 'POST',
    {'email': 'supervisor@club.com', 'password': 'password1234'}, is_json=True)
s, body = req(op_s, '/supervisor/stats')
d = json.loads(body) if body.startswith('{') else {}
check('B9 supervisor stats JSON', s == 200 and 'events' in d and 'articles' in d, True)

s, _ = req(op_l, '/leader/tasks')
check('B10 leader /leader/tasks 200', s == 200, True)

# ===== REPORT =====
print(f'{"test":<55} {"got":<8} {"want":<8} pass')
print('-' * 85)
all_pass = tier1_pass = regression_pass = True
for name, got, want, ok in results:
    all_pass &= ok
    if name.startswith('A'): tier1_pass &= ok
    if name.startswith('B'): regression_pass &= ok
    print(f'{name:<55} {str(got)[:7]:<8} {str(want)[:7]:<8} {"PASS" if ok else "FAIL"}')
print()
print(f'Tier 1 (A1-A12):     {"ALL PASS" if tier1_pass else "FAILURES"}')
print(f'Regression (B1-B10): {"ALL PASS" if regression_pass else "FAILURES"}')
print(f'Overall:             {"ALL PASS" if all_pass else "FAILURES PRESENT"}')
sys.exit(0 if all_pass else 1)
