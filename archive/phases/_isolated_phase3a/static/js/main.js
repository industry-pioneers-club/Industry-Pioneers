const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const path=location.pathname.replace(/\/+$/,'')||'/';
const NAV=[['/','الرئيسية'],['/about','عن النادي'],['/events','الفعاليات'],['/gazette','جريدة الصناعة'],['/partners','الشركاء والرعاة']];

/* Shared navbar + footer (edit once, applies to every page) */
document.body.insertAdjacentHTML('afterbegin',`<header class="nav"><a class="brand" href="/"><img src="/static/Image/club-logo.png" alt="نادي رواد الصناعة"><i></i><img src="/static/Image/taibah-logo.png" alt="جامعة طيبة"></a>
<button class="burger" aria-label="القائمة">☰</button><div class="menu"><nav class="links">${NAV.map(([h,t])=>`<a href="${h}"${h===path?' class="on"':''}>${t}</a>`).join('')}</nav><span id="auth-slot"></span></div></header>`);
const authSource=document.getElementById('auth-links-source');
const authSlot=document.getElementById('auth-slot');
if(authSource&&authSlot) authSlot.replaceWith(...authSource.content.childNodes);
document.body.insertAdjacentHTML('beforeend',`<footer class="mini-footer">© 2026 نادي رواد الصناعة — جامعة طيبة</footer><div class="modal" id="modal"><div class="box" id="box"></div></div><div class="toast" id="toast"></div>`);
$('.burger').onclick=()=>$('.nav').classList.toggle('open');
addEventListener('error',e=>{if(e.target.tagName==='IMG')e.target.classList.add('missing')},true); // hide broken/missing images
const hideBroken=()=>$$('img').forEach(i=>{if(i.complete&&!i.naturalWidth)i.classList.add('missing')});addEventListener('load',hideBroken);

let tt;const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(tt);tt=setTimeout(()=>t.classList.remove('show'),2600)};
const modal=h=>{$('#box').innerHTML=h;$('#modal').classList.add('show')},closeModal=()=>$('#modal').classList.remove('show');
$('#modal').onclick=e=>{if(e.target.id==='modal'||e.target.dataset.close!==undefined)closeModal()};

/* Event search and chips filter the server-rendered cards. */
const evBox=$('#upcoming');
if(evBox){let cat='الكل';const q=$('#q');
 const draw=()=>{const query=(q&&q.value?q.value:'').trim();['#upcoming','#previous'].forEach(sel=>{const box=$(sel);if(!box)return;const cards=$$('.ev',box);let shown=0;cards.forEach(card=>{const text=card.textContent||'';const ok=(cat==='الكل'||text.includes(cat))&&text.includes(query);card.style.display=ok?'':'none';if(ok)shown+=1});let note=$('.empty',box);if(!shown){if(!note){note=document.createElement('p');note.className='empty';note.textContent='لا توجد نتائج مطابقة';box.appendChild(note)}note.style.display=''}else if(note)note.style.display='none'})};
 $$('.chip').forEach(b=>b.onclick=()=>{$$('.chip').forEach(x=>x.classList.remove('on'));b.classList.add('on');cat=b.textContent;draw()});
 if(q)q.oninput=draw}

document.addEventListener('click',async e=>{const b=e.target.closest('[data-article-id]');if(!b)return;const id=b.dataset.articleId;try{const res=await fetch('/like_article/'+id,{method:'POST',headers:{Accept:'application/json'}});if(!res.ok)return;const data=await res.json();const count=b.querySelector('span');if(count&&typeof data.likes_count==='number')count.textContent=data.likes_count;b.classList.add('on')}catch(err){}});

setTimeout(hideBroken,300);
const lf=$('#loginForm');
if(lf)lf.onsubmit=e=>{if(!lf.id.value.trim()||!lf.pw.value.trim()){e.preventDefault();toast('الرجاء تعبئة جميع الحقول')}};

