"""Isolated Phase 1 test matrix.

T1-T10 cover: visitor fix, strict role separation, template rename.
Runs against 127.0.0.1:5055 which is the isolated server bound to
instance/club.event-test.db.
"""
import sys, urllib.request, urllib.parse, json, http.cookiejar
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:5055'

def session():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def session_no_redirect():
    cj = http.cookiejar.CookieJar()
    class NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NR())

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
            return resp.status, dict(resp.headers), resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode('utf-8', errors='replace')

results = []
def check(label, got, want):
    ok = got == want
    results.append((label, got, want, ok))

# Login helper (opener persists cookies)
def login(email, password):
    op = session()
    s, _, _ = req(op, '/login', 'POST', {'email': email, 'password': password}, is_json=True)
    assert s == 200, f'login failed for {email}: {s}'
    return op

def login_nr(email, password):
    op = session_no_redirect()
    s, _, _ = req(op, '/login', 'POST', {'email': email, 'password': password}, is_json=True)
    assert s == 200, f'login failed for {email}: {s}'
    return op

# ===== T1: visitor login + GET /dashboard -> 302 to /visitor =====
op = login_nr('visitor1@test.local', 'password12')
s, hdr, _ = req(op, '/dashboard')
loc = hdr.get('Location', '')
check('T1 visitor /dashboard -> 302 /visitor', s == 302 and '/visitor' in loc, True)

# ===== T2: visitor -> /member/profile -> 403 =====
op = login('visitor1@test.local', 'password12')
s, _, _ = req(op, '/member/profile')
check('T2 visitor /member/profile 403', s == 403, True)

# ===== T3: visitor -> /leader/dashboard -> 403 =====
s, _, _ = req(op, '/leader/dashboard')
check('T3 visitor /leader/dashboard 403', s == 403, True)

# ===== T4: member login + GET /dashboard -> 302 /member/profile =====
op = login_nr('member-test@club.test', 'testpass')
s, hdr, _ = req(op, '/dashboard')
loc = hdr.get('Location', '')
check('T4 member /dashboard -> 302 /member/profile', s == 302 and '/member/profile' in loc, True)

# ===== T5: leader login + GET /dashboard -> 302 /leader/dashboard =====
op = login_nr('leader@club.com', 'password123')
s, hdr, _ = req(op, '/dashboard')
loc = hdr.get('Location', '')
check('T5 leader /dashboard -> 302 /leader/dashboard', s == 302 and '/leader/dashboard' in loc, True)

# ===== T6: leader -> /supervisor/dashboard -> 403 =====
op = login('leader@club.com', 'password123')
s, _, _ = req(op, '/supervisor/dashboard')
check('T6 leader /supervisor/dashboard 403', s == 403, True)

# ===== T7: supervisor login + GET /dashboard -> 302 /supervisor/dashboard =====
op = login_nr('supervisor@club.com', 'password1234')
s, hdr, _ = req(op, '/dashboard')
loc = hdr.get('Location', '')
check('T7 supervisor /dashboard -> 302 /supervisor/dashboard', s == 302 and '/supervisor/dashboard' in loc, True)

# ===== T8: supervisor -> /leader/dashboard -> 403 =====
op = login('supervisor@club.com', 'password1234')
s, _, _ = req(op, '/leader/dashboard')
check('T8 supervisor /leader/dashboard 403', s == 403, True)

# ===== T9: member dashboard renders from member-dashboard.html + contains profile =====
op = login('member-test@club.test', 'testpass')
s, _, body = req(op, '/member/profile')
has_name = 'Test Member' in body
has_email = 'member-test@club.test' in body
has_progress = 'قيد التطوير' in body  # progress block preserved
has_tasks_link = 'عرض المهام' in body  # link to tasks still present
check('T9 member dashboard has name/email/progress/tasks-link',
      s == 200 and has_name and has_email and has_progress and has_tasks_link, True)

# ===== T10: template filename change effective (dashboard.html render would also show same content, but we verify by removing dashboard.html temporarily — no, we check that render_template points to the new file by content match + checking that the title has the member-dashboard page)
# Actually: both files exist in the isolated folder, and both have identical content. So content-wise we can't distinguish. Verify via a more direct method: check Flask's template directly resolved from member-dashboard.html by querying /healthz for a sanity signal.
# A direct way: check that the isolated app.py renders tasks dashboard via member-dashboard.html template name. We proved this via static grep on app.py line 662. Encode that fact into a status check:
import os
app_py = open('_isolated_phase1/app.py','r',encoding='utf-8').read()
check('T10 isolated app.py renders member-dashboard.html',
      'render_template("member-dashboard.html")' in app_py and 'render_template("dashboard.html")' not in app_py, True)

# ===== REPORT =====
print(f'{"test":<60} {"got":<8} {"want":<8} pass')
print('-' * 90)
all_pass = True
for name, got, want, ok in results:
    all_pass = all_pass and ok
    print(f'{name:<60} {str(got)[:7]:<8} {str(want)[:7]:<8} {"PASS" if ok else "FAIL"}')
print()
print('ALL PASS' if all_pass else 'FAILURES PRESENT')
sys.exit(0 if all_pass else 1)
