(() => {
'use strict';
// Preserve screenshot layout. Only update original hero and original 3D phone interior.
const style=document.createElement('style');style.textContent=`
#resq-workflow{margin:12px 0;padding:13px 16px;background:#fff;border:1px solid #e2e7ed;border-left:4px solid #e51e2a;border-radius:10px;box-shadow:0 4px 14px #1522380c}
#resq-workflow .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
#resq-workflow button,.resq-phone button{border:0;border-radius:7px;background:#111827;color:white;padding:9px 12px;font-weight:750;font-size:12px;cursor:pointer}
#resq-workflow button.primary,.resq-phone button.primary{background:#e51e2a}
#resq-workflow button:disabled,.resq-phone button:disabled{opacity:.4;cursor:not-allowed}
#resq-workflow .hint{font-size:11px;color:#64748b;margin-top:5px}
.resq-phone{height:100%;background:#fff;color:#101828;font-family:Inter,system-ui,sans-serif;overflow:auto}
.resq-phone .dark{background:#111827;color:white;padding:16px 14px;text-align:center}
.resq-phone h3{font-size:20px;font-weight:850;margin:7px 0}
.resq-phone .content{padding:14px}
.resq-phone label{display:block;font-size:11px;font-weight:750;color:#64748b;margin:8px 0 3px}
.resq-phone input,.resq-phone textarea,.resq-phone select{display:block;width:100%;padding:8px;border:1px solid #dbe2eb;border-radius:7px;font-size:12px;color:#111827;background:white}
.resq-phone textarea{min-height:76px;resize:vertical}
.resq-phone .stat{background:#f4f6fa;border:1px solid #e4e8f0;border-radius:9px;padding:9px;margin:8px 0;font-size:12px}
.resq-phone .tiny{font-size:10px;color:#64748b;line-height:1.5}
.resq-phone .wave{height:54px;display:flex;align-items:center;justify-content:center;gap:3px}
.resq-phone .wave i{width:3px;background:#fb4755;border-radius:5px}
`;document.head.appendChild(style);
const hero=document.querySelector('main h1');
const banner=document.createElement('style');banner.textContent=`main h1{font-size:clamp(35px,3.6vw,58px)!important;line-height:1.08!important;letter-spacing:-.045em!important;max-width:800px}#resq-workflow{padding:8px 12px!important}#resq-workflow .hint{font-size:10px!important}.resq-phone .content{padding:12px!important}.resq-phone .stat{padding:7px!important;margin:6px 0!important}`;document.head.appendChild(banner);
if(!hero){console.error('ResQ: original dashboard hero not found');return}
const panel=document.createElement('section');panel.id='resq-workflow';
const heroSection=hero.parentElement;heroSection.insertAdjacentElement('afterend',panel);
const phoneScreen=[...document.querySelectorAll('div')].find(el=>el.classList.contains('h-[600px]') && el.classList.contains('overflow-hidden'));
if(!phoneScreen){console.error('ResQ: original 3D phone screen not found');return}
// Retain the original phone chassis and iPhone status bar.
const statusBar=phoneScreen.firstElementChild;
phoneScreen.replaceChildren(statusBar);
const phone=document.createElement('div');phone.className='resq-phone';phone.style.flex='1';phoneScreen.appendChild(phone);
const E=s=>String(s??'Pending').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state={stage:'new',incident:{}},extracted=null;
let turns=[], facts={}, recognizer=null, listening=false, busy=false;

const RESQ_REPORT_KEY = "resq_demo_driver_reports_v1";

function getDriverReports() {
  try {
    return JSON.parse(localStorage.getItem(RESQ_REPORT_KEY) || "{}");
  } catch (_) {
    return {};
  }
}

function saveDriverReport(report) {
  if (!report || !report.driver) return;
  const reports = getDriverReports();
  reports[report.driver] = report;
  localStorage.setItem(RESQ_REPORT_KEY, JSON.stringify(reports));
}

function renderDriverReports() {
  const host = document.getElementById("resq-report-history");
  if (!host) return;

  const reports = getDriverReports();
  host.replaceChildren();

  for (const name of ["Suresh", "Amit"]) {
    const report = reports[name];
    if (!report) continue;

    const card = document.createElement("div");
    card.style.cssText =
      "background:#f8fafc;border:1px solid #e2e8f0;" +
      "border-radius:9px;padding:10px;margin-top:8px;min-width:0;overflow-wrap:anywhere";

    const heading = document.createElement("strong");
    heading.textContent = name + " · Rescue report";

    const details = document.createElement("div");
    details.style.cssText =
      "font-size:12px;line-height:1.7;margin-top:5px";
    details.textContent =
      "Parcels: " + (report.parcels_accepted ?? "Unknown") +
      " · ETA: " + (report.eta_minutes ?? "Unknown") +
      " min · Destination: " + (report.destination ?? "Unknown");

    const download = document.createElement("button");
    download.textContent = "Download " + name + " report";
    download.style.cssText =
      "margin-top:7px;padding:7px 10px;cursor:pointer;max-width:100%;white-space:normal";

    download.addEventListener("click", () => {
      const blob = new Blob(
        [JSON.stringify(report, null, 2)],
        {type: "application/json"}
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "resq-" + name.toLowerCase() + "-report.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    card.append(heading, details, download);
    host.appendChild(card);
  }
}

const SpeechAPI=window.SpeechRecognition||window.webkitSpeechRecognition;
window.resqVoiceGender = "female";

function say(text){
  if (!("speechSynthesis" in window)) return;

  const synth = window.speechSynthesis;
  synth.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = state.candidate === "Suresh" ? "te-IN" : "hi-IN";
  utterance.rate = 0.94;
  utterance.pitch = window.resqVoiceGender === "male" ? 0.85 : 1.12;

  const voices = synth.getVoices();
  const locale = utterance.lang.slice(0, 2);

  const matching = voices.filter(v =>
    v.lang.toLowerCase().startsWith(locale)
  );

  const selected = matching.find(v => {
    const name = v.name.toLowerCase();
    if (window.resqVoiceGender === "male") {
      return /male|ravi|hemant|karthik/.test(name) &&
        !/female/.test(name);
    }
    return /female|lekha|kalpana|swara/.test(name);
  });

  if (selected || matching[0]) {
    utterance.voice = selected || matching[0];
  }

  synth.speak(utterance);
}
let resqAudio=null,resqRecorder=null,resqStream=null,resqChunks=[],resqRecording=false,resqCallStart=0,resqClock=null;
const resqSleep=ms=>new Promise(r=>setTimeout(r,ms));
function resqStatus(message){const e=document.getElementById('rv-micstatus');if(e)e.textContent=message;}
async function resqSpeak(text){
  if(resqAudio){resqAudio.pause();resqAudio=null;}
  try{
    const response=await fetch('/api/v8/voice/speak',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text,language:state.candidate==='Suresh'?'te-IN':'hi-IN',
        gender:window.resqVoiceGender||'female'})});
    if(!response.ok)throw Error('Timbre HTTP '+response.status);
    const url=URL.createObjectURL(await response.blob());
    const audio=new Audio(url);resqAudio=audio;
    try{await new Promise((resolve,reject)=>{
      audio.onended=resolve;audio.onerror=()=>reject(Error('Playback error'));
      audio.play().catch(reject);
    });}finally{URL.revokeObjectURL(url);}
    return true;
  }catch(error){
    resqStatus('Gnani Timbre unavailable: '+error.message+' · browser voice fallback');
    say(text);return false;
  }
}
async function resqMic(){
  if(resqRecording){
    resqRecording=false;resqRecorder.stop();
    resqStatus('Sending recording to Prisma…');return;
  }
  if(busy)return;
  try{
    window.speechSynthesis?.cancel();
    resqStream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4']
      .find(t=>MediaRecorder.isTypeSupported(t));
    resqRecorder=new MediaRecorder(resqStream,mime?{mimeType:mime}:undefined);
    resqChunks=[];
    resqRecorder.ondataavailable=e=>{if(e.data.size)resqChunks.push(e.data);};
    resqRecorder.onstop=async()=>{
      resqStream.getTracks().forEach(t=>t.stop());
      const mimeType=resqRecorder.mimeType||'audio/webm';
      const extension=mimeType.includes('mp4')?'m4a':'webm';
      const data=new FormData();
      data.append('audio',new Blob(resqChunks,{type:mimeType}),'recording.'+extension);
      data.append('language',state.candidate==='Suresh'?'te-IN':'indic-auto');
      try{
        const response=await fetch('/api/v8/voice/transcribe',{method:'POST',body:data});
        if(!response.ok)throw Error('Prisma HTTP '+response.status);
        const obj=await response.json();
        if(!obj.transcript?.trim())throw Error('Empty transcript');
        resqStatus('Prisma transcription ready · Gemini analysing');
        await processSpeech(obj.transcript);
      }catch(error){resqStatus('Prisma unavailable: '+error.message+' · type reply instead');}
    };
    resqRecorder.start();resqRecording=true;
    resqStatus('Recording · press Stop Mic to submit');
  }catch(error){resqStatus('Microphone error: '+error.message);}
}
async function resqPlaceCall(){
  resqStatus('Ringing · simulated call');
  await resqSleep(3000);
  resqCallStart=Date.now();
  const clock=document.getElementById('rv-call-clock');
  clearInterval(resqClock);
  if(clock)resqClock=setInterval(()=>{
    const t=Math.floor((Date.now()-resqCallStart)/1000);
    clock.textContent=String(Math.floor(t/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0');
  },250);
  const opening=intro();logTurn('AI',opening);
  await resqSpeak(opening);
  await resqSleep(2000);
  resqStatus('Your turn · Start Mic');
}

function intro(){return state.candidate==='Suresh'?'నమస్కారం సురేష్ గారు. నేను ResQ AI. రాజు బైక్ ఆగిపోయింది. మీరు కొన్ని పార్సిళ్లు తీసుకోగలరా?':'नमस्ते अमित जी। मैं ResQ AI बोल रहा हूँ। राजू की बाइक खराब हो गई है। क्या आप कुछ पार्सल ले सकते हैं?'}
function logTurn(who,txt){turns.push({role:who,text:txt});const el=document.getElementById('rv-dialog');if(el){const row=document.createElement('div');row.style.cssText='padding:6px 8px;margin:5px 0;border-radius:7px;background:'+(who==='AI'?'#eef2f8':'#fff1f2')+';font-size:11px;line-height:1.5';row.textContent=(who==='AI'?'AI: ':'Driver: ')+txt;el.appendChild(row);el.scrollTop=el.scrollHeight}}
async function processSpeech(text){if(!text.trim()||busy)return;busy=true;logTurn('Driver',text);const info=document.getElementById('rv-micstatus');if(info)info.textContent='Gemini analysing…';try{const result=await api('/api/v7/turn',{driver:state.candidate,language:state.candidate==='Suresh'?'te':'hi',transcript:text,history:[
  {
    role:"system",
    text:"DEMO INCIDENT FACTS: Breakdown driver Raju. " +
      "Location: " + (state.incident?.location || "Gajuwaka, Visakhapatnam") +
      ". Total pending parcels: " + (state.incident?.parcels ?? 6) +
      ". Current helper: " + state.candidate +
      ". Never invent the helper's ETA or accepted parcel count. " +
      "Ask only for missing details. Once ETA, parcel count, " +
      "destination and explicit agreement are known, briefly " +
      "summarize them and ask whether the conversation can end."
  },
  ...turns.slice(0,-1)
]});facts=result;logTurn('AI',result.reply);await resqSpeak(result.reply);await resqSleep(2000);const f=document.getElementById('rv-transcript');if(f)f.value=turns.filter(t=>t.role==='Driver').map(t=>t.text).join('\n');const eta=document.getElementById('rv-eta'),cap=document.getElementById('rv-capacity'),dest=document.getElementById('rv-dest'),acc=document.getElementById('rv-accepted');if(eta)eta.value=result.eta_minutes??'';if(cap)cap.value=result.parcel_capacity??'';if(dest)dest.value=result.destination??'';if(acc)acc.value=result.accepted===true?'yes':result.accepted===false?'no':'unknown';if(info)info.textContent=result.complete?'Conversation complete · End & generate report':'Ready · tap mic for next answer';}catch(e){if(info)info.textContent='AI error: '+e.message+' · You can still type and save a report';}finally{busy=false}}
function startMic(){
  const info = document.getElementById("rv-micstatus");
  const button = document.getElementById("rv-mic");

  if (!SpeechAPI) {
    if (info) info.textContent =
      "Microphone recognition unavailable. Type your answer.";
    return;
  }

  if (busy) return;

  if (listening && recognizer) {
    recognizer.stop();
    if (info) info.textContent = "Processing your answer…";
    return;
  }

  recognizer = new SpeechAPI();
  recognizer.lang = state.candidate === "Suresh" ? "te-IN" : "hi-IN";
  recognizer.interimResults = true;
  recognizer.continuous = true;

  let finalText = "";
  let interimText = "";
  let submitted = false;

  recognizer.onresult = event => {
    finalText = "";
    interimText = "";

    for (let i = 0; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        finalText += result[0].transcript + " ";
      } else {
        interimText += result[0].transcript + " ";
      }
    }

    const textarea = document.getElementById("rv-transcript");
    if (textarea) textarea.value =
      (finalText + interimText).trim();
  };

  recognizer.onerror = event => {
    if (info) info.textContent =
      "Mic error: " + event.error;
  };

  recognizer.onend = () => {
    listening = false;
    if (button) button.textContent = "🎙 Start / Stop Mic";

    if (submitted) return;
    submitted = true;

    const textarea = document.getElementById("rv-transcript");
    const answer = (finalText || interimText ||
      textarea?.value || "").trim();

    if (answer) {
      processSpeech(answer);
    } else if (info) {
      info.textContent = "No speech detected. Try again.";
    }
  };

  try {
    window.speechSynthesis?.cancel();
    recognizer.start();
    listening = true;

    if (button) button.textContent = "■ Stop Mic";
    if (info) info.textContent =
      "Listening… press Stop Mic when finished.";
  } catch (error) {
    if (info) info.textContent = error.message;
  }
}

async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw Error(typeof j.detail==='string'?j.detail:'Request failed');return j}
const btn=(label,act,primary=false)=>`<button data-resq="${act}" class="${primary?'primary':''}">${label}</button>`;
function render(){const s=state.stage;panel.innerHTML=`<div class="row"><b style="font-size:14px">Rescue workflow</b><span style="font-size:11px;color:#64748b">${E(s.replaceAll('_',' ').toUpperCase())} · Local demo</span><span style="flex:1"></span>${btn('Reset','reset')}</div><div class="row" style="margin-top:8px">${s==='new'?'<span class="hint">Start on Raju’s phone →</span>':s==='reported'?btn('Find nearby drivers','shortlist',true):s==='shortlisted'?btn('Contact Amit · Haryanvi/Hindi','call:Amit',true)+btn('Contact Suresh · Telugu','call:Suresh'):s==='demo_call'?'<span class="hint">Complete the conversation on the phone →</span>':btn('Call Amit · Haryanvi/Hindi','call:Amit',true)+btn('Call Suresh · Telugu','call:Suresh')+btn('Download report','download')}</div><div class="hint" id="resq-error">Real calls disabled until verified Gnani outbound setup.</div>`;
let content='';
if(s==='new')content=`<div class="dark"><div class="tiny" style="color:#aab8cb">RAJU · DRIVER APP</div><h3>Report breakdown</h3><div>🚚</div></div><div class="content"><label>Driver</label><input id="rv-name" value="Raju"><label>Breakdown location</label><input id="rv-location" value="Gajuwaka, Visakhapatnam"><label>Issue</label><select id="rv-issue"><option>Bike breakdown</option><option>Engine failure</option><option>Flat tyre</option></select><label>Pending parcels</label><input id="rv-parcels" type="number" min="1" max="100" value="6"><label>Language</label><select id="rv-lang"><option value="hi">Hindi + English</option><option value="en">English</option></select><div style="margin-top:12px">${btn('Send emergency alert','incident',true)}</div></div>`;
else if(s==='reported')content=`<div class="dark"><h3>Help is on the way</h3>🚨</div><div class="content"><div class="stat"><b>${E(state.incident.driver_name)}</b> · ${E(state.incident.issue)}<div>${E(state.incident.location)}</div><b>${E(state.incident.parcels)} parcels at risk</b></div><p class="tiny">AI will shortlist nearby drivers. Demo locations are illustrative.</p>${btn('Find rescue drivers','shortlist',true)}</div>`;
else if(s==='shortlisted')content=`<div class="dark"><h3>2 drivers found</h3><div class="tiny" style="color:#aab8cb">Illustrative ranking</div></div><div class="content"><div class="stat"><b>Suresh</b> · Telugu / English<br>2.1 km · 8 parcel capacity</div><div class="stat"><b>Amit</b> · Hindi / English<br>3.4 km · 10 parcel capacity</div>${btn('Call Amit (demo)','call:Amit',true)} ${btn('Call Suresh (demo)','call:Suresh')}</div>`;
else if(s==='demo_call'){const name=state.candidate;content=`<div class="dark"><div style="font-size:10px;color:#34d399">● AI VOICE · GNANI IF CONFIGURED</div><h3>${E(name)}</h3><div style="font-size:12px;color:#fca5a5">${name==='Suresh'?'Telugu + English':'Hindi + English'}</div><div id="rv-call-clock" style="font-size:16px;font-weight:700">00:00</div><div class="wave">${Array.from({length:24},(_,i)=>`<i style="height:${9+(i*13%35)}px"></i>`).join('')}</div><div style="font-size:10px;color:#94a3b8">Prisma → Gemini → Timbre</div></div><div class="content"><div style="margin:8px 0">
<label>AI voice</label>
<select id="rv-voice-gender" onchange="window.resqVoiceGender=this.value">
<option value="female">Female voice</option>
<option value="male">Male voice</option>
</select>
</div><div id="rv-dialog"  style="max-height:135px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px;padding:5px"></div><div style="display:flex;gap:5px;margin:8px 0">${btn('☎ Place Call','intro',true)}<button id="rv-mic" data-resq="mic">🎙 Start / Stop Mic</button></div><div id="rv-micstatus" class="tiny">Place Call → ringing → listen → record → Stop Mic.</div><label>Your reply (mic transcript or type)</label><textarea id="rv-transcript" placeholder="Speak or type your answer here"></textarea><div style="display:flex;gap:6px;margin:6px 0">${btn('Send reply to AI','reply',true)}${btn('Extract facts','extract')}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:7px"><div><label>ETA (min)</label><input id="rv-eta" type="number" min="1" max="240"></div><div><label>Parcels</label><input id="rv-capacity" type="number" min="0" max="100"></div></div><label>Delivery destination</label><input id="rv-dest"><label>Acceptance</label><select id="rv-accepted"><option value="unknown">Unverified</option><option value="yes">Said yes (unverified)</option><option value="no">Said no</option></select><div style="margin-top:9px">${btn('End conversation & report','report',true)}</div><p class="tiny">Simulated call; Gnani processing when configured. Review extracted facts.</p></div>`;}

else{const r=state.report||{};const tel=state.candidate==='Suresh';content=`<div class="dark"><div style="font-size:10px;color:#34d399">AI RESCUE REPORT · REVIEW REQUIRED</div><h3>${E(r.driver)}</h3><div style="font-size:12px">${tel?'తెలుగు + English':'हिन्दी + English'}</div></div><div class="content"><div class="stat"><b>${tel?'చేరుకునే సమయం / Arrival':'पहुंचने का समय / Arrival'}</b><br>${E(r.eta_minutes)} min</div><div class="stat"><b>${tel?'పార్సిళ్లు / Parcels':'पार्सल / Parcels'}</b><br>${E(r.parcels_accepted)} / ${E(r.parcels_offered)}</div><div class="stat"><b>${tel?'గమ్యం / Destination':'गंतव्य / Destination'}</b><br>${E(r.destination)}</div><div class="stat"><b>Consent</b>: ${r.accepted===true?'Reported yes, not verified':r.accepted===false?'Declined':'Unverified'}<br><b>Dispatcher:</b> Pending</div>${btn('Download JSON report','download',true)}<p class="tiny">Based on entered transcript. Not verified phone audio.</p></div>`}
phone.innerHTML=content;
  if (state.report) saveDriverReport(state.report);

  let history = document.getElementById("resq-report-history");
  if (!history) {
    history = document.createElement("div");
    history.id = "resq-report-history";
    history.style.cssText =
      "margin:12px 0;padding:10px;background:white;max-width:100%;min-width:0;box-sizing:border-box;overflow-wrap:anywhere;" +
      "border:1px solid #e2e8f0;border-radius:12px";
    panel.appendChild(history);
  }
  renderDriverReports();

for(const b of [...document.querySelectorAll('[data-resq]')])b.addEventListener('click',()=>action(b.dataset.resq));
}
async function action(a){try{if(a==='incident')state=await api('/api/v5/incident',{driver_name:document.getElementById('rv-name').value,location:document.getElementById('rv-location').value,issue:document.getElementById('rv-issue').value,parcels:Number(document.getElementById('rv-parcels').value),language:document.getElementById('rv-lang').value});else if(a==='shortlist')state=await api('/api/v5/shortlist',{});else if(a.startsWith('call:')){state=await api('/api/v5/call/'+a.split(':')[1],{});extracted=null;turns=[];facts={}}else if(a==='intro'){await resqPlaceCall();return}else if(a==='mic'){await resqMic();return}else if(a==='reply'){const t=document.getElementById('rv-transcript').value;await processSpeech(t);return}else if(a==='extract'){const text=document.getElementById('rv-transcript').value;const r=await api('/api/v6/extract',{transcript:text,language:state.candidate==='Suresh'?'te':'hi'});extracted=r;document.getElementById('rv-eta').value=r.eta_minutes??'';document.getElementById('rv-capacity').value=r.parcel_capacity??'';document.getElementById('rv-dest').value=r.destination??'';document.getElementById('rv-accepted').value=r.accepted===true?'yes':r.accepted===false?'no':'unknown';document.getElementById('resq-error').textContent='Gemini extracted fields from text; review before report.';return}else if(a==='report'){const val=id=>document.getElementById(id).value;state=await api('/api/v5/report',{driver:state.candidate,language:state.candidate==='Suresh'?'te':'hi',transcript:turns.filter(t=>t.role==='Driver').map(t=>t.text).join('\n')||val('rv-transcript'),eta_minutes:val('rv-eta')?Number(val('rv-eta')):null,parcel_capacity:val('rv-capacity')?Number(val('rv-capacity')):null,destination:val('rv-dest')||null,accepted:val('rv-accepted')==='unknown'?null:val('rv-accepted')==='yes'})}else if(a==='reset'){localStorage.removeItem(RESQ_REPORT_KEY);window.speechSynthesis?.cancel();turns=[];facts={};state=await api('/api/v5/reset',{})}else if(a==='download'){const blob=new Blob([JSON.stringify(state.report,null,2)],{type:'application/json'});const u=URL.createObjectURL(blob);const link=document.createElement('a');link.href=u;link.download='resq-rescue-report.json';link.click();setTimeout(()=>URL.revokeObjectURL(u),1000);return}render()}catch(err){const el=document.getElementById('resq-error');if(el)el.textContent='Error: '+err.message;else alert(err.message)}}
api('/api/v5/state').then(s=>{state=s;render()}).catch(e=>{panel.textContent='Backend unavailable: '+e.message});
})();
