/* ResQ V4: original HTML retained; state and demo actions use a real local API. */
(() => {
  const style = document.createElement('style');
  style.textContent = `#resq-controls{position:fixed;bottom:16px;right:18px;z-index:1000;background:white;border:1px solid #e2e4e8;box-shadow:0 8px 30px #11182722;border-radius:12px;padding:12px;max-width:340px;font:12px Inter,Arial,sans-serif}#resq-controls button{padding:7px 10px;margin:3px;border:1px solid #ddd;border-radius:6px;background:#111827;color:white;cursor:pointer}#resq-controls button:disabled{opacity:.35;cursor:not-allowed}#resq-controls .danger{background:#e51e2a}#resq-controls .note{color:#64748b;font-size:10px;margin:5px 0}`;
  document.head.append(style);
  const panel = document.createElement('div');
  panel.id = 'resq-controls';
  panel.innerHTML = `<strong>ResQ V4 · Backend connected demo</strong><div class="note">SIMULATION — no phone calls, GPS, verified consent or live rescue approvals</div><div id="resq-stage">Connecting...</div><div id="resq-inbox" class="note"></div><div id="resq-buttons"></div><div id="resq-error" class="note" role="status"></div>`;
  document.body.append(panel);
  const actions = [
    ['find_drivers','Find drivers'], ['simulate_call','Simulate call: Suresh','Suresh'],
    ['simulate_call','Simulate call: Amit','Amit'], ['simulate_acceptance','Simulate acceptance'],
    ['simulate_approval','Simulate approval'], ['simulate_handover','Simulate handover'], ['reset','Reset demo']
  ];
  const allowed = {incident:['find_drivers'],ranked:['simulate_call'],calling:['simulate_acceptance','reset'],accepted:['simulate_approval','reset'],approved:['simulate_handover','reset'],completed:['reset']};
  async function refresh(){
    try {
      const response=await fetch('/api/v4/state',{cache:'no-store'});
      if(!response.ok) throw new Error('HTTP '+response.status);
      const data=await response.json();
      document.getElementById('resq-stage').textContent='Backend stage: '+data.stage.toUpperCase()+(data.driver?' · '+data.driver:'');
      document.getElementById('resq-inbox').textContent=data.telephony_inbox.connected?'Real webhook inbox: '+JSON.stringify(data.telephony_inbox.counts):'Real webhook inbox: not configured';
      const buttons=document.getElementById('resq-buttons'); buttons.replaceChildren();
      for(const [action,label,driver] of actions){
        const button=document.createElement('button');button.textContent=label;button.disabled=!(allowed[data.stage]||[]).includes(action);
        if(action==='reset')button.className='danger';
        button.addEventListener('click',async()=>{
          button.disabled=true;
          try{const r=await fetch('/api/v4/demo/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,driver:driver||null})});
            if(!r.ok){const error=await r.json();throw new Error(error.detail||'Action failed');}
            document.getElementById('resq-error').textContent='Saved to SQLite demo state';
          }catch(e){document.getElementById('resq-error').textContent=e.message;}finally{await refresh();}
        });buttons.append(button);
      }
    } catch(e){document.getElementById('resq-stage').textContent='Backend offline: '+e.message;}
  }
  refresh();setInterval(refresh,4000);
})();