/* Article upload form — inline validation + success toast on return */
const uaForm = $('#uploadArticleForm');
if (uaForm) {
    const showError = (field, show) => {
        const el = document.querySelector(`[data-error-for="${field}"]`);
        if (el) el.classList.toggle('show', !!show);
    };
    uaForm.addEventListener('submit', e => {
        const title = uaForm.title.value.trim();
        const category = uaForm.category.value.trim();
        const titleOk = title.length > 0 && title.length <= 200;
        const categoryOk = category.length > 0;
        showError('title', !titleOk);
        showError('category', !categoryOk);
        if (!titleOk || !categoryOk) {
            e.preventDefault();
            toast('يرجى تعبئة الحقول المطلوبة');
            return;
        }
        try { sessionStorage.setItem('ua-submitted', '1'); } catch (_) {}
    });
    ['title','category'].forEach(name => {
        const el = uaForm[name];
        if (el) el.addEventListener('input', () => showError(name, false));
        if (el && el.tagName === 'SELECT') el.addEventListener('change', () => showError(name, false));
    });
    try {
        if (sessionStorage.getItem('ua-submitted') === '1') {
            sessionStorage.removeItem('ua-submitted');
            toast('تم إرسال المقال للمراجعة');
        }
    } catch (_) {}
}

/* Visitor page forms: no backend handler yet; intercept and show a toast
   instead of posting to '#' which reloads the page. */
$$('.visitor-form').forEach(form => {
    form.addEventListener('submit', e => {
        e.preventDefault();
        const required = $$('[required]', form);
        const missing = required.some(el => !String(el.value || '').trim());
        if (missing) {
            toast('يرجى تعبئة جميع الحقول المطلوبة');
            return;
        }
        form.reset();
        toast('تم استلام طلبك (سيتم ربط النموذج بقاعدة البيانات لاحقاً)');
    });
});


/* =========================================
   LEADER DASHBOARD
   =========================================
   Articles: enhanced in place (approve/reject are LOCAL-only until B1).
   Tasks & sponsors: real CRUD via /leader/tasks and /leader/sponsors.
*/

const arabicDate = iso => {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        return new Intl.DateTimeFormat('ar-SA-u-ca-gregory',
            {day:'numeric', month:'long', year:'numeric'}).format(d);
    } catch (_) { return iso; }
};

const leaderData = (() => {
    const el = document.getElementById('leader-dashboard-data');
    if (!el) return {events: [], members: []};
    try { return JSON.parse(el.textContent); }
    catch (_) { return {events: [], members: []}; }
})();

const leaderPage = path === '/leader/dashboard';

