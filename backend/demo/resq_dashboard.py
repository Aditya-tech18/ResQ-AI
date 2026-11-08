"""Standalone ResQ AI dispatcher demo.

Run:
    python demo/resq_dashboard.py

Open:
    http://127.0.0.1:8765

All call and location events are simulated.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8765

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ResQ AI — Emergency Operations</title>
<style>
:root {
  --bg: #08090c;
  --panel: #111318;
  --panel2: #181b21;
  --border: #292d35;
  --text: #f6f7f9;
  --muted: #9298a3;
  --red: #ff414c;
  --green: #43d69b;
  --amber: #ffbf69;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
header {
  padding: 22px 32px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo {
  font-size: 25px;
  font-weight: 850;
  letter-spacing: -1px;
}
.logo span { color: var(--red); }
.pill {
  padding: 8px 12px;
  border-radius: 30px;
  background: #25171a;
  color: #ff8991;
  font-size: 12px;
  font-weight: 750;
}
main { padding: 28px 32px; max-width: 1500px; margin: auto; }
h1 { margin: 0 0 8px; font-size: 30px; letter-spacing: -.8px; }
.subtitle { color: var(--muted); margin-bottom: 25px; }
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 22px;
}
.card {
  background: linear-gradient(145deg, #191b22, #101115);
  border: 1px solid var(--border);
  border-radius: 17px;
  padding: 22px;
}
.metric { color: var(--muted); font-size: 13px; }
.value { font-size: 33px; font-weight: 800; margin-top: 12px; }
.layout {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 20px;
}
h2 { margin: 0 0 16px; font-size: 19px; }
.tag {
  color: var(--red);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 1px;
}
.timeline { margin-top: 20px; }
.event {
  padding: 15px 0;
  border-bottom: 1px solid var(--border);
  color: #c8cbd1;
}
.event strong { color: white; }
.driver {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 17px;
  margin: 10px 0;
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.driver small { display: block; color: var(--muted); margin-top: 6px; }
button {
  border: none;
  background: var(--red);
  color: white;
  padding: 12px 16px;
  border-radius: 10px;
  font-weight: 750;
  cursor: pointer;
}
button:hover { filter: brightness(1.12); }
button:disabled { background: #444; cursor: not-allowed; }
.secondary { background: #343945; }
.success { color: var(--green); }
.warning { color: var(--amber); }
.map {
  position: relative;
  height: 260px;
  border-radius: 13px;
  background:
    linear-gradient(90deg, transparent 49%, #30343d 50%, transparent 51%),
    linear-gradient(0deg, transparent 49%, #30343d 50%, transparent 51%),
    repeating-linear-gradient(45deg, #151a20 0 20px, #191f26 20px 22px);
  overflow: hidden;
}
.pin {
  position: absolute;
  padding: 8px 11px;
  border-radius: 20px;
  background: #252b35;
  border: 1px solid #4a5260;
  font-size: 12px;
}
.pin.red { background: #74252d; border-color: var(--red); }
.footer {
  margin-top: 24px;
  font-size: 12px;
  color: var(--muted);
}
@media(max-width: 850px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .layout { grid-template-columns: 1fr; }
  header, main { padding: 18px; }
}
</style>
</head>
<body>
<header>
  <div class="logo">ResQ<span>AI</span> <small style="font-size:12px;color:#8e95a1">OPERATIONS</small></div>
  <div class="pill">● SIMULATION MODE — NO REAL CALLS</div>
</header>
<main>
  <h1>Emergency Response Command Center</h1>
  <div class="subtitle">Visakhapatnam · Last-mile delivery rescue · Interactive prototype</div>

  <section class="stats">
    <div class="card"><div class="metric">Active emergencies</div><div class="value" style="color:var(--red)">01</div></div>
    <div class="card"><div class="metric">Parcels at risk</div><div class="value">06</div></div>
    <div class="card"><div class="metric">Available drivers</div><div class="value">02</div></div>
    <div class="card"><div class="metric">Rescue status</div><div class="value" id="status" style="font-size:22px">Awaiting action</div></div>
  </section>

  <section class="layout">
    <div class="card">
      <div class="tag">CRITICAL INCIDENT · RESQ-001</div>
      <h2 style="margin-top:12px">Ravi's delivery van has broken down</h2>
      <p style="color:var(--muted);line-height:1.7">
        6 parcels are delayed near MVP Colony. ResQ AI has identified
        two replacement drivers using simulated availability,
        distance and parcel capacity.
      </p>

      <div class="map" aria-label="Illustrative schematic, not a live GPS map">
        <div class="pin red" style="left:43%;top:42%">🚨 Ravi · Breakdown</div>
        <div class="pin" style="left:12%;top:17%">🚚 Suresh</div>
        <div class="pin" style="left:65%;top:75%">🚚 Amit</div>
      </div>
      <p style="font-size:11px;color:var(--muted)">Illustrative positions only · Not live GPS</p>

      <div class="timeline" id="timeline">
        <div class="event"><strong>Incident created</strong> — Van breakdown reported.</div>
        <div class="event"><strong>AI ranking ready</strong> — Replacement candidates identified.</div>
      </div>
    </div>

    <div class="card">
      <h2>Replacement Driver Selection</h2>

      <div class="driver">
        <div><strong>1. Suresh</strong><small>Telugu · 2.1 km · Capacity 8 parcels</small></div>
        <button id="call1" onclick="simulateCall('Suresh')">Simulate Call</button>
      </div>

      <div class="driver">
        <div><strong>2. Amit</strong><small>Hindi · 3.4 km · Capacity 10 parcels</small></div>
        <button id="call2" onclick="simulateCall('Amit')">Simulate Call</button>
      </div>

      <div class="card" style="margin-top:22px;background:#0c0e12">
        <div class="metric">Driver consent</div>
        <p id="consent" class="warning">Not received</p>
        <button id="accept" class="secondary" onclick="simulateAcceptance()" disabled>
          Simulate Driver Acceptance
        </button>
      </div>

      <div style="margin-top:22px">
        <button id="approve" onclick="approveRescue()" disabled>
          Approve Rescue
        </button>
        <button id="handover" class="secondary" onclick="verifyHandover()" disabled>
          Simulate Handover
        </button>
      </div>
      <p class="footer">
        Demonstration only. This page does not initiate phone calls,
        validate actual driver identity or persist approvals to the backend.
      </p>
    </div>
  </section>
</main>

<script>
let selectedDriver = null;
let accepted = false;
let approved = false;

function addEvent(message) {
  const item = document.createElement("div");
  item.className = "event";
  item.textContent = new Date().toLocaleTimeString() + " — " + message;
  document.getElementById("timeline").appendChild(item);
}

function simulateCall(driver) {
  selectedDriver = driver;
  accepted = false;
  approved = false;
  document.getElementById("consent").textContent = "Awaiting simulated response from " + driver;
  document.getElementById("status").textContent = "Contacting";
  document.getElementById("accept").disabled = false;
  document.getElementById("approve").disabled = true;
  document.getElementById("handover").disabled = true;
  addEvent("Simulated call initiated for " + driver + " (no phone call placed)");
}

function simulateAcceptance() {
  if (!selectedDriver) return;
  accepted = true;
  document.getElementById("consent").textContent =
    selectedDriver + " accepted (simulated)";
  document.getElementById("status").textContent = "Consent simulated";
  document.getElementById("approve").disabled = false;
  addEvent("Simulated driver acceptance recorded for " + selectedDriver);
}

function approveRescue() {
  if (!accepted || !selectedDriver) return;
  approved = true;
  document.getElementById("status").textContent = "Approved (demo)";
  document.getElementById("handover").disabled = false;
  document.getElementById("approve").disabled = true;
  addEvent("Dispatcher approved simulated rescue assignment");
}

function verifyHandover() {
  if (!approved) return;
  document.getElementById("status").textContent = "Completed (demo)";
  document.getElementById("handover").disabled = true;
  addEvent("Simulated parcel handover completed");
}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        content = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    print(f"ResQ AI demo: http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
