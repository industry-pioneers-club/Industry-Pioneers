const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const path=location.pathname.replace(/\/+$/,'')||'/';
const NAV=[['/','الرئيسية'],['/about','عن النادي'],['/events','الفعاليات'],['/gazette','جريدة الصناعة'],['/partners','الشركاء والرعاة']];

/* Shared navbar + footer (edit once, applies to every page) */
document.body.insertAdjacentHTML('afterbegin',`<header class="nav"><a class="brand" href="/"><img src="/static/Image/club-logo.png" alt="نادي رواد الصناعة"><i></i><img src="/static/Image/taibah-logo.png" alt="جامعة طيبة"></a>
<button class="burger" aria-label="القائمة">☰</button><div class="menu"><nav class="links">${NAV.map(([h,t])=>`<a href="${h}"${h===path?' class="on"':''}>${t}</a>`).join('')}</nav><div id="auth-slot" class="auth-group"></div></div></header>`);
const authSource=document.getElementById('auth-links-source');
const authSlot=document.getElementById('auth-slot');
if(authSource&&authSlot){
    // Inject auth links as children of #auth-slot so the .auth-group flex
    // wrapper owns the margin-auto + gap, instead of each button fighting.
    const frag=document.importNode(authSource.content,true);
    authSlot.appendChild(frag);
}
// Shared chrome: a mini-footer (only when the page doesn't already include
// the full shared footer), plus the global modal + toast containers.
// Templates that render templates/_footer.html already have a <footer
// class="home-footer"> element, so we skip the mini-footer injection on
// those pages to avoid duplication. Pages that don't include it still get
// the mini-footer as a defensive fallback.
const _hasSharedFooter = document.querySelector('footer.home-footer');
document.body.insertAdjacentHTML('beforeend',
  (_hasSharedFooter ? '' : `<footer class="mini-footer">© 2026 نادي رواد الصناعة — جامعة طيبة</footer>`) +
  `<div class="modal" id="modal"><div class="box" id="box"></div></div><div class="toast" id="toast"></div>`);
$('.burger').onclick=()=>$('.nav').classList.toggle('open');
addEventListener('error',e=>{if(e.target.tagName==='IMG')e.target.classList.add('missing')},true); // hide broken/missing images
const hideBroken=()=>$$('img').forEach(i=>{if(i.complete&&!i.naturalWidth)i.classList.add('missing')});addEventListener('load',hideBroken);

let tt;const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(tt);tt=setTimeout(()=>t.classList.remove('show'),2600)};
const modal=h=>{$('#box').innerHTML=h;$('#modal').classList.add('show')},closeModal=()=>$('#modal').classList.remove('show');
$('#modal').onclick=e=>{if(e.target.id==='modal'||e.target.dataset.close!==undefined)closeModal()};
// Expose the modal/toast helpers globally so inline <script> blocks in
// templates can call them regardless of script-execution order
// (main.js is loaded with defer; template-inline scripts without defer run
// first and would otherwise see modal/toast as undefined).
window.modal = modal;
window.toast = toast;
window.closeModal = closeModal;

/* Event search + chip filter. The chip label matches Event.category
   stored on each card via data-category (see events.html). Full-text
   search still works across the card's visible text. */
const evBox=$('#upcoming');
if(evBox){
    let cat='الكل';
    const q=$('#q');
    const draw=()=>{
        const query=(q&&q.value?q.value:'').trim();
        ['#upcoming','#previous'].forEach(sel=>{
            const box=$(sel);if(!box)return;
            const cards=$$('.ev',box);
            let shown=0;
            cards.forEach(card=>{
                const cardCat = (card.dataset.category || '').trim();
                const text = card.textContent || '';
                const matchesCat = (cat === 'الكل') || (cardCat === cat);
                const matchesQuery = !query || text.includes(query);
                const ok = matchesCat && matchesQuery;
                card.style.display = ok ? '' : 'none';
                if (ok) shown += 1;
            });
            let note=$('.empty',box);
            if(!shown){
                if(!note){
                    note=document.createElement('p');
                    note.className='empty';
                    note.textContent='لا توجد نتائج مطابقة';
                    box.appendChild(note);
                }
                note.style.display='';
            } else if (note) {
                note.style.display='none';
            }
        });
    };
    $$('.chip').forEach(b=>b.onclick=()=>{
        $$('.chip').forEach(x=>x.classList.remove('on'));
        b.classList.add('on');
        cat = (b.textContent || '').trim();
        draw();
    });
    if(q) q.oninput = draw;
}

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
        const content = (uaForm.content ? uaForm.content.value.trim() : '');
        const titleOk = title.length > 0 && title.length <= 200;
        const categoryOk = category.length > 0;
        const contentOk = content.length > 0 && content.length <= 20000;
        showError('title', !titleOk);
        showError('category', !categoryOk);
        showError('content', !contentOk);
        // Image is optional. If present, validate type + size on the client
        // for a fast UX; the server also validates both.
        const file = uaForm.image && uaForm.image.files && uaForm.image.files[0];
        if (file) {
            const allowed = ['image/jpeg','image/png','image/webp'];
            if (!allowed.includes(file.type) || file.size > 5 * 1024 * 1024) {
                e.preventDefault();
                toast('الصورة غير صالحة (نوع مدعوم، الحد الأقصى 5MB)');
                return;
            }
        }
        if (!titleOk || !categoryOk || !contentOk) {
            e.preventDefault();
            toast('يرجى تعبئة جميع الحقول المطلوبة');
            return;
        }
    });
    ['title','category','content'].forEach(name => {
        const el = uaForm[name];
        if (el) el.addEventListener('input', () => showError(name, false));
        if (el && el.tagName === 'SELECT') el.addEventListener('change', () => showError(name, false));
    });
}