if (leaderPage) {

    /* -------- TASKS (real backend) -------- */

    // Format server-rendered deadline cells into Arabic Gregorian on first paint.
    $$('#leaderTasks tr[data-task-id]').forEach(row => {
        const cell = row.querySelector('[data-deadline-cell]');
        const iso = row.dataset.taskDeadline;
        if (cell && iso) cell.textContent = arabicDate(iso);
    });

    const buildOptions = (list, keyName, selectedId) => list.map(item => {
        const v = item.id;
        const label = item[keyName] || item.title || item.name || '';
        const sel = (String(v) === String(selectedId)) ? ' selected' : '';
        return `<option value="${v}"${sel}>${label}</option>`;
    }).join('');

    const eventOptions = (selectedId='') =>
        `<option value="">— بدون فعالية —</option>` + buildOptions(leaderData.events, 'title', selectedId);
    const memberOptions = (selectedId='') =>
        `<option value="">— بدون عضو —</option>` + buildOptions(leaderData.members, 'name', selectedId);

    /* -------- ADD EVENT (real backend) --------
       Collects only the fields the Event model stores:
       title, date, time, is_public, image_path. */
    $('#addEventBtn')?.addEventListener('click',()=>{
        modal(`
            <h3>إنشاء فعالية جديدة</h3>
            <div class="dashboard-form">
                <label>عنوان الفعالية *</label>
                <input id="newEventName" placeholder="عنوان الفعالية" maxlength="200">

                <div class="form-row">
                    <div>
                        <label>التاريخ *</label>
                        <input id="newEventDate" type="date">
                    </div>
                    <div>
                        <label>الوقت</label>
                        <input id="newEventTime" type="time" value="09:00">
                    </div>
                </div>

                <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                    <input id="newEventIsPublic" type="checkbox">
                    <span>عرض الفعالية على الصفحة العامة</span>
                </label>

                <label>مسار الشعار (داخل static/ — اختياري)</label>
                <input id="newEventImagePath" placeholder="Image/event-4.png">
                <p style="font-size:13px;color:#666;margin:4px 0 0">يجب أن يكون المسار لملف موجود داخل مجلد static/. مثال: <code>Image/event-4.png</code></p>

                <button class="btn btn-o" id="saveNewEvent">حفظ الفعالية</button>
            </div>
        `);
        $('#saveNewEvent').onclick = async () => {
            const title = $('#newEventName').value.trim();
            const date = $('#newEventDate').value;
            const time = $('#newEventTime').value;
            if (!title) return toast('يرجى إدخال عنوان الفعالية');
            if (!date) return toast('يرجى تحديد تاريخ الفعالية');
            const fd = new FormData();
            fd.append('title', title);
            fd.append('date', date);
            fd.append('time', time || '00:00');
            fd.append('is_public', $('#newEventIsPublic').checked ? '1' : '0');
            const img = $('#newEventImagePath').value.trim();
            if (img) fd.append('image_path', img);
            try {
                const res = await fetch('/leader/events', {method:'POST', body: fd});
                if (!res.ok) {
                    const err = await res.json().catch(()=>({error:'فشل الحفظ'}));
                    return toast(err.error || 'فشل الحفظ');
                }
                closeModal();
                toast('تم إنشاء الفعالية بنجاح');
                location.reload();
            } catch (_) { toast('تعذر الاتصال بالخادم'); }
        };
    });

    /* -------- DELETE EVENT -------- */
    document.addEventListener('click', async e => {
        const del = e.target.closest('[data-delete-event]');
        if (!del) return;
        if (!confirm('هل تريد حذف هذه الفعالية؟ لا يمكن التراجع.')) return;
        const id = del.dataset.deleteEvent;
        try {
            const res = await fetch(`/leader/events/${id}/delete`, {method:'POST'});
            if (!res.ok) {
                const err = await res.json().catch(()=>({error:'فشل الحذف'}));
                return toast(err.error || 'فشل الحذف');
            }
            toast('تم حذف الفعالية');
            del.closest('tr')?.remove();
        } catch (_) { toast('تعذر الاتصال بالخادم'); }
    });

    /* -------- ADD TASK (real backend) -------- */
    $('#addTaskBtn')?.addEventListener('click',()=>{
        modal(`
            <h3>إضافة مهمة</h3>
            <div class="dashboard-form">
                <label>الفعالية</label>
                <select id="newTaskEvent">${eventOptions()}</select>
                <label>اسم المهمة</label><input id="newTaskName" placeholder="اسم المهمة">
                <label>العضو</label>
                <select id="newTaskMember">${memberOptions()}</select>
                <label>النقاط</label><input id="newTaskPoints" type="number" value="10">
                <label>موعد التسليم</label><input id="newTaskDeadline" type="date">
                <button class="btn btn-o" id="saveNewTask">حفظ المهمة</button>
            </div>
        `);
        $('#saveNewTask').onclick = async () => {
            const title = $('#newTaskName').value.trim();
            if (!title) return toast('يرجى إدخال اسم المهمة');
            const fd = new FormData();
            fd.append('title', title);
            fd.append('event_id', $('#newTaskEvent').value);
            fd.append('assigned_user_id', $('#newTaskMember').value);
            fd.append('points', $('#newTaskPoints').value);
            fd.append('deadline', $('#newTaskDeadline').value);
            try {
                const res = await fetch('/leader/tasks', {method:'POST', body: fd});
                if (!res.ok) {
                    const err = await res.json().catch(()=>({error:'فشل الحفظ'}));
                    return toast(err.error || 'فشل الحفظ');
                }
                closeModal();
                toast('تمت إضافة المهمة');
                location.reload();
            } catch (_) { toast('تعذر الاتصال بالخادم'); }
        };
    });

    /* -------- EDIT / DELETE TASK -------- */
    document.addEventListener('click', async e => {
        const edit = e.target.closest('[data-edit-task]');
        if (edit) {
            const id = edit.dataset.editTask;
            const row = document.querySelector(`tr[data-task-id="${id}"]`);
            if (!row) return;
            const curTitle = row.dataset.taskTitle || '';
            const curPoints = row.dataset.taskPoints || '0';
            const curDeadline = row.dataset.taskDeadline || '';
            const curEvent = row.dataset.taskEventId || '';
            const curMember = row.dataset.taskMemberId || '';
            const curStatus = row.dataset.taskStatus || 'قيد التنفيذ';
            modal(`
                <h3>تعديل المهمة</h3>
                <div class="dashboard-form">
                    <label>اسم المهمة</label>
                    <input id="editTaskName" value="${curTitle.replace(/"/g,'&quot;')}">
                    <label>الفعالية</label>
                    <select id="editTaskEvent">${eventOptions(curEvent)}</select>
                    <label>العضو</label>
                    <select id="editTaskMember">${memberOptions(curMember)}</select>
                    <label>النقاط</label>
                    <input id="editTaskPoints" type="number" value="${curPoints}">
                    <label>موعد التسليم</label>
                    <input id="editTaskDeadline" type="date" value="${curDeadline}">
                    <label>الحالة</label>
                    <select id="editTaskStatus">
                        <option value="قيد التنفيذ"${curStatus==='قيد التنفيذ'?' selected':''}>قيد التنفيذ</option>
                        <option value="مكتملة"${curStatus==='مكتملة'?' selected':''}>مكتملة</option>
                    </select>
                    <button class="btn btn-o" id="saveTaskEdit">حفظ التعديل</button>
                </div>
            `);
            $('#saveTaskEdit').onclick = async () => {
                const fd = new FormData();
                fd.append('title', $('#editTaskName').value);
                fd.append('event_id', $('#editTaskEvent').value);
                fd.append('assigned_user_id', $('#editTaskMember').value);
                fd.append('points', $('#editTaskPoints').value);
                fd.append('deadline', $('#editTaskDeadline').value);
                fd.append('status', $('#editTaskStatus').value);
                try {
                    const res = await fetch(`/leader/tasks/${id}`, {method:'POST', body: fd});
                    if (!res.ok) {
                        const err = await res.json().catch(()=>({error:'فشل التعديل'}));
                        return toast(err.error || 'فشل التعديل');
                    }
                    closeModal();
                    toast('تم تعديل المهمة');
                    location.reload();
                } catch (_) { toast('تعذر الاتصال بالخادم'); }
            };
        }

        const del = e.target.closest('[data-delete-task]');
        if (del) {
            const id = del.dataset.deleteTask;
            if (!confirm('هل تريد حذف هذه المهمة؟')) return;
            try {
                const res = await fetch(`/leader/tasks/${id}/delete`, {method:'POST'});
                if (!res.ok) return toast('فشل الحذف');
                toast('تم حذف المهمة');
                del.closest('tr')?.remove();
            } catch (_) { toast('تعذر الاتصال بالخادم'); }
        }
    });

    /* -------- APPROVALS --------
       We DO NOT clobber server-rendered rows. Instead we enhance them in place:
       for each row with data-article-id, add approve/reject/view buttons and
       track status locally. Status will reset on refresh until a backend
       approval route exists.
    */
    const approvalStatuses = {}; // id -> 'approved' | 'rejected' | 'pending'

    const buildApprovalActions = (id, title, author, date) => {
        const status = approvalStatuses[id] || 'pending';
        const statusLabel = status === 'approved' ? 'معتمد' : status === 'rejected' ? 'مرفوض' : 'قيد المراجعة';
        const statusClass = status === 'approved' ? 'status-approved' : status === 'rejected' ? 'status-rejected' : 'status-pending';
        const actions = status === 'pending' ? `
            <button class="dashboard-action approve" data-approve-article="${id}">اعتماد</button>
            <button class="dashboard-action reject" data-reject-article="${id}">رفض</button>
        ` : '';
        return { statusLabel, statusClass, actions };
    };

    const enhanceApprovalRows = () => {
        const approvalList = $('#approvalList');
        if (!approvalList) return;
        $$('tr', approvalList).forEach(row => {
            // Rows with real articles have data-article-id (set below in template).
            const id = row.dataset.articleId;
            if (!id) return;
            const title = row.dataset.articleTitle || '';
            const author = row.dataset.articleAuthor || '';
            const date = row.dataset.articleDate || '';
            const { statusLabel, statusClass, actions } = buildApprovalActions(id, title, author, date);
            const statusCell = row.querySelector('[data-approval-status]');
            const actionsCell = row.querySelector('[data-approval-actions]');
            if (statusCell) {
                statusCell.innerHTML = `<span class="dashboard-status ${statusClass}">${statusLabel}</span>`;
            }
            if (actionsCell) {
                actionsCell.innerHTML = `
                    <div class="dashboard-actions">
                        <button class="dashboard-action" data-view-article="${id}">عرض</button>
                        ${actions}
                    </div>
                `;
            }
        });
    };

    enhanceApprovalRows();

    document.addEventListener('click', e => {
        const approve = e.target.closest('[data-approve-article]');
        if (approve) {
            approvalStatuses[approve.dataset.approveArticle] = 'approved';
            enhanceApprovalRows();
            toast('تم اعتماد المقال (محلي فقط — يتطلب نقطة نهاية backend)');
            return;
        }
        const reject = e.target.closest('[data-reject-article]');
        if (reject) {
            approvalStatuses[reject.dataset.rejectArticle] = 'rejected';
            enhanceApprovalRows();
            toast('تم رفض المقال (محلي فقط — يتطلب نقطة نهاية backend)');
            return;
        }
        const view = e.target.closest('[data-view-article]');
        if (view) {
            const row = view.closest('tr');
            if (!row) return;
            const title = row.dataset.articleTitle || '';
            const author = row.dataset.articleAuthor || '';
            const date = row.dataset.articleDate || '';
            modal(`
                <h3>${title}</h3>
                <p style="margin-top:12px"><b>الكاتب:</b> ${author}</p>
                <p style="margin-top:8px"><b>التاريخ:</b> ${date}</p>
            `);
        }
    });

    /* -------- SPONSORS (real backend) -------- */
    $('#addSponsorBtn')?.addEventListener('click',()=>{
        modal(`
            <h3>إضافة راعٍ</h3>
            <div class="dashboard-form">
                <label>اسم الراعي</label>
                <input id="sponsorName" placeholder="اسم الراعي">
                <label>الفئة</label>
                <input id="sponsorTier" placeholder="Partner / Gold / Silver" value="Partner">
                <label>مسار شعار الراعي (داخل مجلد static فقط)</label>
                <input id="sponsorImage" placeholder="Image/sponsor.png">
                <p style="font-size:13px;color:#666">يجب أن يكون المسار لملف موجود داخل static/. مثال: <code>Image/club-logo.png</code></p>
                <button class="btn btn-o" id="saveSponsor">إضافة الراعي</button>
            </div>
        `);
        $('#saveSponsor').onclick = async () => {
            const name = $('#sponsorName').value.trim();
            if (!name) return toast('يرجى إدخال اسم الراعي');
            const fd = new FormData();
            fd.append('name', name);
            fd.append('tier', $('#sponsorTier').value.trim() || 'Partner');
            fd.append('logo_path', $('#sponsorImage').value.trim());
            try {
                const res = await fetch('/leader/sponsors', {method:'POST', body: fd});
                if (!res.ok) {
                    const err = await res.json().catch(()=>({error:'فشل الإضافة'}));
                    return toast(err.error || 'فشل الإضافة');
                }
                closeModal();
                toast('تمت إضافة الراعي');
                location.reload();
            } catch (_) { toast('تعذر الاتصال بالخادم'); }
        };
    });

    document.addEventListener('click', async e => {
        const del = e.target.closest('[data-delete-sponsor]');
        if (!del) return;
        if (!confirm('هل تريد حذف هذا الراعي؟')) return;
        const id = del.dataset.deleteSponsor;
        try {
            const res = await fetch(`/leader/sponsors/${id}/delete`, {method:'POST'});
            if (!res.ok) return toast('فشل الحذف');
            toast('تم حذف الراعي');
            del.closest('.sponsor-dashboard-card')?.remove();
        } catch (_) { toast('تعذر الاتصال بالخادم'); }
    });

}


