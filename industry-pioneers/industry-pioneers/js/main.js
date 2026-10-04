const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const page=location.pathname.split('/').pop()||'index.html';
const NAV=[['index.html','الرئيسية'],['about.html','عن النادي'],['events.html','الفعاليات'],['gazette.html','جريدة الصناعة'],['partners.html','الشركاء والرعاة']];

/* Shared navbar + footer (edit once, applies to every page) */
document.body.insertAdjacentHTML('afterbegin',`<header class="nav"><a class="brand" href="index.html"><img src="Image/club-logo.png" alt="نادي رواد الصناعة"><i></i><img src="Image/taibah-logo.png" alt="جامعة طيبة"></a>
<button class="burger" aria-label="القائمة">☰</button><div class="menu"><nav class="links">${NAV.map(([h,t])=>`<a href="${h}"${h===page?' class="on"':''}>${t}</a>`).join('')}</nav><a class="login-btn" href="login.html">تسجيل الدخول</a></div></header>`);
document.body.insertAdjacentHTML('beforeend',`<footer class="mini-footer">© 2026 نادي رواد الصناعة — جامعة طيبة</footer><div class="modal" id="modal"><div class="box" id="box"></div></div><div class="toast" id="toast"></div>`);
$('.burger').onclick=()=>$('.nav').classList.toggle('open');
addEventListener('error',e=>{if(e.target.tagName==='IMG')e.target.classList.add('missing')},true); // hide broken/missing images
const hideBroken=()=>$$('img').forEach(i=>{if(i.complete&&!i.naturalWidth)i.classList.add('missing')});addEventListener('load',hideBroken);

let tt;const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(tt);tt=setTimeout(()=>t.classList.remove('show'),2600)};
const modal=h=>{$('#box').innerHTML=h;$('#modal').classList.add('show')},closeModal=()=>$('#modal').classList.remove('show');
$('#modal').onclick=e=>{if(e.target.id==='modal'||e.target.dataset.close!==undefined)closeModal()};

/* EVENTS (mock data) */
const EV=[
{t:'ورشة التحول الرقمي في الصناعة',c:'ورش',d:'15 نوفمبر 2026',h:'10:00 ص',l:'كلية الهندسة',i:'event-1.png',u:1,x:'تعرّف على أدوات الذكاء الاصطناعي وإنترنت الأشياء في خطوط الإنتاج.'},
{t:'زيارة ميدانية لمصنع الأسمنت',c:'زيارات',d:'22 نوفمبر 2026',h:'8:00 ص',l:'ينبع الصناعية',i:'event-2.png',u:1,x:'رحلة لمعايشة مواقع العمل والتعرف على مراحل الإنتاج.'},
{t:'هاكثون',c:'ملتقيات',d:'13 2026 مايو',h:'9:00 ص',l:'عمادة شؤون الطلاب',i:'event-3.png',u:1,x:'مبادرة تهدف إلى بناء جسر فعال بين الطلاب والقطاعات الصناعية'},
{t:'ملتقى الابتكار الصناعي',c:'ملتقيات',d:'13 مايو 2026',h:'9:00 ص',l:'عمادة شؤون الطلاب',i:'event-4.png',u:0,x:'مبادرة تهدف إلى بناء جسر فعال بين الطلاب والقطاعات الصناعية'},
{t:'التصنيع الذكي',c:'لقاء',d:'26 فبراير 2026',h:'5:00 م',l:'حي المغيسلة',i:'event-5.png',u:0,x:'خلق بيئة تفاعلية  بين العامة وتثقيفهم في المجال الصناعي والتعدين'},
{t:'جولة داخل المصانع السعودية',c:'زيارات',d:'16 ابريل 2026',h:'9:00 ص',l:'مقر شركة الزجاج العربية المتحدة(ينبع)',i:'event-6.png',u:0,x:'زيارة ميدانية بهدف تعريف الطلاب ببيئة العمل الصناعية.'}];
const evBox=$('#upcoming');
if(evBox){let cat='الكل';const q=$('#q');
 const card=(e,n)=>`<article class="ev"><div class="ph"><img src="Image/${e.i}" alt="${e.t}"></div><div class="eb"><span class="tag">${e.c}</span><h3>${e.t}</h3><ul><li><b>التاريخ:</b> ${e.d}</li><li><b>الوقت:</b> ${e.h}</li><li><b>المكان:</b> ${e.l}</li></ul><p>${e.x}</p>${e.u?`<button class="btn btn-o" data-reg="${n}">سجّل الآن</button>`:'<button class="btn btn-d" disabled>انتهت الفعالية</button>'}</div></article>`;
 const draw=()=>{[['#upcoming',1],['#previous',0]].forEach(([s,u])=>{const l=EV.map((e,n)=>[e,n]).filter(([e])=>e.u===u&&(cat==='الكل'||e.c===cat)&&(e.t+e.x+e.l).includes(q.value.trim()));$(s).innerHTML=l.length?l.map(([e,n])=>card(e,n)).join(''):'<p class="empty">لا توجد نتائج مطابقة</p>'})};
 $$('.chip').forEach(b=>b.onclick=()=>{$$('.chip').forEach(x=>x.classList.remove('on'));b.classList.add('on');cat=b.textContent;draw()});
 q.oninput=draw;draw();
 document.addEventListener('click',ev=>{const b=ev.target.closest('[data-reg]');if(!b)return;const e=EV[b.dataset.reg];
  modal(`<h3>التسجيل في: ${e.t}</h3><p>${e.d} — ${e.h}</p><input id="mail" placeholder="البريد الجامعي"><div class="row"><button class="btn btn-o" id="ok">تأكيد التسجيل</button><button class="btn btn-d" data-close>إلغاء</button></div>`);
  $('#ok').onclick=()=>{closeModal();toast('تم تسجيلك في الفعالية (تجريبي)')}})}