/* Phase 4: /visitor forms are now hooked by dedicated IIFEs at the end
   of this file (#eventRegForm, #membershipForm). The old generic
   .visitor-form toast handler has been removed. */


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

    /* Scoping helper: tag the shared #box with .ev-modal so the
       event create/edit CSS (compact layout + 600px width + 85vh +
       internal scroll) applies without affecting other modals.
       We strip the class next time #modal loses .show, via a one-shot
       MutationObserver — avoids the transitionend-bubbling bug. */
    const applyEvModalScope = () => {
        const box = $('#box'); const m = $('#modal');
        if (!box || !m) return;
        box.classList.add('ev-modal');
        const obs = new MutationObserver(() => {
            if (!m.classList.contains('show')) {
                box.classList.remove('ev-modal');
                obs.disconnect();
            }
        });
        obs.observe(m, { attributes: true, attributeFilter: ['class'] });
    };

    // Resolve a stored Event.image_path to a browsable URL for the modal
    // preview. Supports both the DB-backed virtual path 'event-image/<id>'
    // (served by /events/<id>/image) and legacy static-folder paths.
    const resolveEventImageUrl = (p) => {
        if (!p) return '';
        if (p.indexOf('event-image/') === 0) {
            return '/events/' + p.slice('event-image/'.length) + '/image';
        }
        return '/static/' + p.replace(/^\/+/, '');
    };

    /* -------- ADD EVENT (real backend) --------
       Collects only the fields the Event model stores:
       title, date, time, is_public, image_path. */
    // Phase 10: canonical "نوع الفعالية" vocabulary — read from the server
    // via the leader-dashboard-data JSON block so it stays in sync with
    // app.py's EVENT_CATEGORIES without duplication in JS.
    const EVENT_CATEGORIES = (leaderData.event_categories && leaderData.event_categories.length)
        ? leaderData.event_categories
        : ['ورش', 'زيارات', 'ملتقيات', 'مسابقات'];
    const categoryOptions = (selected='') =>
        '<option value="">— اختر نوع الفعالية —</option>' +
        EVENT_CATEGORIES.map(c =>
            `<option value="${c}"${selected === c ? ' selected' : ''}>${c}</option>`
        ).join('');

    $('#addEventBtn')?.addEventListener('click',()=>{
        modal(`
            <h3>إنشاء فعالية جديدة</h3>
            <div class="dashboard-form">
                <label>عنوان الفعالية *</label>
                <input id="newEventName" placeholder="عنوان الفعالية" maxlength="200">

                <label>نوع الفعالية *</label>
                <select id="newEventCategory" required>${categoryOptions()}</select>

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

                <div class="form-row">
                    <div>
                        <label>آخر تاريخ للتسجيل (اختياري)</label>
                        <input id="newEventDeadlineDate" type="date">
                    </div>
                    <div>
                        <label>آخر وقت للتسجيل</label>
                        <input id="newEventDeadlineTime" type="time" value="23:59">
                    </div>
                </div>

                <label>السعة القصوى (اتركه فارغاً لسعة غير محدودة)</label>
                <input id="newEventCapacity" type="number" min="0" placeholder="مثال: 50">

                <label>الاهتمامات/التصنيفات (مفصولة بفواصل)</label>
                <input id="newEventTags" placeholder="مثال: الابتكار, ورش هندسية, الاستدامة">
                <p style="font-size:13px;color:#666;margin:4px 0 0">
                    سنُشعر الأعضاء الذين يطابقون اهتماماتهم أياً من هذه التصنيفات عند نشر الفعالية.
                </p>

                <label>اسم المكان (اختياري)</label>
                <input id="newEventLocationName" maxlength="200" placeholder="مثال: قاعة الملتقى، كلية الهندسة">

                <label>رابط الموقع (اختياري)</label>
                <input id="newEventLocationUrl" type="url" maxlength="500" placeholder="https://maps.google.com/...">
                <p style="font-size:13px;color:#666;margin:4px 0 0">يمكن لصق رابط Google Maps أو أي رابط خرائط آخر.</p>

                <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                    <input id="newEventIsPublic" type="checkbox">
                    <span>عرض الفعالية على الصفحة العامة</span>
                </label>

                <label>صورة الفعالية <span style="font-weight:400;color:#888">(اختياري — JPG / PNG / WEBP، الحد الأقصى 5MB)</span></label>
                <input id="newEventImageFile" type="file" accept="image/jpeg,image/png,image/webp">
                <div id="newEventImagePreview" style="margin-top:10px;display:none">
                    <img alt="معاينة" style="max-width:100%;max-height:200px;border-radius:10px;border:1px solid #e5e7eb">
                </div>

                <button class="btn btn-o" id="saveNewEvent">حفظ الفعالية</button>
            </div>
        `);
        applyEvModalScope();
        // Live preview for the new-event image picker.
        const newImgInput = $('#newEventImageFile');
        const newImgPrev = $('#newEventImagePreview');
        newImgInput?.addEventListener('change', () => {
            const f = newImgInput.files && newImgInput.files[0];
            if (!f) { newImgPrev.style.display = 'none'; return; }
            const img = newImgPrev.querySelector('img');
            img.src = URL.createObjectURL(f);
            newImgPrev.style.display = 'block';
        });
        $('#saveNewEvent').onclick = async () => {
            const title = $('#newEventName').value.trim();
            const category = $('#newEventCategory').value;
            const date = $('#newEventDate').value;
            const time = $('#newEventTime').value;
            if (!title) return toast('يرجى إدخال عنوان الفعالية');
            if (!category) return toast('نوع الفعالية مطلوب');
            if (!date) return toast('يرجى تحديد تاريخ الفعالية');
            const fd = new FormData();
            fd.append('title', title);
            fd.append('category', category);
            fd.append('date', date);
            fd.append('time', time || '00:00');
            fd.append('is_public', $('#newEventIsPublic').checked ? '1' : '0');
            const deadlineDate = $('#newEventDeadlineDate').value;
            const deadlineTime = $('#newEventDeadlineTime').value;
            if (deadlineDate) {
                fd.append('registration_deadline_date', deadlineDate);
                fd.append('registration_deadline_time', deadlineTime || '23:59');
            }
            const cap = $('#newEventCapacity').value.trim();
            if (cap !== '') fd.append('capacity', cap);
            const tags = $('#newEventTags').value.trim();
            if (tags) fd.append('tags', tags);
            const locName = $('#newEventLocationName').value.trim();
            if (locName) fd.append('location_name', locName);
            const locUrl = $('#newEventLocationUrl').value.trim();
            if (locUrl) fd.append('location_url', locUrl);
            const imgFile = newImgInput && newImgInput.files && newImgInput.files[0];
            if (imgFile) fd.append('image', imgFile);
            try {
                const res = await fetch('/leader/events', {method:'POST', body: fd});
                if (!res.ok) {
                    const err = await res.json().catch(()=>({error:'فشل الحفظ'}));
                    return toast(err.error || 'فشل الحفظ');
                }
                const data = await res.json().catch(() => ({}));
                closeModal();
                if (data.notified_members) {
                    toast(`تم إنشاء الفعالية · أُشعر ${data.notified_members} عضواً`);
                } else {
                    toast('تم إنشاء الفعالية بنجاح');
                }
                location.reload();
            } catch (_) { toast('تعذر الاتصال بالخادم'); }
        };
    });

    /* -------- EDIT EVENT -------- */
    document.addEventListener('click', e => {
        const btn = e.target.closest('[data-edit-event]');
        if (!btn) return;
        const row = btn.closest('tr[data-event-id]');
        if (!row) return;
        const id = row.dataset.eventId;
        const title = row.dataset.eventTitle || '';
        const date = row.dataset.eventDate || '';
        const time = row.dataset.eventTime || '';
        const isPublic = row.dataset.eventIsPublic === '1';
        const image = row.dataset.eventImage || '';
        const regCount = parseInt(row.dataset.eventRegCount || '0', 10);
        const taskCount = parseInt(row.dataset.eventTaskCount || '0', 10);
        const capacity = row.dataset.eventCapacity || '';
        const deadlineDate = row.dataset.eventDeadlineDate || '';
        const deadlineTime = row.dataset.eventDeadlineTime || '';
        const tags = row.dataset.eventTags || '';
        const category = row.dataset.eventCategory || '';
        const locationName = row.dataset.eventLocationName || '';
        const locationUrl = row.dataset.eventLocationUrl || '';
        const titleAttr = title.replace(/"/g, '&quot;');
        const imageAttr = image.replace(/"/g, '&quot;');
        const tagsAttr = tags.replace(/"/g, '&quot;');
        const locationNameAttr = locationName.replace(/"/g, '&quot;');
        const locationUrlAttr = locationUrl.replace(/"/g, '&quot;');
        modal(`
            <h3>تعديل الفعالية</h3>
            <p style="color:#888;font-size:13px;margin:4px 0 10px">
                معرّف الفعالية #${id} — ${regCount} تسجيل زائر · ${taskCount} مهمة مرتبطة
            </p>
            <div class="dashboard-form">
                <label>عنوان الفعالية *</label>
                <input id="editEventTitle" type="text" maxlength="200" value="${titleAttr}">

                <label>نوع الفعالية *</label>
                <select id="editEventCategory" required>${categoryOptions(category)}</select>

                <div class="lb-field-row">
                    <div>
                        <label>التاريخ *</label>
                        <input id="editEventDate" type="date" value="${date}">
                    </div>
                    <div>
                        <label>الوقت *</label>
                        <input id="editEventTime" type="time" value="${time}">
                    </div>
                </div>

                <div class="lb-field-row">
                    <div>
                        <label>آخر تاريخ للتسجيل (اختياري)</label>
                        <input id="editEventDeadlineDate" type="date" value="${deadlineDate}">
                    </div>
                    <div>
                        <label>آخر وقت للتسجيل</label>
                        <input id="editEventDeadlineTime" type="time" value="${deadlineTime || '23:59'}">
                    </div>
                </div>

                <label>السعة القصوى (اتركه فارغاً لسعة غير محدودة)</label>
                <input id="editEventCapacity" type="number" min="0" value="${capacity}">

                <label>الاهتمامات/التصنيفات (مفصولة بفواصل)</label>
                <input id="editEventTags" type="text" value="${tagsAttr}"
                       placeholder="مثال: الابتكار, ورش هندسية">

                <label>اسم المكان (اختياري)</label>
                <input id="editEventLocationName" type="text" maxlength="200" value="${locationNameAttr}"
                       placeholder="مثال: قاعة الملتقى، كلية الهندسة">

                <label>رابط الموقع (اختياري)</label>
                <input id="editEventLocationUrl" type="url" maxlength="500" value="${locationUrlAttr}"
                       placeholder="https://maps.google.com/...">

                <label style="display:flex;align-items:center;gap:8px;margin-top:14px">
                    <input id="editEventPublic" type="checkbox" ${isPublic ? 'checked' : ''}
                           style="width:auto;height:auto;margin:0">
                    <span>فعالية عامة (ظاهرة للزوار وقابلة للتسجيل)</span>
                </label>

                <label style="margin-top:14px">صورة الفعالية <span style="font-weight:400;color:#888">(JPG / PNG / WEBP — اختر صورة جديدة لاستبدال الحالية)</span></label>
                <input id="editEventImageFile" type="file" accept="image/jpeg,image/png,image/webp">
                <div id="editEventImagePreview" style="margin-top:10px;${image ? '' : 'display:none'}">
                    <img alt="الصورة الحالية" src="${imageAttr ? resolveEventImageUrl(image) : ''}"
                         style="max-width:100%;max-height:200px;border-radius:10px;border:1px solid #e5e7eb">
                </div>
                <label style="display:flex;align-items:center;gap:8px;margin-top:8px;cursor:pointer">
                    <input id="editEventImageRemove" type="checkbox" style="width:auto;height:auto;margin:0">
                    <span>إزالة الصورة الحالية</span>
                </label>

                <p id="editEventError" style="display:none;color:#c0392b;background:#fdecea;border:1px solid #f5c6cb;padding:8px 12px;border-radius:8px;margin:12px 0 0;font-size:13.5px"></p>

                <div class="row" style="margin-top:16px">
                    <button type="button" class="btn btn-o" id="saveEventEdit">حفظ التعديل</button>
                    <button class="btn btn-s" type="button" data-close>إلغاء</button>
                </div>
            </div>
        `);
        applyEvModalScope();
        const editErrorBox = $('#editEventError');
        const showEditError = (msg) => {
            if (editErrorBox) {
                editErrorBox.textContent = msg;
                editErrorBox.style.display = 'block';
                editErrorBox.scrollIntoView({behavior:'smooth', block:'center'});
            }
            toast(msg);
        };
        // Live preview: when the user picks a new file, show it.
        const editImgInput = $('#editEventImageFile');
        const editImgPrev = $('#editEventImagePreview');
        const editImgRemove = $('#editEventImageRemove');
        editImgInput?.addEventListener('change', () => {
            const f = editImgInput.files && editImgInput.files[0];
            if (!f) return;
            const img = editImgPrev.querySelector('img');
            img.src = URL.createObjectURL(f);
            editImgPrev.style.display = 'block';
            if (editImgRemove) editImgRemove.checked = false;
        });
        editImgRemove?.addEventListener('change', () => {
            if (editImgRemove.checked) {
                editImgPrev.style.display = 'none';
                if (editImgInput) editImgInput.value = '';
            } else if (image) {
                const img = editImgPrev.querySelector('img');
                img.src = resolveEventImageUrl(image);
                editImgPrev.style.display = 'block';
            }
        });
        const saveBtn = $('#saveEventEdit');
        const onSaveEdit = async (e) => {
            if (e) { e.preventDefault(); e.stopPropagation(); }
            if (saveBtn.disabled) return;
            if (editErrorBox) editErrorBox.style.display = 'none';
            const newTitle = $('#editEventTitle').value.trim();
            // Legacy events predate the category field (NULL in DB) — do not
            // block editing them. Only enforce category when the user picked
            // one or when it was already set; the backend edit endpoint
            // treats category as optional on update.
            const newCategory = $('#editEventCategory').value;
            const newDate = $('#editEventDate').value;
            const newTime = $('#editEventTime').value;
            if (!newTitle) return showEditError('يرجى إدخال عنوان الفعالية');
            if (!newDate || !newTime) return showEditError('يرجى إدخال التاريخ والوقت');
            const fd = new FormData();
            fd.append('title', newTitle);
            // Only send category if non-empty — avoids clearing it to NULL
            // when the row never had one (would otherwise be a silent change).
            if (newCategory) fd.append('category', newCategory);
            fd.append('date', newDate);
            fd.append('time', newTime);
            fd.append('is_public', $('#editEventPublic').checked ? '1' : '0');
            // Image: send the new file if picked; else send image_path=""
            // only when the user explicitly asked to remove; else send
            // nothing so the backend preserves the existing image.
            const editImgFile = editImgInput && editImgInput.files && editImgInput.files[0];
            if (editImgFile) {
                fd.append('image', editImgFile);
            } else if (editImgRemove && editImgRemove.checked) {
                fd.append('image_path', '');
            }
            // Always submit these three so edits clear them when emptied.
            fd.append('registration_deadline_date', $('#editEventDeadlineDate').value);
            fd.append('registration_deadline_time', $('#editEventDeadlineTime').value || '23:59');
            fd.append('capacity', $('#editEventCapacity').value.trim());
            fd.append('tags', $('#editEventTags').value.trim());
            // Always submit so edits clear the venue fields when emptied.
            fd.append('location_name', $('#editEventLocationName').value.trim());
            fd.append('location_url', $('#editEventLocationUrl').value.trim());
            const originalLabel = saveBtn.textContent;
            saveBtn.disabled = true;
            saveBtn.textContent = 'جارٍ الحفظ…';
            try {
                const res = await fetch(`/leader/events/${id}/edit`, {method:'POST', body: fd});
                if (!res.ok) {
                    const err = await res.json().catch(() => ({error:'فشل الحفظ'}));
                    saveBtn.disabled = false;
                    saveBtn.textContent = originalLabel;
                    return showEditError(err.error || 'فشل الحفظ');
                }
                const data = await res.json().catch(() => ({}));
                closeModal();
                let msg = 'تم حفظ التعديل';
                if (data.promoted) msg += ` · رُقّي ${data.promoted} من قائمة الانتظار`;
                if (data.notified_members) msg += ` · أُشعر ${data.notified_members} عضواً`;
                toast(msg);
                location.reload();
            } catch (_) {
                saveBtn.disabled = false;
                saveBtn.textContent = originalLabel;
                showEditError('تعذر الاتصال بالخادم');
            }
        };
        // Bind via both addEventListener and onclick so a stray reassignment
        // elsewhere can't silently remove the handler.
        saveBtn.addEventListener('click', onSaveEdit);
        saveBtn.onclick = onSaveEdit;
    });

    /* -------- DELETE EVENT (dependency-aware) -------- */
    document.addEventListener('click', async e => {
        const del = e.target.closest('[data-delete-event]');
        if (!del) return;
        const row = del.closest('tr[data-event-id]');
        const regCount = row ? parseInt(row.dataset.eventRegCount || '0', 10) : 0;
        const taskCount = row ? parseInt(row.dataset.eventTaskCount || '0', 10) : 0;
        const id = del.dataset.deleteEvent;

        // Build dependency-aware confirmation
        let confirmMsg;
        let force = false;
        if (regCount === 0 && taskCount === 0) {
            confirmMsg = 'هل تريد حذف هذه الفعالية؟ لا يمكن التراجع.';
        } else {
            confirmMsg =
                'هذه الفعالية مرتبطة بـ ' + regCount + ' تسجيل زائر و ' + taskCount + ' مهمة.\n' +
                'الحذف سيؤدي إلى:\n' +
                '  • حذف جميع تسجيلات الزوار المرتبطة.\n' +
                '  • فصل المهام عن الفعالية (دون حذفها).\n\n' +
                'هل تريد المتابعة؟ لا يمكن التراجع.';
            force = true;
        }
        if (!confirm(confirmMsg)) return;

        try {
            const fd = new FormData();
            if (force) fd.append('force', '1');
            const res = await fetch(`/leader/events/${id}/delete`, {method:'POST', body: fd});
            if (!res.ok) {
                const err = await res.json().catch(() => ({error:'فشل الحذف'}));
                return toast(err.error || 'فشل الحذف');
            }
            const data = await res.json().catch(() => ({}));
            let msg = 'تم حذف الفعالية';
            if (data.registrations_removed) msg += ` · حُذف ${data.registrations_removed} تسجيل`;
            if (data.tasks_unlinked) msg += ` · فُصلت ${data.tasks_unlinked} مهمة`;
            toast(msg);
            row?.remove();
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
                <label>الدور (اختياري)</label>
                <input id="newTaskRole" list="roleSuggestions" placeholder="منسق · منفذ · مراجع · تصميم بوستر">
                <datalist id="roleSuggestions">
                    <option value="منسق"></option>
                    <option value="منفذ"></option>
                    <option value="مراجع"></option>
                    <option value="تصميم بوستر"></option>
                </datalist>
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
            fd.append('role', $('#newTaskRole').value.trim());
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
            const curRole = row.dataset.taskRole || '';
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
                    <label>الدور (اختياري)</label>
                    <input id="editTaskRole" list="roleSuggestionsEdit" value="${curRole.replace(/"/g,'&quot;')}" placeholder="منسق · منفذ · مراجع · تصميم بوستر">
                    <datalist id="roleSuggestionsEdit">
                        <option value="منسق"></option>
                        <option value="منفذ"></option>
                        <option value="مراجع"></option>
                        <option value="تصميم بوستر"></option>
                    </datalist>
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
                fd.append('role', $('#editTaskRole').value.trim());
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

    /* -------- APPROVALS: article approval moved to a dedicated Phase 4
       IIFE at the end of this file, which POSTs to real backend routes.
       The old in-memory approvalStatuses block was removed. ------- */

    /* -------- SPONSORS (real backend) -------- */
    const sponsorFormBody = (vals) => {
        const v = vals || {name:'', tier:'Partner', logo:'', status:'current'};
        const esc = s => (s || '').replace(/"/g, '&quot;');
        return `
            <div class="dashboard-form">
                <label>اسم الراعي *</label>
                <input id="sponsorName" placeholder="اسم الراعي" value="${esc(v.name)}">
                <label>الفئة</label>
                <input id="sponsorTier" placeholder="Partner / Gold / Silver" value="${esc(v.tier) || 'Partner'}">
                <label>مسار شعار الراعي (داخل مجلد static فقط)</label>
                <input id="sponsorImage" placeholder="Image/sponsor.png" value="${esc(v.logo)}">
                <p style="font-size:13px;color:#666;margin:4px 0 0">يجب أن يكون المسار لملف موجود داخل static/. مثال: <code>Image/club-logo.png</code></p>
                <label>حالة الراعي *</label>
                <select id="sponsorStatus" required>
                    <option value="current" ${v.status === 'current' ? 'selected' : ''}>حالي</option>
                    <option value="previous" ${v.status === 'previous' ? 'selected' : ''}>سابق</option>
                </select>
            </div>
        `;
    };
    const readSponsorForm = () => {
        const name = $('#sponsorName').value.trim();
        if (!name) { toast('يرجى إدخال اسم الراعي'); return null; }
        const status = $('#sponsorStatus').value;
        if (status !== 'current' && status !== 'previous') {
            toast('يرجى اختيار حالة الراعي');
            return null;
        }
        const fd = new FormData();
        fd.append('name', name);
        fd.append('tier', $('#sponsorTier').value.trim() || 'Partner');
        fd.append('logo_path', $('#sponsorImage').value.trim());
        fd.append('status', status);
        return fd;
    };

    $('#addSponsorBtn')?.addEventListener('click',()=>{
        modal(`<h3>إضافة راعٍ</h3>${sponsorFormBody()}
            <div class="row" style="margin-top:12px"><button class="btn btn-o" id="saveSponsor">إضافة الراعي</button></div>`);
        $('#saveSponsor').onclick = async () => {
            const fd = readSponsorForm();
            if (!fd) return;
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

    document.addEventListener('click', e => {
        const btn = e.target.closest('[data-edit-sponsor]');
        if (!btn) return;
        const card = btn.closest('.sponsor-dashboard-card');
        if (!card) return;
        const id = btn.dataset.editSponsor;
        const vals = {
            name: card.dataset.sponsorName || '',
            tier: card.dataset.sponsorTier || 'Partner',
            logo: card.dataset.sponsorLogo || '',
            status: card.dataset.sponsorStatus === 'previous' ? 'previous' : 'current',
        };
        modal(`<h3>تعديل الراعي</h3>${sponsorFormBody(vals)}
            <div class="row" style="margin-top:12px"><button class="btn btn-o" id="saveSponsorEdit">حفظ التعديل</button></div>`);
        $('#saveSponsorEdit').onclick = async () => {
            const fd = readSponsorForm();
            if (!fd) return;
            try {
                const res = await fetch(`/leader/sponsors/${id}/edit`, {method:'POST', body: fd});
                if (!res.ok) {
                    const err = await res.json().catch(()=>({error:'فشل الحفظ'}));
                    return toast(err.error || 'فشل الحفظ');
                }
                closeModal();
                toast('تم حفظ التعديل');
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
   PHASE 0 — MEMBER TASK STATUS
   ========================================= */

(function () {
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
   PHASE 4 — MEMBERSHIP APPLICATIONS
   ========================================= */
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
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
        c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const showSuccessPopup = (email, committeeName) => {
        if (typeof modal !== 'function') {
            showMsg('تم استلام طلبك بنجاح. عند قبوله ستصلك رسالة على بريدك الإلكتروني فيها رابط لتفعيل حسابك.', true);
            return;
        }
        if (msgBox) msgBox.style.display = 'none';
        modal(`<div style="text-align:center">
<div style="width:64px;height:64px;margin:0 auto 14px;border-radius:50%;background:#d4edda;display:grid;place-items:center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" style="width:34px;height:34px;stroke:#1e7e34;stroke-width:3"><polyline points="20 6 9 17 4 12"/></svg>
</div>
<h3 style="color:var(--pn);font-size:21px">تم إرسال طلبك بنجاح</h3>
<p style="margin-top:10px;line-height:1.9;color:#444">شكراً لاهتمامك بالانضمام إلى نادي رواد الصناعة، سيراجع قائد ${committeeName ? `لجنة <strong style="color:var(--pn)">${esc(committeeName)}</strong>` : 'اللجنة'} طلبك قريباً.</p>
<p style="margin-top:8px;line-height:1.9;color:#444">عند قبول طلبك ستصلك رسالة على بريدك الإلكتروني<br><strong dir="ltr" style="color:var(--pn);word-break:break-all">${esc(email)}</strong><br>فيها رابط لتعيين كلمة المرور وتفعيل حسابك.</p>
<p style="margin-top:8px;font-size:13px;color:#777">إذا لم تجد الرسالة، تحقق من مجلد الرسائل غير المرغوب فيها (Spam).</p>
<button type="button" class="btn btn-o" data-close style="margin-top:18px">حسناً</button>
</div>`);
    };
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            name: form.name.value.trim(),
            student_id: form.student_id.value.trim(),
            major: form.major.value.trim(),
            email: form.email.value.trim(),
            committee_id: form.committee_id.value,
            reason: form.reason.value.trim(),
        };
        if (!payload.name || !payload.student_id || !payload.major || !payload.email) {
            showMsg('يرجى تعبئة الاسم والرقم الجامعي والتخصص والبريد الإلكتروني', false);
            return;
        }
        if (!payload.committee_id) {
            showMsg('يرجى اختيار اللجنة التي تريد الانضمام إليها', false);
            return;
        }
        const committeeName = form.committee_id.selectedOptions[0]?.textContent.trim() || '';
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
                showSuccessPopup(payload.email, committeeName);
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

(function () {
    const list = document.getElementById('membershipRequestsList');
    if (!list) return;
    // Committee leaders review via /committee-leader/...; the club leader
    // only handles legacy requests that have no committee.
    const endpoint = list.dataset.endpoint || '/leader/membership-requests';
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

    const escHtml = (s) => String(s ?? '').replace(/[&<>"']/g,
        c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

    // Email delivery off or failed → let the leader share the link manually.
    const showActivationLink = (url) => {
        if (!url) return;
        if (typeof modal !== 'function') { prompt('رابط تفعيل الحساب', url); return; }
        modal(`<h3 style="color:#1b365d">رابط تفعيل الحساب</h3>
<p style="margin-top:12px;line-height:1.8">لم يُرسل البريد للمتقدم (خدمة الإيميل غير مفعّلة أو فشل الإرسال). انسخ الرابط وأرسله له بنفسك — يُستخدم مرة واحدة فقط.</p>
<input readonly dir="ltr" data-activation-link value="${escHtml(url)}" style="width:100%;margin-top:10px;padding:8px 10px;border:1px solid #ccc;border-radius:8px">
<div class="dashboard-actions" style="margin-top:12px">
<button type="button" class="dashboard-action approve" data-copy-activation-link>نسخ الرابط</button>
<button type="button" class="dashboard-action" data-close>إغلاق</button>
</div>`);
    };

    const statusHtml = (data) => {
        if (data.status === 'approved') {
            return '<span class="dashboard-status status-approved">معتمد</span><br>' + (data.activated
                ? '<small style="color:#27ae60">الحساب مفعّل</small>'
                : '<small style="color:#b9770e">بانتظار تفعيل الحساب</small>');
        }
        if (data.status === 'rejected') return '<span class="dashboard-status status-rejected">مرفوض</span>';
        return '<span class="dashboard-status status-pending">قيد المراجعة</span>';
    };

    const actionsHtml = (reqId, data, reasonTpl) => {
        const buttons = [];
        if (data.status === 'approved' && !data.activated) {
            buttons.push(`<button type="button" class="dashboard-action" data-resend-activation="${reqId}">إعادة إرسال رابط التفعيل</button>`);
        }
        if (reasonTpl) {
            buttons.push(`<button type="button" class="dashboard-action" data-view-reason="${reqId}">عرض السبب</button>`);
        }
        if (!buttons.length) return '—';
        return `<div class="dashboard-actions">${buttons.join('')}</div>${reasonTpl ? reasonTpl.outerHTML : ''}`;
    };

    const CONFIRM_MSG = {
        'approve': 'اعتماد طلب العضوية؟ سيصل للمتقدم بريد فيه رابط لتعيين كلمة المرور وتفعيل حسابه.',
        'reject': 'رفض طلب العضوية؟',
        'resend-activation': 'إرسال رابط تفعيل جديد؟ الرابط السابق سيتوقف عن العمل.',
    };

    const callRoute = async (reqId, action, button) => {
        const row = button.closest('tr[data-membership-id]');
        if (!row) return;
        if (!confirm(CONFIRM_MSG[action])) return;
        row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
            const res = await fetch(`${endpoint}/${reqId}/${action}`, {method:'POST'});
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (!res.ok) {
                if (typeof toast === 'function') toast(data.error || ('فشل الطلب ('+res.status+')'));
                row.querySelectorAll('button').forEach(b => { b.disabled = false; });
                return;
            }
            row.dataset.status = data.status;
            const statusCell = row.querySelector('[data-membership-status]');
            if (statusCell) statusCell.innerHTML = statusHtml(data);
            const actionsCell = row.querySelector('[data-membership-actions]');
            if (actionsCell) {
                const reasonTpl = actionsCell.querySelector(`template[data-reason-for="${reqId}"]`);
                actionsCell.innerHTML = actionsHtml(reqId, data, reasonTpl);
            }
            let msg;
            if (action === 'reject') {
                msg = 'تم رفض الطلب' + (data.email_sent
                    ? ' · أُرسل إشعار للمتقدم'
                    : ' · لم يُرسل إيميل (الخدمة غير مفعّلة)');
            } else if (data.activated) {
                // An account with this email already existed — it was promoted to member.
                msg = 'يوجد حساب بهذا البريد · تمت ترقيته إلى عضو';
            } else if (data.email_sent) {
                msg = action === 'approve'
                    ? 'تم اعتماد الطلب · أُرسل رابط التفعيل لبريد المتقدم'
                    : 'أُرسل رابط تفعيل جديد لبريد المتقدم';
            } else {
                msg = (action === 'approve' ? 'تم اعتماد الطلب' : 'تم إنشاء رابط جديد') + ' · لم يُرسل البريد';
                showActivationLink(data.activation_url);
            }
            if (typeof toast === 'function') toast(msg);
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
        const sb = e.target.closest('[data-resend-activation]');
        if (sb) { e.preventDefault(); callRoute(sb.dataset.resendActivation, 'resend-activation', sb); return; }
        const cb = e.target.closest('[data-copy-activation-link]');
        if (cb) {
            const input = document.querySelector('[data-activation-link]');
            if (!input) return;
            const copied = () => { if (typeof toast === 'function') toast('تم نسخ الرابط'); };
            const fallback = () => { input.select(); document.execCommand('copy'); copied(); };
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(input.value).then(copied, fallback);
            } else {
                fallback();
            }
            return;
        }
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


/* =========================================
   PHASE 4 — PERSISTENT ARTICLE APPROVAL
   ========================================= */
(function () {
    const list = document.getElementById('articleApprovalList');
    if (!list) return;

    const renderRow = (row, status) => {
        row.dataset.articleStatus = status;
        const statusCell = row.querySelector('[data-article-status-cell]');
        if (statusCell) {
            statusCell.innerHTML = status === 'approved'
                ? '<span class="dashboard-status status-approved">معتمد</span>'
                : status === 'rejected'
                ? '<span class="dashboard-status status-rejected">مرفوض</span>'
                : '<span class="dashboard-status status-pending">قيد المراجعة</span>';
        }
        const id = row.dataset.articleId;
        const actionsCell = row.querySelector('[data-article-actions]');
        if (actionsCell) {
            const buttons = [];
            if (status !== 'approved') buttons.push(`<button class="dashboard-action approve" data-approve-article="${id}">✓ اعتماد</button>`);
            if (status !== 'rejected') buttons.push(`<button class="dashboard-action reject" data-reject-article="${id}">✗ رفض</button>`);
            actionsCell.innerHTML = `<div class="dashboard-actions">${buttons.join('')}</div>`;
        }
    };

    const callRoute = async (articleId, action, button) => {
        const row = button.closest('tr[data-article-id]');
        if (!row) return;
        row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
            const res = await fetch(`/leader/articles/${articleId}/${action}`, {method:'POST'});
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (!res.ok) {
                if (typeof toast === 'function') toast(data.error || ('فشل الطلب ('+res.status+')'));
                row.querySelectorAll('button').forEach(b => { b.disabled = false; });
                return;
            }
            renderRow(row, data.status);
            if (typeof toast === 'function') {
                toast(action === 'approve' ? 'تم اعتماد المقال' : 'تم رفض المقال');
            }
        } catch (_) {
            if (typeof toast === 'function') toast('تعذر الاتصال بالخادم');
            row.querySelectorAll('button').forEach(b => { b.disabled = false; });
        }
    };

    document.addEventListener('click', (e) => {
        const ab = e.target.closest('[data-approve-article]');
        if (ab) { e.preventDefault(); callRoute(ab.dataset.approveArticle, 'approve', ab); return; }
        const rb = e.target.closest('[data-reject-article]');
        if (rb) { e.preventDefault(); callRoute(rb.dataset.rejectArticle, 'reject', rb); }
    });
})();


/* =========================================
   PHASE 4 — EVENT REGISTRATION
   ========================================= */
(function () {
    const form = document.getElementById('eventRegForm');
    if (!form) return;
    const msgBox = document.getElementById('eventFormMessage');
    const showMsg = (text, ok) => {
        if (!msgBox) return;
        msgBox.textContent = text;
        msgBox.style.display = 'block';
        msgBox.style.background = ok ? '#d4edda' : '#f8d7da';
        msgBox.style.color = ok ? '#155724' : '#721c24';
    };
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const eventId = form.event_id.value;
        if (!eventId) {
            showMsg('يرجى اختيار فعالية', false);
            return;
        }
        const payload = {
            name: form.name.value.trim(),
            email: form.email.value.trim(),
            phone: form.phone.value.trim(),
        };
        if (!payload.name || !payload.email) {
            showMsg('الاسم والبريد مطلوبان', false);
            return;
        }
        try {
            const res = await fetch(`/visitor/events/${eventId}/register`, {
                method: 'POST',
                headers: {'Content-Type':'application/json','Accept':'application/json'},
                body: JSON.stringify(payload),
            });
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (res.status === 201) {
                form.reset();
                showMsg(`تم تسجيلك بنجاح في: ${data.event_title}`, true);
            } else if (res.status === 409) {
                showMsg(data.error || 'أنت مسجّل بالفعل في هذه الفعالية', false);
            } else if (res.status === 400) {
                showMsg(data.error || 'بيانات غير مكتملة', false);
            } else if (res.status === 404) {
                showMsg('الفعالية غير موجودة', false);
            } else {
                showMsg('تعذر إرسال التسجيل (' + res.status + ')', false);
            }
        } catch (_) {
            showMsg('تعذر الاتصال بالخادم', false);
        }
    });
})();

(function () {
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
        m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-view-registrations]');
        if (!btn) return;
        e.preventDefault();
        const eventId = btn.dataset.viewRegistrations;
        try {
            const res = await fetch(`/leader/events/${eventId}/registrations`);
            if (!res.ok) {
                if (typeof toast === 'function') toast('فشل تحميل التسجيلات (' + res.status + ')');
                return;
            }
            const data = await res.json();

            const body = (data.count === 0)
                ? `<p class="lb-empty">لا توجد تسجيلات لهذه الفعالية حتى الآن.</p>`
                : `<table class="lb-reg-table">
                        <thead>
                            <tr>
                                <th class="c-num">#</th>
                                <th class="c-name">الاسم</th>
                                <th class="c-email">البريد الإلكتروني</th>
                                <th class="c-phone">رقم الجوال</th>
                                <th class="c-type">النوع</th>
                                <th class="c-date">وقت التسجيل</th>
                            </tr>
                        </thead>
                        <tbody>
                        ${data.registrations.map((r, i) => `
                            <tr>
                                <td class="c-num" data-label="#">${i + 1}</td>
                                <td class="c-name" data-label="الاسم"><b>${esc(r.name)}</b></td>
                                <td class="c-email lb-ltr" data-label="البريد الإلكتروني">${esc(r.email)}</td>
                                <td class="c-phone lb-ltr" data-label="رقم الجوال">${esc(r.phone || '—')}</td>
                                <td class="c-type" data-label="النوع">${r.user_id
                                    ? '<span class="lb-chip lb-chip-ok">عضو مسجّل</span>'
                                    : '<span class="lb-chip lb-chip-pend">زائر</span>'}</td>
                                <td class="c-date" data-label="وقت التسجيل">${esc(r.registered_at)}</td>
                            </tr>`).join('')}
                        </tbody>
                    </table>`;

            if (typeof modal !== 'function') return;
            modal(`
                <div class="lb-modal-head">
                    <div style="min-width:0">
                        <h3>تسجيلات الفعالية: ${esc(data.event_title)}</h3>
                        <p class="lb-modal-sub">إجمالي التسجيلات: <strong>${data.count}</strong></p>
                    </div>
                    <button type="button" class="lb-modal-close" data-close aria-label="إغلاق">×</button>
                </div>
                <div class="lb-modal-body">
                    ${body}
                </div>
                <div class="lb-modal-foot">
                    <button type="button" class="btn btn-s" data-close>إغلاق</button>
                </div>
            `);
            // Promote #box to wide variant AND tag the modal so the grid
            // container stretches to full viewport. Both classes must be
            // present together; they are stripped as a pair when the
            // modal closes.
            const box = document.getElementById('box');
            const modalEl = document.getElementById('modal');
            if (box) box.classList.add('box--wide');
            if (modalEl) modalEl.classList.add('modal-wide');
            // Strip the width-expansion classes ONLY when the modal is
            // actually closed (i.e., .show class removed by closeModal()).
            // The previous version also listened for `transitionend` on
            // the modal, which fires for ANY descendant transition
            // (hover effects on buttons/rows) and bubbles up — that
            // was removing .box--wide/.modal-wide on hover, causing the
            // box to shrink back to 500px mid-interaction. Removed.
            const strip = () => {
                box && box.classList.remove('box--wide');
                modalEl && modalEl.classList.remove('modal-wide');
            };
            const observer = new MutationObserver(() => {
                if (!modalEl.classList.contains('show')) {
                    strip();
                    observer.disconnect();
                }
            });
            observer.observe(modalEl, { attributes: true, attributeFilter: ['class'] });
        } catch (_) {
            if (typeof toast === 'function') toast('تعذر الاتصال بالخادم');
        }
    });
})();


/* =========================================
   NOTIFICATIONS (leader bell/bar)
   ========================================= */
(() => {
    const bar = document.getElementById('notifBar');
    if (!bar) return;
    const countEl = document.getElementById('notifCount');
    const listEl = document.getElementById('notifList');
    const markAll = document.getElementById('notifMarkAll');

    const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g,
        m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

    const render = (data) => {
        const unread = data.unread_count || 0;
        countEl.textContent = unread;
        if (unread === 0 && (!data.items || data.items.length === 0)) {
            bar.hidden = true;
            return;
        }
        bar.hidden = false;
        listEl.innerHTML = (data.items || []).map(n => `
            <li class="notif-item ${n.read ? 'is-read' : 'is-unread'}">
                <div class="notif-item-body">
                    <span class="notif-item-msg">${escapeHtml(n.message)}</span>
                    <small class="notif-item-time">${escapeHtml(n.created_at)}</small>
                </div>
                ${n.read ? '' : `<button type="button" class="notif-item-action" data-mark-notif="${n.id}">تحديد كمقروء</button>`}
            </li>
        `).join('');
    };

    const load = async () => {
        try {
            const r = await fetch('/notifications', { headers: { Accept: 'application/json' } });
            if (!r.ok) return;
            render(await r.json());
        } catch (_) {}
    };

    listEl?.addEventListener('click', async (e) => {
        const b = e.target.closest('[data-mark-notif]');
        if (!b) return;
        try {
            await fetch(`/notifications/${b.dataset.markNotif}/read`, { method: 'POST' });
            load();
        } catch (_) {}
    });
    markAll?.addEventListener('click', async () => {
        try {
            await fetch('/notifications/read-all', { method: 'POST' });
            load();
        } catch (_) {}
    });

    load();
    // Poll every 60s so a leader sees new submissions without refreshing.
    setInterval(load, 60000);
})();


/* =========================================
   INITIATIVES (leader approve/reject)
   ========================================= */
(() => {
    document.addEventListener('click', async (e) => {
        const ap = e.target.closest('[data-approve-init]');
        const rj = e.target.closest('[data-reject-init]');
        const btn = ap || rj;
        if (!btn) return;
        const id = (ap || rj).dataset.approveInit || (ap || rj).dataset.rejectInit;
        const action = ap ? 'approve' : 'reject';
        const msg = ap ? 'اعتماد هذه المبادرة ومنح نقاط المبادرة لصاحبها؟' : 'رفض هذه المبادرة؟';
        if (!confirm(msg)) return;
        const row = btn.closest('[data-pending-init-id]');
        row?.querySelectorAll('button').forEach(b => b.disabled = true);
        try {
            const r = await fetch(`/leader/initiatives/${id}/${action}`, { method: 'POST' });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                if (typeof toast === 'function') toast(data.error || `فشل الطلب (${r.status})`);
                row?.querySelectorAll('button').forEach(b => b.disabled = false);
                return;
            }
            if (typeof toast === 'function') {
                toast(action === 'approve'
                    ? `تم اعتماد المبادرة · +${data.points_awarded || 0} نقطة`
                    : 'تم رفض المبادرة');
            }
            row?.remove();
            const tbody = document.getElementById('pendingInitiativesList');
            if (tbody && tbody.querySelectorAll('tr[data-pending-init-id]').length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#888">لا توجد مبادرات بانتظار الاعتماد.</td></tr>';
            }
        } catch (_) {
            if (typeof toast === 'function') toast('تعذر الاتصال بالخادم');
            row?.querySelectorAll('button').forEach(b => b.disabled = false);
        }
    });
})();

/* =========================================================
   PHASE 6 — Shared live countdown + capacity renderer.

   Any element with [data-event-id] + [data-reg-deadline] (ISO datetime)
   + optional [data-event-capacity] is auto-rendered: a single setInterval
   updates every registered element. For capacity, we fetch the live
   status every POLL_MS so counts stay fresh without a page reload.
   Exposed as window.IPC.{renderOne, renderAll} so other pages can poke it.
   ========================================================= */
(function () {
    const TICK_MS = 1000;         // UI tick for countdown text
    const POLL_MS = 15000;        // Capacity refetch interval per card
    let pollState = new WeakMap();

    const pad2 = (n) => String(n).padStart(2, '0');

    function parseIso(s) {
        if (!s) return null;
        // Treat server-local naive datetimes as local time — matches the
        // backend, which uses naive datetime.now() throughout. If the
        // server later moves to UTC, append 'Z' there and parse the same way.
        const d = new Date(s);
        return isNaN(d.getTime()) ? null : d;
    }

    function fmtDiff(ms) {
        if (ms <= 0) return null;
        const s = Math.floor(ms / 1000);
        const d = Math.floor(s / 86400);
        const h = Math.floor((s % 86400) / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        if (d > 0) return `${d} يوم ${pad2(h)}:${pad2(m)}:${pad2(sec)}`;
        return `${pad2(h)}:${pad2(m)}:${pad2(sec)}`;
    }

    function setCountdown(el, label, variant) {
        if (!el) return;
        el.textContent = label;
        // Toggle parent variant classes for both the chip (events.html)
        // and the stat card (event-detail.html).
        const chip = el.closest('.ev-chip, .ed-stat');
        if (chip) {
            chip.classList.remove('urgent', 'closed');
            if (variant) chip.classList.add(variant);
        }
    }

    function renderCapacity(el, host) {
        if (!el) return;
        const cap = host.dataset.eventCapacity;
        const chip = el.closest('.ev-chip, .ed-stat');
        if (chip) chip.classList.remove('few', 'full', 'inf');

        if (cap === '' || cap == null) {
            el.textContent = 'سعة غير محدودة';
            if (chip) chip.classList.add('inf');
            return;
        }
        const capacity = parseInt(cap, 10);
        const confirmed = parseInt(host.dataset.statusConfirmed || '', 10);
        const remaining = host.dataset.statusRemaining;
        const waitlist = parseInt(host.dataset.statusWaitlist || '', 10);
        if (isNaN(capacity)) {
            el.textContent = '—';
            return;
        }
        if (remaining === '' || remaining == null || isNaN(parseInt(remaining, 10))) {
            // Server status hasn't loaded yet; show capacity only.
            el.textContent = `السعة: ${capacity}`;
            return;
        }
        const rem = parseInt(remaining, 10);
        let label;
        if (rem <= 0) {
            label = `مكتملة · قائمة الانتظار: ${isNaN(waitlist) ? 0 : waitlist}`;
            if (chip) chip.classList.add('full');
        } else if (rem <= 5) {
            label = `باقي ${rem} من ${capacity} مقعد`;
            if (chip) chip.classList.add('few');
        } else {
            label = `${isNaN(confirmed) ? '?' : confirmed}/${capacity} · باقي ${rem}`;
        }
        el.textContent = label;
    }

    function renderOne(host) {
        if (!host) return;
        const deadlineStr = host.dataset.regDeadline;
        const startStr = host.dataset.eventStart;
        const now = Date.now();

        const regEl = host.querySelector('[data-countdown="reg"]');
        const startEl = host.querySelector('[data-countdown="start"]');
        const capEl = host.querySelector('[data-capacity]');

        if (regEl) {
            const d = parseIso(deadlineStr);
            if (!d) {
                setCountdown(regEl, 'بدون موعد إغلاق', '');
            } else {
                const diff = d.getTime() - now;
                if (diff <= 0) {
                    setCountdown(regEl, 'التسجيل مغلق', 'closed');
                } else {
                    const prefix = 'يُغلق التسجيل خلال ';
                    setCountdown(regEl, prefix + fmtDiff(diff),
                                 diff < 60 * 60 * 1000 ? 'urgent' : '');
                }
            }
        }
        if (startEl) {
            const d = parseIso(startStr);
            if (!d) {
                setCountdown(startEl, '—', '');
            } else {
                const diff = d.getTime() - now;
                if (diff <= 0) {
                    setCountdown(startEl, 'الفعالية بدأت', 'closed');
                } else {
                    setCountdown(startEl, 'تبدأ خلال ' + fmtDiff(diff),
                                 diff < 60 * 60 * 1000 ? 'urgent' : '');
                }
            }
        }
        if (capEl) renderCapacity(capEl, host);
    }

    function pollCardIfNeeded(host) {
        const id = host.dataset.eventId;
        const cap = host.dataset.eventCapacity;
        if (!id || cap === '' || cap == null) return;
        const last = pollState.get(host) || 0;
        if (Date.now() - last < POLL_MS) return;
        pollState.set(host, Date.now());
        fetch(`/visitor/events/${id}/status`, {credentials: 'same-origin'})
            .then(r => r.ok ? r.json() : null)
            .then(s => {
                if (!s) return;
                host.dataset.statusConfirmed = s.confirmed;
                host.dataset.statusRemaining = (s.remaining == null) ? '' : s.remaining;
                host.dataset.statusWaitlist = s.waitlist;
                host.dataset.statusFull = s.is_full ? '1' : '0';
                host.dataset.statusClosed = s.registration_closed ? '1' : '0';
                host.dataset.regDeadline = s.effective_deadline || host.dataset.regDeadline;
                renderOne(host);
            })
            .catch(() => { /* ignore */ });
    }

    function renderAll() {
        const hosts = document.querySelectorAll('[data-event-id][data-reg-deadline]');
        hosts.forEach(h => {
            renderOne(h);
            pollCardIfNeeded(h);
        });
    }

    window.IPC = window.IPC || {};
    window.IPC.renderOne = renderOne;
    window.IPC.renderAll = renderAll;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', renderAll);
    } else {
        renderAll();
    }
    setInterval(renderAll, TICK_MS);
})();