/* =========================================
   SUPERVISOR DASHBOARD
   =========================================
   Reads real counts from the /supervisor/stats JSON endpoint.
*/

const supervisorPage = path === '/supervisor/dashboard';

if (supervisorPage) {

    const stats = { total: 0, completed: 0, upcoming: 0, pct: 0, articles: 0, sponsors: 0 };

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    const renderStats = (failed = false) => {
        set('stat-total', stats.total);
        set('stat-completed', stats.completed);
        set('stat-upcoming', stats.upcoming);
        set('stat-articles', stats.articles);
        set('stat-sponsors', stats.sponsors);
        set('stat-completion', stats.pct + '%');
        set('completion-circle', stats.pct + '%');
        set('completion-summary', stats.total > 0
            ? `تم إنجاز ${stats.completed} من أصل ${stats.total} فعالية.`
            : (failed ? 'تعذر تحميل البيانات' : 'لا توجد فعاليات حالياً.'));
        const upPct = stats.total > 0 ? Math.round((stats.upcoming / stats.total) * 100) : 0;
        const cFill = document.getElementById('chart-completed-fill');
        const uFill = document.getElementById('chart-upcoming-fill');
        if (cFill) cFill.style.width = stats.pct + '%';
        if (uFill) uFill.style.width = upPct + '%';
        set('chart-completed-label', stats.pct + '%');
        set('chart-upcoming-label', upPct + '%');
    };

    const loadStats = async () => {
        try {
            const res = await fetch('/supervisor/stats', { headers: { Accept: 'application/json' } });
            if (!res.ok) { renderStats(true); return; }
            const d = await res.json();
            stats.total     = d.events.total;
            stats.completed = d.events.completed;
            stats.upcoming  = d.events.upcoming;
            stats.pct       = d.events.completion_pct;
            stats.articles  = d.articles.total;
            stats.sponsors  = d.sponsors.total;
            renderStats();
        } catch (_) { renderStats(true); }
    };

    loadStats();

    const exportBtn = $('#exportReportBtn');
    exportBtn?.addEventListener('click', () => {
        const pct = stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : 0;
        const now = new Date().toLocaleString('ar');
        const report = [
            'تقرير أداء نادي رواد الصناعة',
            '',
            `التاريخ: ${now}`,
            '',
            `إجمالي الفعاليات: ${stats.total}`,
            `الفعاليات المكتملة: ${stats.completed}`,
            `الفعاليات القادمة: ${stats.upcoming}`,
            `نسبة الإنجاز: ${pct}%`,
            `إجمالي المقالات: ${stats.articles}`,
            `عدد الرعاة: ${stats.sponsors}`,
            '',
            'تم إنشاء التقرير من لوحة تحكم المشرف الأكاديمي.'
        ].join('\n');

        const blob = new Blob(['﻿' + report], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'industry-pioneers-report.txt';
        a.click();
        URL.revokeObjectURL(url);
        toast('تم تحميل التقرير');
    });

}


/* =========================================
   PHASE 0 — SIGNUP + MEMBER TASK STATUS
   ========================================= */

(function () {
    const sq = (s, r = document) => r.querySelector(s);

    /* ---------- Signup form (templates/signup.html) ---------- */
    const signupForm = sq('#signupForm');
    if (signupForm) {
        const errorBox = sq('#signupError');
        const showError = (msg) => {
            if (!errorBox) return;
            errorBox.textContent = msg;
            errorBox.style.display = msg ? 'block' : 'none';
        };

        signupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            showError('');

            const name = sq('#su-name').value.trim();
            const email = sq('#su-email').value.trim();
            const password = sq('#su-password').value;
            const invite = sq('#su-invite').value.trim();

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

    /* ---------- Task status update (templates/tasks.html) ---------- */
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


/* =========================================
   PHASE 2D — LEADER TASK APPROVAL / REJECTION
   ========================================= */

(function () {
    const approveButtons = document.querySelectorAll('[data-approve-task]');
    const rejectButtons = document.querySelectorAll('[data-reject-task]');
    if (approveButtons.length === 0 && rejectButtons.length === 0) return;

    const callApprovalRoute = async (taskId, action, button) => {
        const row = button.closest('[data-pending-task-id]');
        if (!row) return;
        const confirmMsg = action === 'approve'
            ? 'اعتماد هذه المهمة وإضافة النقاط للعضو؟'
            : 'رفض هذه المهمة؟';
        if (!confirm(confirmMsg)) return;
        row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
            const res = await fetch(`/leader/tasks/${taskId}/${action}`, { method: 'POST' });
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (!res.ok) {
                const msg = data.error || `فشل الطلب (${res.status})`;
                if (typeof toast === 'function') toast(msg);
                row.querySelectorAll('button').forEach(b => { b.disabled = false; });
                return;
            }
            if (typeof toast === 'function') {
                if (action === 'approve') {
                    toast(`تم اعتماد المهمة · +${data.points_awarded || 0} نقطة للعضو`);
                } else {
                    toast('تم رفض المهمة');
                }
            }
            row.remove();
            const tbody = document.getElementById('pendingApprovalList');
            if (tbody && tbody.querySelectorAll('tr[data-pending-task-id]').length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#888">لا توجد مهام تنتظر الاعتماد.</td></tr>';
            }
        } catch (_) {
            if (typeof toast === 'function') toast('تعذر الاتصال بالخادم');
            row.querySelectorAll('button').forEach(b => { b.disabled = false; });
        }
    };

    document.addEventListener('click', e => {
        const approveBtn = e.target.closest('[data-approve-task]');
        if (approveBtn) {
            e.preventDefault();
            callApprovalRoute(approveBtn.dataset.approveTask, 'approve', approveBtn);
            return;
        }
        const rejectBtn = e.target.closest('[data-reject-task]');
        if (rejectBtn) {
            e.preventDefault();
            callApprovalRoute(rejectBtn.dataset.rejectTask, 'reject', rejectBtn);
        }
    });
})();


/* =========================================
   PHASE 3A — MEMBERSHIP APPLICATIONS
   ========================================= */

// Visitor side: submit the membership form via fetch.
(function () {
    const form = document.getElementById('membershipForm');
    if (!form) return;
    const msgBox = document.getElementById('membershipFormMessage');
    const showMsg = (text, ok) => {
        if (!msgBox) return;
        msgBox.textContent = text;
        msgBox.style.display = 'block';
        msgBox.style.background = ok ? '#d4edda' : '#f8d7da';
        msgBox.style.color = ok ? '#155724' : '#721c24';
    };
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            name: form.name.value.trim(),
            student_id: form.student_id.value.trim(),
            major: form.major.value.trim(),
            email: form.email.value.trim(),
            reason: form.reason.value.trim(),
        };
        if (!payload.name || !payload.student_id || !payload.major) {
            showMsg('يرجى تعبئة الاسم والرقم الجامعي والتخصص', false);
            return;
        }
        try {
            const res = await fetch('/visitor/membership-request', {
                method: 'POST',
                headers: {'Content-Type':'application/json','Accept':'application/json'},
                body: JSON.stringify(payload),
            });
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (res.status === 201) {
                form.reset();
                showMsg('تم استلام طلبك بنجاح. سيقوم القائد بمراجعته قريباً.', true);
            } else if (res.status === 409) {
                showMsg(data.error || 'لديك طلب قيد المراجعة بالفعل', false);
            } else if (res.status === 400) {
                showMsg(data.error || 'بيانات غير مكتملة', false);
            } else {
                showMsg('تعذر إرسال الطلب (' + res.status + ')', false);
            }
        } catch (_) {
            showMsg('تعذر الاتصال بالخادم', false);
        }
    });
})();

