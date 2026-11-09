/* Reference-aligned enhancement: do not overwrite real voice transcript, GPS, or backend state. */
(()=>{'use strict';
const q=(s,r=document)=>r.querySelector(s);
function update(){
 const hero=q('#resq19-hero');
 if(hero){const pill=q('.resq19-pill',hero);if(pill)pill.innerHTML='<b aria-hidden="true">⬡</b> &nbsp;Recover At-Risk Deliveries';}
 const right=q('.resq19-right');if(!right)return;
 const banner=q('#resq20-call-banner',right);
 if(banner){
  const demo=q('.resq20-demo',banner);if(demo)demo.innerHTML='<span class="resq20-dot">●</span> &nbsp;ResQ AI · Voice Rescue (Demo)';
  const flow=q('#resq21-flowline',right);
  if(!flow){const target=q('.resq20-call-banner',right);if(target){const el=document.createElement('div');el.id='resq21-flowline';el.className='resq21-flowline';el.innerHTML='<span><b>⚠</b>Detects Issue</span><i>➜</i><span><b>♧</b>Finds Nearby Driver</span><i>➜</i><span><b>⬡</b>Recovers Deliveries</span>';target.insertAdjacentElement('afterend',el)}}
 }else{const flow=q('#resq21-flowline',right);if(flow)flow.remove()}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',update);else update();
setInterval(update,1400);
})();
