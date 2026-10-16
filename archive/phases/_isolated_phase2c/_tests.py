"""Phase 2C test matrix: tasks grouped by event + approval badges on member tasks."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(HERE, '..', 'instance', 'club.phase2c-test.db')

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

results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

op = login('p2a-member@test.local', 'testpass')
s, body = req(op, '/member/tasks')

# C1: page renders
check('C1 /member/tasks 200', s == 200, True)

# C2: event groups rendered (should contain titles like Factory Floor Open Day etc.)
c = sqlite3.connect(TEST_DB).cursor()
event_titles = [r[0] for r in c.execute("SELECT title FROM event WHERE id IN (SELECT DISTINCT event_id FROM task WHERE assigned_user_id=(SELECT id FROM user WHERE email='p2a-member@test.local') AND event_id IS NOT NULL)").fetchall()]
check('C2 event groups appear',
      all(t in body for t in event_titles), True)

# C3: tasks list contains all task titles
expected_titles = ['مهمة اختبار 2B', 'مهمة أ', 'مهمة ب', 'مهمة ج', 'مهمة بلا فعالية']
check('C3 all task titles rendered',
      all(t in body for t in expected_titles), True)

# C4: null-event bucket rendered
check('C4 null-event bucket rendered', 'مهام عامة (بدون فعالية)' in body, True)

# C5: approval badges rendered
has_approved_badge = '✓ معتمد' in body
has_rejected_badge = '✗ مرفوض' in body
has_pending_badge = 'قيد المراجعة' in body
check('C5 all 3 approval badges rendered',
      has_approved_badge and has_rejected_badge and has_pending_badge, True)

# C6: approved tasks do NOT get the status-update dropdown
# Our 'مهمة ب' is approved. Verify no data-update-status for that task.
tid_approved = c.execute("SELECT id FROM task WHERE title='مهمة ب'").fetchone()[0]
has_update_btn = f'data-update-status="{tid_approved}"' in body
check('C6 approved task has no status-update button', not has_update_btn, True)

# C7: pending task HAS the update button
tid_pending = c.execute("SELECT id FROM task WHERE title='مهمة أ'").fetchone()[0]
check('C7 pending task has status-update button',
      f'data-update-status="{tid_pending}"' in body, True)

# Report
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
