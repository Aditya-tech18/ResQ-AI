/* Optional dashboard report widget. No changes to existing call/microphone controls. */
(() => {
  const root = document.getElementById('resq-live-report');
  if (!root) return;
  const esc = x => String(x ?? 'Awaiting data').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let callId = null;
  window.ResQLiveReport = { setCallId(id) { callId = String(id); refresh(); } };
  const fields = [
    ['Breakdown driver','breakdown_driver'],['Rescue driver','rescue_driver'],
    ['Raju location','breakdown_location'],['Nearby parcels','nearby_parcels'],
    ['Next route','next_route'],['Current location','current_location'],
    ['Pickup ETA','pickup_eta_minutes'],['Call status','call_status']
  ];
  async function refresh() {
    if (!callId) return;
    try {
      const res = await fetch('/api/v16/reports/' + encodeURIComponent(callId), {cache:'no-store'});
      if (!res.ok) return;
      const d = await res.json();
      root.innerHTML = '<div class="resq-report-heading"><strong>Live Rescue Call Report</strong><span>' + esc(d.rescue_driver) + '</span></div>' +
        '<div class="resq-report-grid">' + fields.map(([label,key]) =>
          '<div class="resq-report-cell"><small>' + esc(label) + '</small><strong>' +
          esc(key==='pickup_eta_minutes' && d[key]!=null ? d[key]+' min' : d[key]) + '</strong></div>').join('') + '</div>' +
        '<small>Call data · Unverified GPS shown as unavailable · Dispatcher approval separate</small>';
    } catch(e) { console.warn('Live report refresh failed',e); }
  }
  setInterval(refresh, 1200);
})();
