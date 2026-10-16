/* Tier 1 — isolated additions loaded only by signup.html and tasks_tier1.html.
   Depends on main.js having run first (uses $, toast, defined there). */

(function () {
    const $ = (s, r = document) => r.querySelector(s);
    const $$ = (s, r = document) => [...r.querySelectorAll(s)];

    /* ---------- Signup form (templates/signup.html) ---------- */
    const signupForm = $('#signupForm');
    if (signupForm) {
        const errorBox = $('#signupError');
        const showError = (msg) => {
            if (!errorBox) return;
            errorBox.textContent = msg;
            errorBox.style.display = msg ? 'block' : 'none';
        };

        signupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            showError('');

            const name = $('#su-name').value.trim();
            const email = $('#su-email').value.trim();
            const password = $('#su-password').value;
            const invite = $('#su-invite').value.trim();

            if (!name) return showError('يرجى إدخال الاسم');
            if (!email) return showError('يرجى إدخال البريد الإلكتروني');
            if (!password || password.length < 8) return showError('كلمة المرور يجب أن تكون 8 أحرف على الأقل');

            const payload = { name, email, password };
            if (invite) payload.invite_code = invite;

            try {
                const res = await fetch('/register', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify(payload)
                });
                if (res.status === 201) {
                    // Success — redirect to login page.
                    window.location.href = '/login';
                    return;
                }
                let data = {};
                try { data = await res.json(); } catch (_) {}
                if (res.status === 409) {
                    showError('البريد الإلكتروني مسجل بالفعل');
                } else if (res.status === 400) {
                    showError(data.error || 'البيانات غير مكتملة');
                } else {
                    showError('تعذر إنشاء الحساب (' + res.status + ')');
                }
            } catch (err) {
                showError('تعذر الاتصال بالخادم');
            }
        });
    }

    /* ---------- Task status update (templates/tasks_tier1.html) ---------- */
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-update-status]');
        if (!btn) return;
        const taskId = btn.dataset.updateStatus;
        const card = btn.closest('[data-task-id]');
        if (!card) return;
        const select = card.querySelector('[data-status-select]');
        if (!select) return;
        const newStatus = select.value;

        const fd = new FormData();
        fd.append('status', newStatus);

        btn.disabled = true;
        try {
            const res = await fetch(`/member/tasks/${taskId}/status`, {
                method: 'POST',
                body: fd
            });
            if (!res.ok) {
                let msg = 'فشل التحديث';
                try {
                    const d = await res.json();
                    if (d.error) msg = d.error;
                } catch (_) {}
                if (typeof toast === 'function') toast(msg);
                return;
            }
            const d = await res.json();
            const statusEl = card.querySelector('[data-current-status]');
            if (statusEl) {
                statusEl.textContent = d.status;
                statusEl.classList.remove('completed', 'in-progress');
                statusEl.classList.add(d.status === 'مكتملة' ? 'completed' : 'in-progress');
            }
            if (typeof toast === 'function') toast('تم تحديث الحالة');
        } catch (_) {
            if (typeof toast === 'function') toast('تعذر الاتصال بالخادم');
        } finally {
            btn.disabled = false;
        }
    });
})();
