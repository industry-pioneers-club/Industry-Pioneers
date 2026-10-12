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


/* =========================================
   LEADER DASHBOARD
========================================= */

const leaderPage = path === '/leader/dashboard';

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
            image:'/static/Image/club-logo.png'
        },
        {
            name:'راعي النادي',
            image:'/static/Image/taibah-logo.png'
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
                    placeholder="/static/Image/sponsor.png">

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

const supervisorPage = path === '/supervisor/dashboard';

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