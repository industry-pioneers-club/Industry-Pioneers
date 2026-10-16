"""Phase 4 test matrix: 5 features + regression."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(HERE, '..', 'instance', 'club.phase4-test.db')

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

# Clean start
c = sqlite3.connect(TEST_DB)
c.execute("DELETE FROM membership_request")
c.execute("DELETE FROM event_registration")
c.execute("UPDATE article SET status='approved', reviewed_by=NULL, reviewed_at=NULL")
# Add a 5th 'pending' article for approval tests
c.execute("INSERT INTO article (title,author_name,author_sector,date_published,likes_count,image_path,status) VALUES ('مقال اختبار 4','Phase4 Member','الصناعة',datetime('now'),0,NULL,'pending')")
c.commit()
c.close()

results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

c = sqlite3.connect(TEST_DB).cursor()

# ===== FEATURE 1: Membership (10 tests) =====
op_pub = session()

# M1 submit valid
s, b = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'طالب م1','student_id':'STU-M1','major':'هندسة','email':'m1@test','reason':'نص'}, is_json=True)
check('M1 submit valid -> 201', s == 201 and json.loads(b).get('status') == 'pending', True)

# M2 duplicate pending blocked
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'x','student_id':'STU-M1','major':'y'}, is_json=True)
check('M2 duplicate pending -> 409', s == 409, True)

# M3 missing name -> 400
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'student_id':'STU-X','major':'y'}, is_json=True)
check('M3 missing name -> 400', s == 400, True)

# M4 missing student_id -> 400
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'x','major':'y'}, is_json=True)
check('M4 missing student_id -> 400', s == 400, True)

# M5 missing major -> 400
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'x','student_id':'STU-Y'}, is_json=True)
check('M5 missing major -> 400', s == 400, True)

# M6 unauthenticated approve -> 403
mid = c.execute("SELECT id FROM membership_request WHERE student_id='STU-M1'").fetchone()[0]
op_none = session()
s, _ = req(op_none, f'/leader/membership-requests/{mid}/approve', 'POST')
check('M6 no-cookie approve -> 403', s == 403, True)

# M7 supervisor approve -> 403 (leader-only per spec)
sup_op = login('supervisor@club.com', 'password1234')
s, _ = req(sup_op, f'/leader/membership-requests/{mid}/approve', 'POST')
check('M7 supervisor approve -> 403 (leader-only)', s == 403, True)

# M8 leader approve -> 200 + reviewer recorded + does NOT create user
leader_op = login('leader@club.com', 'password123')
users_before = c.execute("SELECT COUNT(*) FROM user").fetchone()[0]
s, b = req(leader_op, f'/leader/membership-requests/{mid}/approve', 'POST')
d = json.loads(b) if b.startswith('{') else {}
row = c.execute("SELECT status, reviewed_by FROM membership_request WHERE id=?", (mid,)).fetchone()
users_after = c.execute("SELECT COUNT(*) FROM user").fetchone()[0]
check('M8 leader approve 200 + reviewer + no auto user',
      s == 200 and row[0] == 'approved' and row[1] is not None and users_before == users_after and 'signup' in d.get('note',''), True)

# M9 re-approve -> 409
s, _ = req(leader_op, f'/leader/membership-requests/{mid}/approve', 'POST')
check('M9 re-approve already approved -> 409', s == 409, True)

# M10 reject different request + resubmit allowed
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'طالب م2','student_id':'STU-M2','major':'إدارة'}, is_json=True)
mid2 = c.execute("SELECT id FROM membership_request WHERE student_id='STU-M2'").fetchone()[0]
req(leader_op, f'/leader/membership-requests/{mid2}/reject', 'POST')
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'طالب م2','student_id':'STU-M2','major':'إدارة'}, is_json=True)
check('M10 reject + resubmit allowed -> 201', s == 201, True)

# ===== FEATURE 2: Article approval (6 tests) =====
article_pending = c.execute("SELECT id FROM article WHERE title='مقال اختبار 4'").fetchone()[0]

# A1 pending article is HIDDEN from public gazette
s, body = req(session(), '/gazette')
check('A1 pending article hidden from gazette',
      s == 200 and 'مقال اختبار 4' not in body, True)

# A2 existing 4 approved articles still VISIBLE
check('A2 existing articles still visible after backfill',
      'How Local Plants' in body, True)

# A3 member cannot approve
from werkzeug.security import generate_password_hash
mem_op = login('member@phase4.test', 'testpass')
s, _ = req(mem_op, f'/leader/articles/{article_pending}/approve', 'POST')
check('A3 member approve article -> 403', s == 403, True)

# A4 supervisor approve article -> 403 (leader-only)
s, _ = req(sup_op, f'/leader/articles/{article_pending}/approve', 'POST')
check('A4 supervisor approve article -> 403 (leader-only)', s == 403, True)

# A5 leader approve + article becomes visible in gazette
s, _ = req(leader_op, f'/leader/articles/{article_pending}/approve', 'POST')
row = c.execute("SELECT status, reviewed_by FROM article WHERE id=?", (article_pending,)).fetchone()
s2, body2 = req(session(), '/gazette')
check('A5 leader approve article -> 200 + visible in gazette + reviewer recorded',
      s == 200 and row[0] == 'approved' and row[1] is not None and 'مقال اختبار 4' in body2, True)

# A6 duplicate approve -> 409
s, _ = req(leader_op, f'/leader/articles/{article_pending}/approve', 'POST')
check('A6 re-approve article -> 409', s == 409, True)

# ===== FEATURE 3: Event registration (6 tests) =====
public_event_id = c.execute("SELECT id FROM event WHERE is_public=1 LIMIT 1").fetchone()[0]
private_event_id = c.execute("SELECT id FROM event WHERE is_public=0 LIMIT 1").fetchone()[0]

# E1 anonymous registration -> 201
s, b = req(session(), f'/visitor/events/{public_event_id}/register', 'POST',
           {'name':'زائر 1','email':'v1@test','phone':'0501234567'}, is_json=True)
check('E1 anonymous register -> 201', s == 201, True)

# E2 duplicate anonymous (same email+event) -> 409
s, _ = req(session(), f'/visitor/events/{public_event_id}/register', 'POST',
           {'name':'زائر 1','email':'v1@test'}, is_json=True)
check('E2 duplicate anonymous register -> 409', s == 409, True)

# E3 logged-in register
mem_op = login('member@phase4.test', 'testpass')
s, _ = req(mem_op, f'/visitor/events/{public_event_id}/register', 'POST',
           {'name':'عضو','email':'member@phase4.test'}, is_json=True)
reg = c.execute("SELECT user_id FROM event_registration WHERE event_id=? AND email='member@phase4.test'", (public_event_id,)).fetchone()
check('E3 logged-in register -> 201 + user_id set',
      s == 201 and reg is not None and reg[0] is not None, True)

# E4 duplicate logged-in -> 409 (unique index enforced)
s, _ = req(mem_op, f'/visitor/events/{public_event_id}/register', 'POST',
           {'name':'عضو','email':'member@phase4.test'}, is_json=True)
check('E4 duplicate logged-in register -> 409', s == 409, True)

# E5 missing email -> 400
s, _ = req(session(), f'/visitor/events/{public_event_id}/register', 'POST',
           {'name':'x'}, is_json=True)
check('E5 missing email -> 400', s == 400, True)

# E6 non-public event -> 400
s, _ = req(session(), f'/visitor/events/{private_event_id}/register', 'POST',
           {'name':'x','email':'y@test'}, is_json=True)
check('E6 non-public event register -> 400', s == 400, True)

# E7 leader views registrations
s, b = req(leader_op, f'/leader/events/{public_event_id}/registrations')
d = json.loads(b) if b.startswith('{') else {}
check('E7 leader list registrations -> 200 + count=2',
      s == 200 and d.get('count') == 2, True)

# E8 member cannot view registrations
s, _ = req(mem_op, f'/leader/events/{public_event_id}/registrations')
check('E8 member list registrations -> 403', s == 403, True)

# ===== FEATURE 4: Leaderboard by points (4 tests) =====

# L1 /member/leaderboard renders
s, body = req(mem_op, '/member/leaderboard')
check('L1 /member/leaderboard -> 200', s == 200, True)

# L2 ordering: parse row order from HTML, verify highest-points member is rank #1
import re as _re
_rows = _re.findall(r'<td>([^<]+)</td>\s*<td>[^<]*</td>\s*<td><strong[^>]*>(\d+)</strong></td>', body)
# _rows is list of (name, points_str) in render order
first_name = _rows[0][0] if _rows else None
first_points = int(_rows[0][1]) if _rows else -1
check('L2 highest-points member rendered first (Phase4 Member2 / 120)',
      first_name == 'Phase4 Member2' and first_points == 120, True)

# L3 member sees their actual points column
check('L3 leaderboard has points column + value 120',
      'النقاط' in body and '>120<' in body, True)

# L4 only role='member' shown (no leader/supervisor)
check('L4 leader/supervisor NOT shown',
      'leader@club.com' not in body and 'supervisor@club.com' not in body, True)

# ===== FEATURE 5: Committee UI (4 tests) =====

# C1 leader dashboard has committee section
s, body = req(leader_op, '/leader/dashboard')
check('C1 leader dashboard has committee section',
      s == 200 and 'إدارة اللجان' in body and 'data-save-committee' in body, True)

# C2 leader assigns a committee
mem_id = c.execute("SELECT id FROM user WHERE email='member@phase4.test'").fetchone()[0]
s, b = req(leader_op, f'/leader/members/{mem_id}/committee', 'POST',
           {'committee':'لجنة البرمجة'})
d = json.loads(b) if b.startswith('{') else {}
updated = c.execute("SELECT committee FROM user WHERE id=?", (mem_id,)).fetchone()[0]
check('C2 leader assigns committee -> saved',
      s == 200 and d.get('committee') == 'لجنة البرمجة' and updated == 'لجنة البرمجة', True)

# C3 supervisor can also assign (per existing permission)
s, _ = req(sup_op, f'/leader/members/{mem_id}/committee', 'POST',
           {'committee':'لجنة التصميم'})
check('C3 supervisor can assign committee -> 200', s == 200, True)

# C4 member cannot assign
s, _ = req(mem_op, f'/leader/members/{mem_id}/committee', 'POST',
           {'committee':'HACK'})
check('C4 member assign committee -> 403', s == 403, True)

# ===== REGRESSION (5 tests) =====

# R1 login still works
op_reg = session()
s, _ = req(op_reg, '/login', 'POST', {'email':'leader@club.com','password':'password123'}, is_json=True)
check('R1 login still works -> 200', s == 200, True)

# R2 leader dashboard renders
s, _ = req(op_reg, '/leader/dashboard')
check('R2 leader dashboard -> 200', s == 200, True)

# R3 task approval route still works (Phase 2B)
# Reset the one existing task for cleanliness
c2 = sqlite3.connect(TEST_DB)
c2.execute("UPDATE task SET status='مكتملة', approval_status='pending' WHERE id=1")
c2.commit(); c2.close()
# approve it
s, _ = req(op_reg, '/leader/tasks/1/approve', 'POST')
check('R3 task approval still works -> 200', s == 200, True)

# R4 event create still works
s, _ = req(op_reg, '/leader/events', 'POST',
           {'title':'فعالية regression','date':'2027-12-01','time':'10:00','is_public':'1'})
check('R4 event create still works -> 201', s == 201, True)

# R5 member dashboard still renders with points + activity
mem_op2 = login('member@phase4.test', 'testpass')
s, body = req(mem_op2, '/member/profile')
check('R5 member dashboard renders with name + points',
      s == 200 and 'member@phase4.test' in body and 'نقطة' in body, True)

# ===== Report =====
print(f'{"test":<60} pass')
print('-' * 70)
all_pass = True
groups = {}
for name, got, want, ok in results:
    all_pass = all_pass and ok
    group = name[:2] if name[1].isdigit() or name[1] == name[1].upper() else name[0]
    groups.setdefault(group, [0,0])
    groups[group][0] += 1
    if ok: groups[group][1] += 1
    msg = 'PASS' if ok else f'FAIL (got={got} want={want})'
    print(f'{name:<60} {msg}')
print()
print('ALL PASS' if all_pass else 'FAILURES PRESENT')
print()
print('Group breakdowns:')
for g in sorted(groups):
    tot, p = groups[g]
    print(f'  {g}: {p}/{tot}')
sys.exit(0 if all_pass else 1)
