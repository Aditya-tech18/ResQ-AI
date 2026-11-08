(() => {
  'use strict';
  // V9 is a local simulated phone experience, NOT real outbound dialing.
  const css = document.createElement('style');
  css.textContent = `
    aside.fixed.left-0 {display:none!important}
    body>div.pl-\\[220px\\] {padding-left:0!important}
    header.fixed {left:0!important; height:58px!important}
    header.fixed>div:first-child>div:first-child {display:none!important}
    main {padding-top:60px!important}
    main h1 {font-size:clamp(38px,4.5vw,70px)!important;line-height:1.06!important;max-width:900px!important;letter-spacing:-.045em!important}
    #resq-v9-flow {background:#fff;border:1px solid #e3e8ef;border-left:5px solid #e51e2a;border-radius:16px;padding:15px 18px;margin:12px 0;box-shadow:0 7px 24px #1824370b}
    #resq-v9-flow h2 {font-size:18px;font-weight:850;margin:0}
    #resq-v9-flow .muted {font-size:12px;color:#64748b}
    #resq-v9-flow button,.resq-v9-phone button {background:#111827;color:#fff;border:0;border-radius:10px;padding:11px 15px;font-weight:800;cursor:pointer}
    #resq-v9-flow button.primary,.resq-v9-phone button.primary {background:#e51e2a}
    #resq-v9-flow button:disabled,.resq-v9-phone button:disabled {opacity:.5;cursor:not-allowed}
    #resq-v9-flow .actions {display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px}
    #resq-v9-flow .report {padding:11px 14px;background:#f7f9fc;border:1px solid #e2e8f0;border-radius:12px;min-width:0;overflow-wrap:anywhere}
    #resq-v9-flow .reports {display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:12px}
    #resq-v9-flow .report button {font-size:12px;padding:7px 11px;margin-top:7px;max-width:100%;white-space:normal}
    .resq-v9-phone {flex:1;display:flex;flex-direction:column;min-height:0;background:#fff;color:#111827;font-family:Inter,system-ui,sans-serif}
    .resq-v9-phone .dark {background:#111827;color:white;padding:22px 15px;text-align:center}
    .resq-v9-phone .dark h2 {font-size:26px;font-weight:850;margin:7px 0}
    .resq-v9-phone .body {padding:15px;display:flex;flex-direction:column;gap:11px;overflow-y:auto;flex:1}
    .resq-v9-phone .transcript {min-height:120px;max-height:215px;overflow:auto;border:1px solid #e2e8f0;border-radius:10px;padding:10px;font-size:12px;line-height:1.55}
    .resq-v9-phone .line {padding:7px 8px;border-radius:7px;margin-bottom:6px;background:#f1f5f9;overflow-wrap:anywhere}
    .resq-v9-phone .line.user {background:#fff1f2}
    .resq-v9-phone .status {padding:11px;background:#f1f5f9;border-radius:10px;font-size:12px;font-weight:650}
    .resq-v9-phone .wave {display:flex;justify-content:center;align-items:center;gap:4px;height:60px}
    .resq-v9-phone .wave i {width:4px;background:#f43f5e;border-radius:4px;height:20px;animation:resq-wave .75s ease-in-out infinite alternate}
    .resq-v9-phone .wave i:nth-child(2n) {animation-delay:.25s}
    .resq-v9-phone .wave i:nth-child(3n) {animation-delay:.4s}
    @keyframes resq-wave {to {height:45px}}
    @media(max-width:750px) {header.fixed{position:relative!important}main{padding-top:0!important}#resq-v9-flow{padding:12px}}
  `;
  document.head.appendChild(css);
  const hero = document.querySelector('main h1');
  const phoneShell = [...document.querySelectorAll('div')].find(el => el.classList.contains('h-[600px]') && el.classList.contains('overflow-hidden'));
  if (!hero || !phoneShell) {console.error('ResQ V9: original hero/phone not found');return;}
  // Remove original promotional clutter without disturbing map/plan cards.
  for (const el of document.querySelectorAll('header .bg-red-50, header .bg-slate-100')) {
    if (el.textContent.includes('Demo Rescue Scenario') || el.textContent.includes('AI Telephony')) el.remove();
  }
  const flow = document.createElement('section');flow.id='resq-v9-flow';
  hero.parentElement.insertAdjacentElement('afterend',flow);
  const statusBar = phoneShell.firstElementChild;
  phoneShell.replaceChildren(statusBar);
  const phone = document.createElement('div');phone.className='resq-v9-phone';phoneShell.appendChild(phone);
  const sleep = ms => new Promise(resolve => setTimeout(resolve,ms));
  const esc = s => String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let state = {incident:{},reports:[]};
  let phase='idle', actor=null, callId=null, clockStart=0, clockTimer=null, stopCapture=null, callGeneration=0;
  let mediaStream=null, audioCtx=null, audioPlayer=null, transcript=[];
  const roles=['Raju','Suresh','Amit'];
  const intro={
    Raju:'नमस्ते राजू जी, मैं ResQ AI से बोल रही हूँ। क्या आपकी डिलीवरी में कोई परेशानी हुई है? कृपया बताइए।',
    Suresh:'नमस्ते सुरेश जी, मैं ResQ AI से बोल रही हूँ। राजू की बाइक खराब हो गई है। क्या आप उनकी डिलीवरी में मदद कर पाएंगे?',
    Amit:'राम राम अमित जी, मैं ResQ AI से बोल रही हूँ। राजू की बाइक खराब हो गई है। क्या आप कुछ पार्सल ले पाएंगे?'
  };
  function status(msg){const el=document.getElementById('v9-status');if(el)el.textContent=msg;}
  async function req(url,body){const r=await fetch(url,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});let data;try{data=await r.json()}catch{data={detail:`HTTP ${r.status}`}}if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:`HTTP ${r.status}`);return data}
  async function sync(){state=await req('/api/v9/state');renderFlow();}
  function renderFlow(){
    const reports=state.reports||[];
    flow.innerHTML=`<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap"><div><h2>ResQ AI · Emergency Rescue</h2><div class="muted">Raju → Suresh → Amit · Live microphone demo</div></div><div class="muted">SIMULATED CALL · No telephone dialing</div></div>
      <div class="actions"><button class="primary" id="v9-place" ${phase!=='idle'?'disabled':''}>${phase==='idle'?'☎ Place Call to Raju':'Call in progress'}</button><button id="v9-reset">Reset demo</button><span class="muted" id="v9-topstatus">${esc(phase==='idle'?'Ready':'Voice session active')}</span></div>
      <div class="reports">${reports.map(r=>`<div class="report"><strong>${esc(r.driver)} · Rescue report</strong><div class="muted">${esc(r.facts.parcels)} parcels · ${esc(r.facts.eta_minutes)} min</div><div class="muted">${esc(r.facts.destination)}</div><div class="muted">Pending dispatcher approval</div><button data-report="${r.call_id}">Download report</button></div>`).join('')}</div>`;
    document.getElementById('v9-place').onclick=()=>begin('Raju');
    document.getElementById('v9-reset').onclick=reset;
    for(const button of flow.querySelectorAll('[data-report]'))button.onclick=()=>{
      const report=reports.find(r=>String(r.call_id)===button.dataset.report);if(!report)return;
      const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download=`resq-${report.driver.toLowerCase()}-report.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
  }
  function phoneView(name){
    phone.innerHTML=`<div class="dark"><div style="font-size:10px;color:#34d399;font-weight:700">● RESQ AI · LOCAL VOICE DEMO</div><h2>${esc(name)}</h2><div style="font-size:12px;color:#fda4af">${name==='Raju'?'Breakdown reporting':name==='Suresh'?'Telugu / Hindi':'Haryanvi / Hindi'}</div><div style="font-size:22px;font-weight:800;margin-top:12px" id="v9-clock">00:00</div><div class="wave">${Array.from({length:15},()=>'<i></i>').join('')}</div></div><div class="body"><div class="status" id="v9-status">Connecting…</div><div class="transcript" id="v9-transcript" aria-live="polite"></div><div style="font-size:11px;color:#64748b">Hands-free: AI speaks → listen → 2s silence → AI responds</div><button id="v9-end">End demo call</button></div>`;
    document.getElementById('v9-end').onclick=()=>finish(false);
  }
  function line(who,text){transcript.push({who,text});const host=document.getElementById('v9-transcript');if(!host)return;const div=document.createElement('div');div.className='line '+(who==='Driver'?'user':'');div.textContent=`${who}: ${text}`;host.appendChild(div);host.scrollTop=host.scrollHeight;}
  function startClock(){clockStart=Date.now();clearInterval(clockTimer);clockTimer=setInterval(()=>{const el=document.getElementById('v9-clock');if(el){const sec=Math.floor((Date.now()-clockStart)/1000);el.textContent=`${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;}},250)}
  async function speak(text,language){
    status('AI speaking · Gnani Timbre');
    const response=await fetch('/api/v8/voice/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,language:language==='te'?'te-IN':language==='en'?'en-IN':'hi-IN',gender:'female'})});
    if(!response.ok){let msg;try{msg=(await response.json()).detail}catch{msg=`HTTP ${response.status}`}throw Error(`Gnani Timbre: ${msg}`)}
    const blob=await response.blob();const url=URL.createObjectURL(blob);
    await new Promise((resolve,reject)=>{audioPlayer=new Audio(url);audioPlayer.onended=resolve;audioPlayer.onerror=()=>reject(Error('Timbre audio playback failed'));audioPlayer.play().catch(reject)}).finally(()=>{URL.revokeObjectURL(url);audioPlayer=null});
  }
  async function prepareMic(){
    if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)throw Error('Use Chrome/Edge on localhost and allow microphone access');
    if(!mediaStream)mediaStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(!audioCtx){audioCtx=new (window.AudioContext||window.webkitAudioContext)();await audioCtx.resume();}
  }
  // Voice activity detection: continuous audio sampling, stops after ~2s of silence.
  async function capture(token){
    await prepareMic();
    const ctx=audioCtx;
    const source=ctx.createMediaStreamSource(mediaStream);
    const analyser=ctx.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
    const samples=new Float32Array(analyser.fftSize);
    const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    if(!mime)throw Error('Browser audio recording format unsupported');
    const recorder=new MediaRecorder(mediaStream,{mimeType:mime});
    const chunks=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    let started=Date.now(),heard=false,lastVoice=started,finished=false;
    const done=new Promise((resolve,reject)=>{recorder.onstop=()=>resolve(new Blob(chunks,{type:mime}));recorder.onerror=()=>reject(Error('Microphone recording error'))});
    recorder.start(250);
    status('Listening automatically · speak now');
    const threshold=0.018; // May require calibration in noisy environments.
    await new Promise(resolve=>{
      const poll=()=>{
        if(finished)return;
        analyser.getFloatTimeDomainData(samples);
        let sum=0;for(const x of samples)sum+=x*x;
        const rms=Math.sqrt(sum/samples.length),now=Date.now();
        if(rms>threshold){heard=true;lastVoice=now;}
        const end=token!==callGeneration || (heard && now-lastVoice>=2000) || now-started>25000;
        if(end){finished=true;resolve();}else setTimeout(poll,75);
      };poll();
    });
    if(recorder.state!=='inactive')recorder.stop();
    source.disconnect();analyser.disconnect();
    const audio=await done;
    if(token!==callGeneration)return null;
    if(!heard){status('No speech detected · retrying');return null;}
    return audio;
  }
  async function transcribe(blob){
    status('Gnani Prisma · transcribing');
    const form=new FormData();form.append('audio',blob,blob.type.includes('mp4')?'speech.m4a':'speech.webm');form.append('language','indic-auto');
    const response=await fetch('/api/v8/voice/transcribe',{method:'POST',body:form});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(`Gnani Prisma: ${data.detail||response.status}`);
    return data;
  }
  async function begin(name){
    if(phase!=='idle')return;
    const token=++callGeneration;
    actor=name;phase='ringing';transcript=[];renderFlow();phoneView(name);
    try{
      // User gesture grants microphone permission; recording starts after AI introduction.
      await prepareMic();
      status(`AI placing simulated call to ${name} · ringing`);
      await sleep(3000);if(token!==callGeneration)return;
      const call=await req('/api/v9/calls',{actor:name});callId=call.call_id;phase='active';startClock();renderFlow();
      line('AI',intro[name]);await speak(intro[name],'hi');
      await sleep(2000);
      while(token===callGeneration && phase==='active'){
        const audio=await capture(token);if(token!==callGeneration)return;
        if(!audio){await sleep(400);continue;}
        const stt=await transcribe(audio);
        const words=String(stt.transcript||'').trim();
        if(!words){status('Could not understand · please repeat');continue;}
        line('Driver',words);
        status('Gemini · deciding next question');
        const result=await req(`/api/v9/calls/${callId}/turn`,{transcript:words,detected_language:stt.language||null});
        if(token!==callGeneration)return;
        line('AI',result.reply);
        await sleep(2000);await speak(result.reply,result.language);
        if(result.end_call){await finish(true);return;}
        await sleep(2000);
      }
    }catch(error){
      status(`Paused: ${error.message}`);
      phase='error';renderFlow();
      // Never silently replace Gnani with browser voice and claim Gnani worked.
      const host=document.getElementById('v9-status');if(host)host.textContent=`Voice pipeline error: ${error.message}`;
    }
  }
  async function finish(completed){
    ++callGeneration;clearInterval(clockTimer);if(audioPlayer)audioPlayer.pause();
    if(stopCapture)stopCapture();
    if(mediaStream){mediaStream.getTracks().forEach(track=>track.stop());mediaStream=null;}
    if(audioCtx){await audioCtx.close().catch(()=>{});audioCtx=null;}
    const endedActor=actor,oldId=callId;actor=null;callId=null;phase='idle';
    if(!completed && oldId){try{await req(`/api/v9/calls/${oldId}/end`,{})}catch(e){console.warn(e)}}
    await sync();
    if(completed && endedActor==='Raju'){
      phoneView('Suresh');status('Raju report saved · calling Suresh next');
      await sleep(1300);begin('Suresh');
    }else if(completed && endedActor==='Suresh'){
      phoneView('Raju');status('Suresh rescue report sent to Raju app demo');
      const btn=document.getElementById('v9-place');if(btn){btn.textContent='☎ Call Amit (optional)';btn.onclick=()=>begin('Amit')}
    }else if(completed){phoneView('Raju');status('Rescue reports ready · dispatcher review pending');}
    else{phoneView('Raju');status('Call ended · report incomplete');}
  }
  async function reset(){
    if(phase!=='idle'){await finish(false)}
    await req('/api/v9/reset',{});await sync();phoneView('Raju');status('Ready · Place Call to Raju');
  }
  phoneView('Raju');status('Ready · Place Call to Raju');
  sync().catch(e=>status(`Backend unavailable: ${e.message}`));
})();