// Leader side: approve / reject / filter / view-reason.
(function () {
    const list = document.getElementById('membershipRequestsList');
    if (!list) return;

    const applyFilter = (filter) => {
        list.querySelectorAll('tr[data-membership-id]').forEach(row => {
            const show = (filter === 'all') || (row.dataset.status === filter);
            row.style.display = show ? '' : 'none';
        });
    };
    document.querySelectorAll('.membership-filter').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.membership-filter').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            applyFilter(btn.dataset.filter);
        });
    });

    const callRoute = async (reqId, action, button) => {
        const row = button.closest('tr[data-membership-id]');
        if (!row) return;
        const confirmMsg = action === 'approve'
            ? 'اعتماد طلب العضوية؟ لن يُنشأ حساب تلقائياً — سيُطلب من المتقدم التسجيل بنفسه عبر /signup باستخدام رمز الدعوة.'
            : 'رفض طلب العضوية؟';
        if (!confirm(confirmMsg)) return;
        row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
            const res = await fetch(`/leader/membership-requests/${reqId}/${action}`, {method:'POST'});
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (!res.ok) {
                if (typeof toast === 'function') toast(data.error || ('فشل الطلب ('+res.status+')'));
                row.querySelectorAll('button').forEach(b => { b.disabled = false; });
                return;
            }
            row.dataset.status = data.status;
            const statusCell = row.querySelector('[data-membership-status]');
            if (statusCell) {
                statusCell.innerHTML = data.status === 'approved'
                    ? '<span class="dashboard-status status-approved">معتمد</span>'
                    : data.status === 'rejected'
                    ? '<span class="dashboard-status status-rejected">مرفوض</span>'
                    : '<span class="dashboard-status status-pending">قيد المراجعة</span>';
            }
            const actionsCell = row.querySelector('[data-membership-actions]');
            const reasonTpl = actionsCell ? actionsCell.querySelector(`template[data-reason-for="${reqId}"]`) : null;
            if (actionsCell) {
                actionsCell.innerHTML = reasonTpl
                    ? `<button type="button" class="dashboard-action" data-view-reason="${reqId}">عرض السبب</button>${reasonTpl.outerHTML}`
                    : '—';
            }
            if (typeof toast === 'function') {
                toast(action === 'approve'
                    ? 'تم اعتماد الطلب — يرجى إبلاغ المتقدم للتسجيل عبر صفحة إنشاء الحساب'
                    : 'تم رفض الطلب');
            }
        } catch (_) {
            if (typeof toast === 'function') toast('تعذر الاتصال بالخادم');
            row.querySelectorAll('button').forEach(b => { b.disabled = false; });
        }
    };

    document.addEventListener('click', (e) => {
        const ab = e.target.closest('[data-approve-membership]');
        if (ab) { e.preventDefault(); callRoute(ab.dataset.approveMembership, 'approve', ab); return; }
        const rb = e.target.closest('[data-reject-membership]');
        if (rb) { e.preventDefault(); callRoute(rb.dataset.rejectMembership, 'reject', rb); return; }
        const vb = e.target.closest('[data-view-reason]');
        if (vb) {
            e.preventDefault();
            const id = vb.dataset.viewReason;
            const tpl = document.querySelector(`template[data-reason-for="${id}"]`);
            const reason = tpl ? tpl.innerHTML.trim() : '';
            if (typeof modal === 'function') {
                modal(`<h3 style="color:#1b365d">سبب الانضمام</h3><p style="margin-top:12px;line-height:1.8">${reason || '(لا يوجد نص)'}</p>`);
            } else {
                alert(reason || '(لا يوجد نص)');
            }
        }
    });
})();