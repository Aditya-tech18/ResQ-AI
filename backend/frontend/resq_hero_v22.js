/* ResQ AI V22 — replace only the existing hero. Preserve the original reset button and all app handlers. */
(()=>{'use strict';
const q=(s,r=document)=>r.querySelector(s);
function mount(){
 if(q('#resq22-hero'))return;
 const heading=[...document.querySelectorAll('h1')].find(e=>/ResQ AI.*Delivery/i.test(e.textContent));
 if(!heading)return;
 const original=heading.closest('.bg-white.rounded-xl')||heading.parentElement.parentElement.parentElement;
 if(!original||!original.parentElement)return;
 const hero=document.createElement('section');hero.id='resq22-hero';hero.className='resq22-hero';
 hero.innerHTML=`<div class="r22-top"><div class="r22-kicker"><span class="r22-red-dot"></span><strong>AI-POWERED LAST-MILE DELIVERY RECOVERY</strong><i></i><span class="r22-cluster">Visakhapatnam Cluster IXZ-04</span></div><div class="r22-actions"><span class="r22-pill"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 21 6v6c0 5-4 8-9 10C7 20 3 17 3 12V6zM12 6v12M7 12l3 3 7-7"/></svg>Recover At-Risk Deliveries</span><div class="r22-reset-slot"></div></div></div><div class="r22-body"><div class="r22-copy"><h1><span>ResQ AI</span> — Delivery<br>Recovery, Powered by AI.</h1><div class="r22-underline"></div><p>Detect <b>·</b> Call <b>·</b> Resolve</p></div><div class="r22-art" aria-hidden="true"><div class="r22-ring ring1"></div><div class="r22-ring ring2"></div><div class="r22-ring ring3"></div><svg viewBox="0 0 500 285" preserveAspectRatio="xMidYMid meet"><path d="M20 257C75 145 178 229 246 185S310 70 448 66" fill="none" stroke="#ee111a" stroke-width="2.2" stroke-dasharray="8 9"/><path d="M447 4c-24 0-38 18-38 40 0 27 38 65 38 65s38-38 38-65c0-22-14-40-38-40zm0 24a14 14 0 1 0 0 28 14 14 0 0 0 0-28" fill="#e9000c" fill-rule="evenodd"/><g fill="#cfd4d9" transform="translate(348 165)"><path d="M0 0h91v60H0zM96 15h26l26 28v17H96z"/><circle cx="25" cy="63" r="14" stroke="white" stroke-width="5"/><circle cx="120" cy="63" r="14" stroke="white" stroke-width="5"/></g></svg></div></div><div class="r22-steps">${[['Breakdown','Detected'],['Find Drivers','Scanned · Matches'],['AI Calls','In Progress'],['Approve','By Dispatcher'],['Deliver','Complete & Report']].map((v,i)=>`<div class="r22-step" data-index="${i}"><span class="r22-number">${i+1}</span><span class="r22-step-text"><strong>${v[0]}</strong><small>${v[1]}</small></span></div>`).join('<div class="r22-line"></div>')}</div>`;
 const reset=[...original.querySelectorAll('button')].find(b=>/reset/i.test(b.textContent||''));
 if(reset){reset.classList.add('r22-reset');reset.textContent='⟳  Reset';q('.r22-reset-slot',hero).append(reset)}else{q('.r22-reset-slot',hero).innerHTML='<button class="r22-reset" type="button" disabled title="Existing reset button unavailable">⟳  Reset</button>'}
 original.parentNode.insertBefore(hero,original);original.classList.add('r22-original-hidden');original.setAttribute('aria-hidden','true');
 const steps=[...original.querySelectorAll('button,div')].filter(e=>/Breakdown|Find Drivers|AI Calls|Approve|Deliver/.test(e.textContent||'')&&e.children.length<6);
 function refresh(){
  const text=original.innerText||'';let stage=0;
  if(/delivery (complete|completed)|handover complete/i.test(text))stage=4;
  else if(/approved by dispatcher|dispatcher approved/i.test(text))stage=3;
  else if(/AI Calls|rescue in progress|call connected/i.test(text))stage=2;
  else if(/drivers scanned|matches/i.test(text))stage=1;
  document.querySelectorAll('#resq22-hero .r22-step').forEach((e,i)=>{e.classList.toggle('active',i===stage);e.classList.toggle('complete',i<stage)});
  const call=original.querySelector('*');void call;void steps;
 }
 refresh();setInterval(refresh,1800);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();
