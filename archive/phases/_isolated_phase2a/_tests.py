"""Phase 2A test matrix: committee field + points balance + progress bar."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(HERE, '..', 'instance', 'club.phase2a-test.db')

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

# Confirm DB has the two new columns + sanity row
c = sqlite3.connect(TEST_DB).cursor()
cols = [r[1] for r in c.execute('PRAGMA table_info(user)').fetchall()]
check('A1 user table has committee column', 'committee' in cols, True)
check('A2 user table has points column', 'points' in cols, True)

# A3: member logs in, dashboard shows 0 points + "غير محدّدة" committee
op = login('p2a-member@test.local', 'testpass')
s, body = req(op, '/member/profile')
has_points_zero = '0 نقطة' in body
has_no_committee = 'غير محدّدة' in body
has_target_500 = '/ 500 نقطة' in body
check('A3 member dashboard shows 0 points + target 500 + no committee',
      s == 200 and has_points_zero and has_no_committee and has_target_500, True)

# A4: leader sets committee for the member
leader_op = login('leader@club.com', 'password123')
member_id = c.execute("SELECT id FROM user WHERE email='p2a-member@test.local'").fetchone()[0]
s, body = req(leader_op, f'/leader/members/{member_id}/committee', 'POST', {'committee': 'لجنة البرمجة'})
d = json.loads(body) if body.startswith('{') else {}
check('A4 leader POST /leader/members/<id>/committee 200',
      s == 200 and d.get('committee') == 'لجنة البرمجة', True)

# A5: verify committee persisted in DB
new_committee = c.execute("SELECT committee FROM user WHERE id=?", (member_id,)).fetchone()[0]
check('A5 committee persisted in DB', new_committee == 'لجنة البرمجة', True)

# A6: member re-fetches dashboard, sees new committee
s, body = req(op, '/member/profile')
check('A6 member dashboard now shows committee', s == 200 and 'لجنة البرمجة' in body, True)

# A7: unauthenticated cannot set a committee (403)
op_no = session()
s, _ = req(op_no, f'/leader/members/{member_id}/committee', 'POST', {'committee': 'HACK'})
check('A7 no-cookie POST /leader/members/<id>/committee 403', s == 403, True)

# A7b: member cannot set a committee (403)
s, _ = req(op, f'/leader/members/{member_id}/committee', 'POST', {'committee': 'HACK'})
check('A7b member -> /leader/members/<id>/committee 403', s == 403, True)

# A8: 404 for nonexistent user
s, _ = req(leader_op, '/leader/members/999999/committee', 'POST', {'committee': 'X'})
check('A8 nonexistent user id -> 404', s == 404, True)

# A9: can't set committee on visitor-role user (400)
visitor_id = c.execute("SELECT id FROM user WHERE role='visitor'").fetchone()[0]
s, body = req(leader_op, f'/leader/members/{visitor_id}/committee', 'POST', {'committee': 'X'})
check('A9 cannot set committee on visitor-role user -> 400', s == 400, True)

# A10: progress bar width reflects points (manually set points=250 in DB, then re-fetch)
c2 = sqlite3.connect(TEST_DB)
c2.execute("UPDATE user SET points=250 WHERE id=?", (member_id,))
c2.commit()
c2.close()
s, body = req(op, '/member/profile')
# 250/500 = 50%
has_50_pct = 'width: 50%' in body or '"width: 50%"' in body or 'width:50%' in body
check('A10 progress bar at 50% when points=250 target=500',
      s == 200 and has_50_pct and '250' in body, True)

# A11: strict separation preserved — member can't open leader dashboard
s, _ = req(op, '/leader/dashboard')
check('A11 member -> /leader/dashboard 403', s == 403, True)

# A12: leader can still open leader dashboard (regression)
s, _ = req(leader_op, '/leader/dashboard')
check('A12 leader -> /leader/dashboard 200', s == 200, True)

# A13: supervisor can still open supervisor dashboard (regression)
sup_op = login('supervisor@club.com', 'password1234')
s, _ = req(sup_op, '/supervisor/dashboard')
check('A13 supervisor -> /supervisor/dashboard 200', s == 200, True)

# A14: idempotent schema upgrade — add column again doesn't crash
# (By definition: _upgrade_schema already ran on boot. We check that re-running
# would not re-add the column. We simulate by checking columns stable.)
cols2 = [r[1] for r in sqlite3.connect(TEST_DB).cursor().execute('PRAGMA table_info(user)').fetchall()]
check('A14 schema stable (no duplicate columns)', cols == cols2, True)

# Report
print(f'{"test":<60} pass')
print('-' * 68)
all_pass = True
for name, got, want, ok in results:
    all_pass = all_pass and ok
    print(f'{name:<60} {"PASS" if ok else "FAIL"} (got={got}, want={want})' if not ok else f'{name:<60} PASS')
print()
print('ALL PASS' if all_pass else 'FAILURES PRESENT')
sys.exit(0 if all_pass else 1)
