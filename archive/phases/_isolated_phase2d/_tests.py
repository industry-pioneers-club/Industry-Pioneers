"""Phase 2D test matrix: leader approval UI, pending-approval section,
end-to-end approve/reject flow, duplicate-award prevention."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(HERE, '..', 'instance', 'club.phase2d-test.db')

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

def reset_state():
    c = sqlite3.connect(TEST_DB)
    mid = c.execute("SELECT id FROM user WHERE email='p2a-member@test.local'").fetchone()[0]
    c.execute("UPDATE user SET points=0 WHERE id=?", (mid,))
    c.execute("DELETE FROM activity_log WHERE user_id=?", (mid,))
    c.execute("UPDATE task SET approval_status='pending', approved_by=NULL, approved_at=NULL WHERE assigned_user_id=?", (mid,))
    c.execute("UPDATE task SET status='مكتملة' WHERE title IN ('مهمة اختبار 2B','مهمة أ')")
    c.execute("UPDATE task SET status='قيد التنفيذ' WHERE title NOT IN ('مهمة اختبار 2B','مهمة أ') AND assigned_user_id=?", (mid,))
    c.commit()
    c.close()

reset_state()
results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

c = sqlite3.connect(TEST_DB).cursor()
mid = c.execute("SELECT id FROM user WHERE email='p2a-member@test.local'").fetchone()[0]
tid_a = c.execute("SELECT id FROM task WHERE title='مهمة اختبار 2B'").fetchone()[0]
tid_b = c.execute("SELECT id FROM task WHERE title='مهمة أ'").fetchone()[0]

leader_op = login('leader@club.com', 'password123')
s, body = req(leader_op, '/leader/dashboard')
check('D1 leader dashboard 200 + pending section present',
      s == 200 and 'اعتماد مهام الأعضاء' in body and 'pendingApprovalList' in body, True)

check('D2 pending section lists both tasks + buttons',
      'مهمة اختبار 2B' in body and 'مهمة أ' in body
      and f'data-approve-task="{tid_a}"' in body
      and f'data-reject-task="{tid_a}"' in body
      and f'data-approve-task="{tid_b}"' in body, True)

s, b = req(leader_op, f'/leader/tasks/{tid_a}/approve', 'POST')
d = json.loads(b) if b.startswith('{') else {}
pts = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log1 = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_approved'", (mid,)).fetchone()[0]
check('D3 approve task A -> 200 + points=25 + 1 log',
      s == 200 and d.get('points_awarded') == 25 and pts == 25 and log1 == 1, True)

s, b = req(leader_op, f'/leader/tasks/{tid_b}/approve', 'POST')
d = json.loads(b) if b.startswith('{') else {}
pts2 = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log2 = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_approved'", (mid,)).fetchone()[0]
check('D4 approve task B -> 200 + points=35 + 2 logs',
      s == 200 and d.get('points_awarded') == 10 and pts2 == 35 and log2 == 2, True)

s, b = req(leader_op, f'/leader/tasks/{tid_a}/approve', 'POST')
pts3 = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log3 = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_approved'", (mid,)).fetchone()[0]
check('D5 duplicate approve -> 409 + points still 35 + still 2 logs',
      s == 409 and pts3 == 35 and log3 == 2, True)

s, body = req(leader_op, '/leader/dashboard')
check('D6 approved tasks removed from pending section',
      s == 200
      and f'data-pending-task-id="{tid_a}"' not in body
      and f'data-pending-task-id="{tid_b}"' not in body, True)

reset_state()
s, b = req(leader_op, f'/leader/tasks/{tid_a}/reject', 'POST')
pts4 = c.execute("SELECT points FROM user WHERE id=?", (mid,)).fetchone()[0]
log_rej = c.execute("SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action='task_rejected'", (mid,)).fetchone()[0]
check('D7 reject -> 200 + points=0 + 1 reject log',
      s == 200 and pts4 == 0 and log_rej == 1, True)

reset_state()
req(leader_op, f'/leader/tasks/{tid_a}/approve', 'POST')
s, _ = req(leader_op, f'/leader/tasks/{tid_a}/reject', 'POST')
check('D8 reject after approve -> 409', s == 409, True)

reset_state()
member_op = login('p2a-member@test.local', 'testpass')
s, _ = req(member_op, f'/leader/tasks/{tid_a}/approve', 'POST')
check('D9 member -> approve 403', s == 403, True)

op_none = session()
s, _ = req(op_none, f'/leader/tasks/{tid_a}/approve', 'POST')
check('D10 no-cookie -> approve 403', s == 403, True)

reset_state()
sup_op = login('supervisor@club.com', 'password1234')
s, _ = req(sup_op, f'/leader/tasks/{tid_a}/approve', 'POST')
check('D11 supervisor approve -> 200', s == 200, True)

reset_state()
req(leader_op, f'/leader/tasks/{tid_a}/approve', 'POST')
member_op = login('p2a-member@test.local', 'testpass')
s, body = req(member_op, '/member/profile')
check('D12 member dashboard shows 25 points + task_approved activity',
      s == 200 and '25' in body and 'اعتماد مهمة' in body and 'مهمة اختبار 2B' in body, True)

s, _ = req(member_op, '/leader/dashboard')
check('D13 member -> /leader/dashboard 403', s == 403, True)

s, _ = req(sup_op, '/leader/dashboard')
check('D14 supervisor -> /leader/dashboard 403', s == 403, True)

s, _ = req(leader_op, '/leader/tasks/999999/approve', 'POST')
check('D15 approve nonexistent -> 404', s == 404, True)

reset_state()
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