/* GAZETTE (mock data) */
const AR=[
{t:'الصناعة السعودية وفرص التحول نحو الاقتصاد الأخضر',a:'أ. سارة العتيبي',s:'الطاقة',d:'28 سبتمبر 2026',i:'article-1.png',n:24,x:'نظرة على أبرز الفرص المتاحة للخريجين في قطاعات الطاقة المتجددة والتصنيع المستدام.'},
{t:'كيف يغيّر الذكاء الاصطناعي خطوط الإنتاج؟',a:'م. خالد الحربي',s:'التقنية',d:'14 سبتمبر 2026',i:'article-2.png',n:41,x:'تطبيقات الصيانة التنبؤية والرقابة الذكية في المصانع الحديثة.'},
{t:'السلامة المهنية: ثقافة قبل أن تكون قواعد',a:'د. نورة الجهني',s:'السلامة',d:'1 سبتمبر 2026',i:'article-3.png',n:18,x:'لماذا تبدأ السلامة من سلوك الفرد وكيف تبني المنشآت ثقافتها.'},
{t:'سلاسل الإمداد: من المصنع إلى المستهلك',a:'أ. فهد القحطاني',s:'اللوجستيات',d:'20 أغسطس 2026',i:'article-4.png',n:12,x:'مدخل مبسّط لفهم دور سلاسل الإمداد في تنافسية الصناعة.'}];
const ab=$('#articles');
if(ab){ab.innerHTML=AR.map((a,n)=>`<article class="ev"><div class="ph"><img src="Image/${a.i}" alt="${a.t}"></div><div class="eb"><span class="tag">${a.s}</span><h3>${a.t}</h3><ul><li><b>الكاتب:</b> ${a.a}</li><li><b>التاريخ:</b> ${a.d}</li></ul><p>${a.x}</p><div><button class="like" data-like="${n}">♡ <span>${a.n}</span></button></div></div></article>`).join('');
 ab.onclick=e=>{const b=e.target.closest('[data-like]');if(!b)return;const a=AR[b.dataset.like],on=b.classList.toggle('on');a.n+=on?1:-1;b.firstChild.textContent=on?'♥ ':'♡ ';$('span',b).textContent=a.n}}

setTimeout(hideBroken,300);
/* LOGIN (mock only — no real authentication) */
const lf=$('#loginForm');
if(lf)lf.onsubmit=e=>{e.preventDefault();if(!lf.id.value.trim()||!lf.pw.value)return toast('الرجاء تعبئة جميع الحقول');toast('تم تسجيل الدخول بنجاح');setTimeout(()=>location.href='index.html',1200)};


/* =========================================
   LEADER DASHBOARD
========================================= */

const leaderPage = page === 'leader-dashboard.html';

