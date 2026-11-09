/* V20 UI upgrade: presentation only. Never replaces app state or voice handlers. */
(()=>{'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
function patchHero(){const hero=$('#resq19-hero');if(!hero)return;const h=$('h1',hero);if(h)h.innerHTML='<em>ResQ AI</em> — Delivery<br>Recovery, Powered by AI.';const route=$('.resq19-route',hero);if(route&&!$('#resq20-truck',hero)){route.insertAdjacentHTML('afterend','<svg id="resq20-truck" viewBox="0 0 90 45" aria-hidden="true" style="position:absolute;width:90px;right:5%;top:55%;opacity:.19"><path fill="#6d7d91" d="M3 7h49v26H3zM52 15h17l13 12v6H52z"/><circle fill="#44576c" cx="19" cy="35" r="7"/><circle fill="#44576c" cx="68" cy="35" r="7"/></svg>')};}
function patchMobile(){const roots=$$('.resq19-right');if(!roots.length)return;const root=roots[0];$$('h1,h2,h3',root).forEach(h=>{if(/report breakdown/i.test(h.textContent||'')){h.classList.add('resq20-mobile-title');h.innerHTML='Your Bike Stops.<br><span>Deliveries Don\'t.</span>';}});
const text=(root.innerText||'').toLowerCase();const active=/listening automatically|end demo call|driver speaking|ai rescue call|00:\d\d/.test(text);
const prior=$('#resq20-call-banner',root);
if(!active){if(prior)prior.remove();return}
if(!prior){const banner=document.createElement('div');banner.id='resq20-call-banner';banner.className='resq20-call-banner';banner.innerHTML='<div class="resq20-demo"><span class="resq20-dot">●</span> ResQ AI · VOICE RESCUE (DEMO)</div><h2>AI <em>Rescue</em> Call</h2><p>Coordinating nearby drivers to recover deliveries</p><div class="resq20-person">Suresh</div><div class="resq20-wave" aria-hidden="true">'+Array.from({length:17},(_,i)=>`<span style="--wave-height:${10+(i*11)%29}px;--wave-delay:${i*55}ms"></span>`).join('')+'</div><div class="resq20-timer" aria-label="Call timer">Live conversation</div>';root.prepend(banner)}
const banner=$('#resq20-call-banner',root);const timerText=(root.innerText||'').match(/\b\d{2}:\d{2}\b/);const timer=$('.resq20-timer',banner);if(timer&&timerText)timer.textContent=timerText[0];const nameMatch=(root.innerText||'').match(/\b(Suresh|Amit)\b/i);if(nameMatch){const person=$('.resq20-person',banner);if(person)person.textContent=nameMatch[0]}
}
function tick(){patchHero();patchMobile()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',tick);else tick();setInterval(tick,1500);
})();
