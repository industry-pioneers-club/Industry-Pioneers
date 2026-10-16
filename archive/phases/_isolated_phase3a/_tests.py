"""Phase 3A test matrix: membership form persistence + leader approve/reject +
duplicate guard + role separation + decision immutability."""
import sys, urllib.request, urllib.parse, json, http.cookiejar, sqlite3, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'
HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(HERE, '..', 'instance', 'club.phase3a-test.db')

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

# Clean slate for the membership table
c = sqlite3.connect(TEST_DB)
c.execute("DELETE FROM membership_request")
c.commit()
c.close()

results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

# ===== Public submission =====

# T1: public submission works, 201 + row persists
op_pub = session()
s, body = req(op_pub, '/visitor/membership-request', 'POST',
              {'name':'طالب تجريبي','student_id':'STU-100','major':'هندسة','email':'t@test.local','reason':'أريد المشاركة'},
              is_json=True)
d = json.loads(body) if body.startswith('{') else {}
c = sqlite3.connect(TEST_DB).cursor()
count = c.execute("SELECT COUNT(*) FROM membership_request").fetchone()[0]
check('T1 public submit -> 201 + 1 row persisted', s == 201 and count == 1 and d.get('status') == 'pending', True)

# T2: duplicate (same student_id, still pending) -> 409
s, body = req(op_pub, '/visitor/membership-request', 'POST',
              {'name':'طالب تجريبي','student_id':'STU-100','major':'هندسة'}, is_json=True)
count2 = c.execute("SELECT COUNT(*) FROM membership_request").fetchone()[0]
check('T2 duplicate pending submission -> 409 + no new row',
      s == 409 and count2 == 1, True)

# T3: missing name -> 400
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'student_id':'STU-200','major':'هندسة'}, is_json=True)
check('T3 missing name -> 400', s == 400, True)

# T4: missing student_id -> 400
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'x','major':'y'}, is_json=True)
check('T4 missing student_id -> 400', s == 400, True)

# T5: missing major -> 400
s, _ = req(op_pub, '/visitor/membership-request', 'POST',
           {'name':'x','student_id':'STU-9'}, is_json=True)
check('T5 missing major -> 400', s == 400, True)

# ===== Leader-only authorization =====

req_id = c.execute("SELECT id FROM membership_request WHERE student_id='STU-100'").fetchone()[0]

# T6: no cookie -> 403
op_none = session()
s, _ = req(op_none, f'/leader/membership-requests/{req_id}/approve', 'POST')
check('T6 no-cookie approve -> 403', s == 403, True)

# T7: supervisor is NOT authorized (per decision: leader-only)
sup_op = login('supervisor@club.com', 'password1234')
s, _ = req(sup_op, f'/leader/membership-requests/{req_id}/approve', 'POST')
check('T7 supervisor approve -> 403 (leader-only)', s == 403, True)

# T8: member cannot approve. We create a disposable test member in the test DB.
from werkzeug.security import generate_password_hash
cc = sqlite3.connect(TEST_DB)
cc.execute("DELETE FROM user WHERE email='p3a-member@test.local'")
cc.execute("INSERT INTO user (name,email,password_hash,role,committee,points) VALUES (?,?,?,?,NULL,0)",
           ("P3A Member","p3a-member@test.local",generate_password_hash("testpass"),"member"))
cc.commit(); cc.close()
om = login('p3a-member@test.local', 'testpass')
s, _ = req(om, f'/leader/membership-requests/{req_id}/approve', 'POST')
check('T8 member approve -> 403 (leader-only)', s == 403, True)

# ===== Approval flow =====

# T9: leader approves -> 200 + status=approved + reviewer recorded
leader_op = login('leader@club.com', 'password123')
s, body = req(leader_op, f'/leader/membership-requests/{req_id}/approve', 'POST')
d = json.loads(body) if body.startswith('{') else {}
row = c.execute("SELECT status, reviewed_by, reviewed_at FROM membership_request WHERE id=?", (req_id,)).fetchone()
check('T9 leader approve -> 200 + status=approved + reviewer+time recorded',
      s == 200 and d.get('status') == 'approved' and row[0] == 'approved' and row[1] is not None and row[2] is not None, True)

# T10: decision immutable — approve again -> 409
s, _ = req(leader_op, f'/leader/membership-requests/{req_id}/approve', 'POST')
check('T10 re-approve already approved -> 409', s == 409, True)

# T11: reject after approve -> 409
s, _ = req(leader_op, f'/leader/membership-requests/{req_id}/reject', 'POST')
check('T11 reject already approved -> 409', s == 409, True)

# T12: approval message mentions signup/invite flow (not auto-created)
# Decode T9 body as JSON object; the note string will decode properly
note = (d or {}).get('note', '')
check('T12 approve response note mentions signup + invite',
      'signup' in note and 'رمز الدعوة' in note, True)

# T13: no User row auto-created for the applicant
# Count users with name='طالب تجريبي'
auto_user = c.execute("SELECT COUNT(*) FROM user WHERE name='طالب تجريبي'").fetchone()[0]
check('T13 approval did NOT create a user row', auto_user == 0, True)

# ===== Reject flow =====

# Submit a second request
s, body = req(session(), '/visitor/membership-request', 'POST',
              {'name':'طالب ب','student_id':'STU-200','major':'إدارة'}, is_json=True)
d = json.loads(body)
req2 = d['id']

# T14: leader rejects -> 200 + status=rejected
s, _ = req(leader_op, f'/leader/membership-requests/{req2}/reject', 'POST')
row2 = c.execute("SELECT status, reviewed_by, reviewed_at FROM membership_request WHERE id=?", (req2,)).fetchone()
check('T14 leader reject -> 200 + status=rejected + reviewer recorded',
      s == 200 and row2[0] == 'rejected' and row2[1] is not None and row2[2] is not None, True)

# T15: re-reject after reject -> 409
s, _ = req(leader_op, f'/leader/membership-requests/{req2}/reject', 'POST')
check('T15 re-reject already rejected -> 409', s == 409, True)

# T16: approve after reject -> 409
s, _ = req(leader_op, f'/leader/membership-requests/{req2}/approve', 'POST')
check('T16 approve already rejected -> 409', s == 409, True)

# T17: nonexistent request -> 404
s, _ = req(leader_op, '/leader/membership-requests/999999/approve', 'POST')
check('T17 nonexistent -> 404', s == 404, True)

# T18: can resubmit after rejection (not blocked by duplicate guard because status != pending)
s, _ = req(session(), '/visitor/membership-request', 'POST',
           {'name':'طالب ب','student_id':'STU-200','major':'إدارة'}, is_json=True)
check('T18 resubmit after rejection allowed -> 201', s == 201, True)

# T19: leader dashboard renders the section with the submitted rows
s, body = req(leader_op, '/leader/dashboard')
has_section = 'طلبات الانضمام للنادي' in body
has_signup_hint = '/signup' in body or 'إنشاء حساب' in body
has_filter = 'membership-filter' in body
has_data = 'STU-100' in body and 'STU-200' in body
check('T19 leader dashboard shows section + filter + rows + signup note',
      s == 200 and has_section and has_signup_hint and has_filter and has_data, True)

# T20: counts in the heading show real values (1 approved, 1 rejected, 1 pending — depends on T18)
cnt = c.execute("SELECT status, COUNT(*) FROM membership_request GROUP BY status").fetchall()
cnt_d = dict(cnt)
check('T20 DB counts: approved=1, rejected=1, pending>=1',
      cnt_d.get('approved',0) == 1 and cnt_d.get('rejected',0) == 1 and cnt_d.get('pending',0) >= 1, True)

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