if (leaderPage) {

    /* -------------------------
       MOCK TASKS
    ------------------------- */

    let leaderTasks = [
        {
            event:'ملتقى الابتكار الصناعي',
            task:'تنظيم التسجيل',
            member:'سارة أحمد',
            points:20,
            deadline:'10 مايو 2026',
            status:'قيد التنفيذ'
        },
        {
            event:'التصنيع الذكي',
            task:'إعداد المحتوى',
            member:'محمد خالد',
            points:30,
            deadline:'20 فبراير 2026',
            status:'مكتملة'
        },
        {
            event:'جولة داخل المصانع السعودية',
            task:'كتابة التقرير',
            member:'نورة علي',
            points:25,
            deadline:'20 أبريل 2026',
            status:'قيد التنفيذ'
        }
    ];

    let approvals = [
        {
            member:'محمد خالد',
            title:'مقال: الذكاء الاصطناعي في الصناعة',
            date:'14 سبتمبر 2026',
            points:30,
            status:'قيد المراجعة'
        },
        {
            member:'سارة أحمد',
            title:'مهمة تنظيم ملتقى الابتكار',
            date:'10 مايو 2026',
            points:20,
            status:'قيد المراجعة'
        }
    ];

    let sponsors = [
        {
            name:'شركة صناعات',
            image:'Image/club-logo.png'
        },
        {
            name:'راعي النادي',
            image:'Image/taibah-logo.png'
        }
    ];


    /* -------------------------
       TASKS
    ------------------------- */

    const leaderTasksBox = $('#leaderTasks');

    const drawLeaderTasks = () => {

        if(!leaderTasksBox) return;

        leaderTasksBox.innerHTML = leaderTasks.map((t,i)=>`

            <tr>

                <td>${t.event}</td>

                <td>${t.task}</td>

                <td>${t.member}</td>

                <td><b>${t.points}</b></td>

                <td>${t.deadline}</td>

                <td>
                    <span class="dashboard-status ${
                        t.status === 'مكتملة'
                        ? 'status-approved'
                        : 'status-pending'
                    }">
                        ${t.status}
                    </span>
                </td>

                <td>

                    <div class="dashboard-actions">

                        <button
                            class="dashboard-action"
                            data-edit-task="${i}">
                            تعديل
                        </button>

                        <button
                            class="dashboard-action reject"
                            data-delete-task="${i}">
                            حذف
                        </button>

                    </div>

                </td>

            </tr>

        `).join('');
    };


    drawLeaderTasks();


    /* -------------------------
       ADD EVENT
    ------------------------- */

    $('#addEventBtn')?.addEventListener('click',()=>{

        modal(`

            <h3>إنشاء فعالية جديدة</h3>

            <div class="dashboard-form">

                <label>اسم الفعالية</label>
                <input id="newEventName" placeholder="اسم الفعالية">

                <label>وصف الفعالية</label>
                <textarea id="newEventDescription"
                    placeholder="وصف الفعالية"></textarea>

                <div class="form-row">

                    <div>
                        <label>التاريخ</label>
                        <input id="newEventDate" type="date">
                    </div>

                    <div>
                        <label>الوقت</label>
                        <input id="newEventTime" type="time">
                    </div>

                </div>

                <label>المكان</label>
                <input id="newEventLocation" placeholder="مكان الفعالية">

                <label>متطلبات الفعالية</label>
                <textarea id="newEventRequirements"
                    placeholder="متطلبات الفعالية"></textarea>

                <button class="btn btn-o" id="saveNewEvent">
                    حفظ الفعالية
                </button>

            </div>
        `);


        $('#saveNewEvent').onclick=()=>{

            const name=$('#newEventName').value.trim();

            if(!name){
                return toast('يرجى إدخال اسم الفعالية');
            }

            closeModal();

            toast('تم إنشاء الفعالية بنجاح');
        };

    });


    /* -------------------------
       EDIT / DELETE TASK
    ------------------------- */

    document.addEventListener('click',e=>{

        const edit=e.target.closest('[data-edit-task]');

        if(edit){

            const i=Number(edit.dataset.editTask);
            const task=leaderTasks[i];

            modal(`

                <h3>تعديل المهمة</h3>

                <div class="dashboard-form">

                    <label>اسم المهمة</label>
                    <input id="editTaskName" value="${task.task}">

                    <label>العضو</label>
                    <input id="editTaskMember" value="${task.member}">

                    <label>النقاط</label>
                    <input id="editTaskPoints"
                        type="number"
                        value="${task.points}">

                    <label>موعد التسليم</label>
                    <input id="editTaskDeadline"
                        value="${task.deadline}">

                    <button class="btn btn-o" id="saveTaskEdit">
                        حفظ التعديل
                    </button>

                </div>
            `);


            $('#saveTaskEdit').onclick=()=>{

                task.task=$('#editTaskName').value;
                task.member=$('#editTaskMember').value;
                task.points=Number($('#editTaskPoints').value);
                task.deadline=$('#editTaskDeadline').value;

                drawLeaderTasks();

                closeModal();

                toast('تم تعديل المهمة');
            };

        }


        const del=e.target.closest('[data-delete-task]');

        if(del){

            const i=Number(del.dataset.deleteTask);

            leaderTasks.splice(i,1);

            drawLeaderTasks();

            toast('تم حذف المهمة');
        }

    });


    /* -------------------------
       APPROVALS
    ------------------------- */

    const approvalList=$('#approvalList');

    const drawApprovals=()=>{

        if(!approvalList) return;

        approvalList.innerHTML=approvals.map((a,i)=>`

            <tr>

                <td>${a.member}</td>

                <td>${a.title}</td>

                <td>${a.date}</td>

                <td><b>${a.points}</b></td>

                <td>

                    <span class="dashboard-status ${
                        a.status==='معتمد'
                        ? 'status-approved'
                        : a.status==='مرفوض'
                        ? 'status-rejected'
                        : 'status-pending'
                    }">

                        ${a.status}

                    </span>

                </td>

                <td>

                    <div class="dashboard-actions">

                        <button
                            class="dashboard-action"
                            data-view-approval="${i}">
                            عرض
                        </button>

                        ${
                            a.status==='قيد المراجعة'
                            ? `
                            <button
                                class="dashboard-action approve"
                                data-approve="${i}">
                                اعتماد
                            </button>

                            <button
                                class="dashboard-action reject"
                                data-reject="${i}">
                                رفض
                            </button>
                            `
                            :''
                        }

                    </div>

                </td>

            </tr>

        `).join('');
    };


    drawApprovals();


    document.addEventListener('click',e=>{

        const approve=e.target.closest('[data-approve]');

        if(approve){

            const i=Number(approve.dataset.approve);

            approvals[i].status='معتمد';

            drawApprovals();

            toast(`تم اعتماد المهمة وإضافة ${approvals[i].points} نقطة`);
        }


        const reject=e.target.closest('[data-reject]');

        if(reject){

            const i=Number(reject.dataset.reject);

            approvals[i].status='مرفوض';

            drawApprovals();

            toast('تم رفض المشاركة');
        }


        const view=e.target.closest('[data-view-approval]');

        if(view){

            const a=approvals[Number(view.dataset.viewApproval)];

            modal(`

                <h3>${a.title}</h3>

                <p style="margin-top:12px">
                    <b>العضو:</b> ${a.member}
                </p>

                <p style="margin-top:8px">
                    <b>التاريخ:</b> ${a.date}
                </p>

                <p style="margin-top:8px">
                    <b>النقاط:</b> ${a.points}
                </p>

            `);
        }

    });


    /* -------------------------
       SPONSORS
    ------------------------- */

    const sponsorList=$('#sponsorList');

    const drawSponsors=()=>{

        if(!sponsorList) return;

        sponsorList.innerHTML=sponsors.map((s,i)=>`

            <div class="sponsor-dashboard-card">

                <button
                    class="sponsor-delete"
                    data-delete-sponsor="${i}">
                    ×
                </button>

                <img src="${s.image}" alt="${s.name}">

                <h4>${s.name}</h4>

            </div>

        `).join('');
    };


    drawSponsors();


    $('#addSponsorBtn')?.addEventListener('click',()=>{

        modal(`

            <h3>إضافة راعٍ</h3>

            <div class="dashboard-form">

                <label>اسم الراعي</label>

                <input
                    id="sponsorName"
                    placeholder="اسم الراعي">

                <label>مسار شعار الراعي</label>

                <input
                    id="sponsorImage"
                    placeholder="Image/sponsor.png">

                <button class="btn btn-o" id="saveSponsor">
                    إضافة الراعي
                </button>

            </div>

        `);


        $('#saveSponsor').onclick=()=>{

            const name=$('#sponsorName').value.trim();
            const image=$('#sponsorImage').value.trim();

            if(!name || !image){
                return toast('يرجى تعبئة جميع الحقول');
            }

            sponsors.push({
                name,
                image
            });

            drawSponsors();

            closeModal();

            toast('تمت إضافة الراعي');
        };

    });


    document.addEventListener('click',e=>{

        const del=e.target.closest('[data-delete-sponsor]');

        if(!del) return;

        const i=Number(del.dataset.deleteSponsor);

        sponsors.splice(i,1);

        drawSponsors();

        toast('تم حذف الراعي');

    });

}


/* =========================================
   SUPERVISOR DASHBOARD
========================================= */

const supervisorPage = page === 'supervisor-dashboard.html';

if(supervisorPage){

    const exportBtn=$('#exportReportBtn');

    exportBtn?.addEventListener('click',()=>{

        const report=`

تقرير أداء نادي رواد الصناعة

إجمالي الفعاليات: 12
الفعاليات المكتملة: 8
الفعاليات قيد التنفيذ: 4
نسبة الإنجاز: 67%

تم إنشاء التقرير من لوحة تحكم المشرف الأكاديمي.
        `.trim();

        const blob=new Blob(
            [report],
            {type:'text/plain;charset=utf-8'}
        );

        const url=URL.createObjectURL(blob);

        const a=document.createElement('a');

        a.href=url;
        a.download='industry-pioneers-report.txt';

        a.click();

        URL.revokeObjectURL(url);

        toast('تم تحميل التقرير');
    });

}