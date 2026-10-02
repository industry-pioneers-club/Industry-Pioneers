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
{t:'ورشة السلامة المهنية',c:'ورش',d:'2 أبريل 2026',h:'11:00 ص',l:'مبنى الورش',i:'event-5.png',u:0,x:'أساسيات السلامة في بيئات العمل الصناعية.'},
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
