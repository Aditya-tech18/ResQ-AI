/* ResQ V16: replace only the legacy AI Rescue Plan card. No voice handlers modified. */
(() => {
  'use strict';
  const ID='resq-v16-live-panel';
  const esc=v=>String(v==null||v===''?'Awaiting call data':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  let host=null, currentCall=null;
  const css=`#${ID}{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:24px;color:#0f172a;font-family:inherit;box-shadow:0 3px 14px #0f172a0a}#${ID} .rvhead{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:1px solid #e2e8f0;padding-bottom:17px;margin-bottom:17px}#${ID} h2{margin:0;font-size:22px;letter-spacing:-.5px}#${ID} .rvsub{font-size:13px;color:#64748b;margin-top:5px}#${ID} .rvbadge{padding:8px 12px;background:#eff6ff;color:#1d4ed8;border-radius:9px;font-weight:700;font-size:12px}#${ID} .rvgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}#${ID} .rvcell{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px;min-width:0}#${ID} .rvlabel{font-size:12px;color:#64748b;margin-bottom:8px}#${ID} .rvvalue{font-size:16px;font-weight:750;overflow-wrap:anywhere}#${ID} .rvfooter{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#64748b;font-size:12px;margin-top:17px}#${ID} .rvdot{display:inline-block;width:8px;height:8px;background:#10b981;border-radius:50%;margin-right:7px}@media(max-width:650px){#${ID}{padding:15px}#${ID} .rvgrid{grid-template-columns:1fr}#${ID} h2{font-size:19px}}`;
  if(!document.getElementById('resq-v16-style')){const s=document.createElement('style');s.id='resq-v16-style';s.textContent=css;document.head.append(s)}
  function locate(){
    if(host&&host.isConnected)return host;
    // Match the exact legacy card by BOTH unique strings, avoiding the whole dashboard.
    const nodes=[...document.querySelectorAll('h1,h2,h3,h4,div,section,article')].filter(e=>e.children.length<8 && e.textContent?.trim()==='AI Rescue Plan');
    for(const n of nodes){let p=n;for(let depth=0;depth<7&&p;depth++,p=p.parentElement){const t=p.textContent||'';if(t.includes('Review & Approve Rescue Plan')&&t.includes("Raju's Load")&&t.length<6500){host=p;host.replaceChildren();host.id=ID;return host}}}
    return null;
  }
  async function get(url){try{const r=await fetch(url,{cache:'no-store'});return r.ok?await r.json():null}catch{return null}}
  const first=(...v)=>v.find(x=>x!==null&&x!==undefined&&x!=='')??null;
  function reportFrom(x){if(!x)return null;return Array.isArray(x)?x[0]??null:x}
  async function update(){
    const el=locate();if(!el)return;
    const [state, reports]=await Promise.all([get('/api/v9/state'),get('/api/v16/reports')]);
    const incident=state?.incident||{};
    const call=first(state?.active_call,state?.call,state?.current_call,null);
    const activeId=first(call?.id,state?.call_id,state?.active_call_id,null);
    const entries=Array.isArray(reports)?reports:[];
    const r=entries.find(x=>activeId!=null&&String(x.call_id)===String(activeId))||entries[0]||null;
    const name=first(r?.rescue_driver,call?.driver,call?.candidate,'Suresh');
    const values=[
      ['Breakdown driver',first(r?.breakdown_driver,incident.driver,'Raju')],
      ["Raju's current location",first(r?.breakdown_location,incident.location)],
      ['Rescue driver',name],
      ['Nearby parcels',first(r?.nearby_parcels,Array.isArray(r?.parcel_ids)?r.parcel_ids.length:null)],
      ["Driver's next route",first(r?.next_route)],
      ["Driver's current location",first(r?.current_location)],
      ['Pickup ETA',r?.pickup_eta_minutes!=null?`${r.pickup_eta_minutes} min`:null],
      ['Call status',first(r?.call_status,call?.status,incident.status)]
    ];
    const badge=first(r?.call_status,call?.status,'Awaiting call');
    const markup=`<div class="rvhead"><div><h2>Live Rescue Call Report</h2><div class="rvsub">${esc(name)} · Updated from incident and call records</div></div><span class="rvbadge"><span class="rvdot"></span>${esc(badge)}</span></div><div class="rvgrid">${values.map(([k,v])=>`<div class="rvcell"><div class="rvlabel">${esc(k)}</div><div class="rvvalue">${esc(v)}</div></div>`).join('')}</div><div class="rvfooter"><span>GPS is shown only when available · No assumed ETA</span><span>Dispatcher approval required</span></div>`;
    if(el.innerHTML!==markup)el.innerHTML=markup;
  }
  update();setInterval(update,1200);
})();
