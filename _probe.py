"""Responsive smoke-test across every page and three viewports."""
import sys, time, requests, os
from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash

BASE = "http://127.0.0.1:5055"
for _ in range(40):
    try:
        if requests.get(BASE + "/healthz", timeout=1).status_code == 200: break
    except Exception: pass
    time.sleep(0.25)
else:
    print("FATAL: Flask not up"); sys.exit(2)

os.environ.pop("DATABASE_URL", None)
os.environ["SECRET_KEY"] = "dev"
from app import app, db, User

PWD = "resp-ui-pwd"
with app.app_context():
    u = User.query.filter_by(email="resp_ui@t.com").first()
    if u is None:
        u = User(name="تجربة الاستجابة", email="resp_ui@t.com",
                 password_hash=generate_password_hash(PWD), role="member")
        db.session.add(u); db.session.commit()
    else:
        u.password_hash = generate_password_hash(PWD); db.session.commit()
    UID = u.id

PUBLIC_PATHS = ["/", "/about", "/events", "/gazette", "/partners", "/visitor",
                "/login", "/signup"]
AUTH_PATHS = ["/member/profile", "/member/tasks", "/member/leaderboard",
              "/member/points-guide", "/member/upload-article",
              "/member/initiatives"]
VIEWPORTS = [("desktop", 1280, 900), ("tablet", 768, 1024), ("mobile", 375, 812)]

checks = []
def ok(msg, c, detail=""):
    checks.append((msg, c, detail))
    tag = (" — " + detail) if detail else ""
    print(("[OK] " if c else "[FAIL] ") + msg + tag)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, w, h in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            pageerrors = []
            page.on("pageerror", lambda e: pageerrors.append(str(e)))

            # Login once for the auth paths
            page.goto(BASE + "/login")
            page.fill('input[name="email"]', "resp_ui@t.com")
            page.fill('input[name="password"]', PWD)
            page.click('button[type="submit"]')
            try:
                page.wait_for_url("**/member/profile", timeout=5000)
            except Exception:
                pass

            all_paths = PUBLIC_PATHS + AUTH_PATHS
            for path in all_paths:
                try:
                    page.goto(BASE + path, wait_until="domcontentloaded", timeout=10000)
                except Exception as e:
                    ok(f"{name} {path} loads", False, f"nav err: {e}")
                    continue
                # Check horizontal overflow
                has_h_scroll = page.evaluate(
                    "document.documentElement.scrollWidth > window.innerWidth + 1"
                )
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                ok(f"{name} {path}: no horizontal overflow",
                   not has_h_scroll,
                   f"scrollWidth={scroll_w} vs viewport={w}")

            # Mobile-specific: hamburger shows + works
            if name == "mobile":
                page.goto(BASE + "/", wait_until="domcontentloaded")
                time.sleep(0.3)
                burger_visible = page.evaluate(
                    "() => { const b = document.querySelector('.burger'); if (!b) return false; const s = getComputedStyle(b); return s.display !== 'none'; }"
                )
                ok("mobile: burger button is visible", burger_visible)
                menu_hidden = page.evaluate(
                    "() => { const m = document.querySelector('.menu'); return getComputedStyle(m).display === 'none'; }"
                )
                ok("mobile: menu starts hidden", menu_hidden)
                page.click(".burger")
                time.sleep(0.3)
                menu_shown = page.evaluate(
                    "() => { const m = document.querySelector('.menu'); return getComputedStyle(m).display !== 'none'; }"
                )
                ok("mobile: clicking burger shows menu", menu_shown)
                link_count = page.evaluate("document.querySelectorAll('.menu .links a').length")
                ok(f"mobile: menu has {link_count} nav links", link_count >= 5)

                # Test the interests modal viewport-fit (login already active)
                page.goto(BASE + "/member/profile", wait_until="domcontentloaded")
                time.sleep(0.3)
                page.evaluate("document.getElementById('openInterestsModal')?.scrollIntoView()")
                page.click("#openInterestsModal")
                time.sleep(0.4)
                modal_box = page.evaluate(
                    "() => { const b = document.getElementById('box'); if (!b) return null; const r = b.getBoundingClientRect(); return {w: r.width, h: r.height}; }"
                )
                print("  modal box dims:", modal_box)
                if modal_box:
                    ok("mobile: modal fits viewport width",
                       modal_box["w"] <= w + 1,
                       f"box.w={modal_box['w']} vs viewport={w}")
                    ok("mobile: modal fits viewport height",
                       modal_box["h"] <= h + 1,
                       f"box.h={modal_box['h']} vs viewport={h}")

            if pageerrors:
                for e in pageerrors[:3]:
                    print("  pageerror:", e)
                ok(f"{name}: no page errors", False, f"{len(pageerrors)}")
            else:
                ok(f"{name}: no page errors", True)
            ctx.close()
        browser.close()
finally:
    with app.app_context():
        u = User.query.filter_by(email="resp_ui@t.com").first()
        if u:
            db.session.delete(u); db.session.commit()

passed = sum(1 for _, c, _ in checks if c)
total = len(checks)
print(f"\n{passed}/{total} PASS")
failures = [(m, d) for m, c, d in checks if not c]
if failures:
    print("Failures:")
    for m, d in failures:
        print(f"  - {m} :: {d}")
sys.exit(0 if passed == total else 1)
