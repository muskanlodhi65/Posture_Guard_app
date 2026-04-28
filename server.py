"""
server.py
---------
Flask Web Server providing real-time telemetry API, voice personality switcher API,
user name personalization API, and an interactive bilingual analytics dashboard for PostureGuard Pro.
"""

from __future__ import annotations

import threading
import time
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS

import config

app = Flask(__name__)
CORS(app)

# Global shared metrics store
latest_telemetry = {
    "timestamp": time.time(),
    "user_name": config.USER_NAME,
    "cva_smoothed": 55.0,
    "ear_smoothed": 0.25,
    "blink_rate_bpm": 16.0,
    "blink_count_total": 0,
    "session_score": 100.0,
    "is_slouching": False,
    "sustained_slouch": False,
    "slouch_reason": "",
    "ocular_fatigue": False,
    "fatigue_reason": "",
    "is_too_close": False,
    "is_low_light": False,
    "ambient_luminance": 100.0,
    "voice_personality": config.VOICE_PERSONALITY_MODE,
    "break_time_remaining": config.BREAK_REMINDER_INTERVAL_SEC,
    "history": []
}

telemetry_history = []
MAX_HISTORY = 600  # 10 minutes history at 1s intervals

# Voice dispatcher reference
_dispatcher_ref = None

def register_dispatcher(dispatcher):
    global _dispatcher_ref
    _dispatcher_ref = dispatcher

def update_telemetry(metrics, voice_personality: str):
    global latest_telemetry, telemetry_history
    now = time.time()
    user_name = _dispatcher_ref.user_name if _dispatcher_ref else config.USER_NAME

    data_point = {
        "time": time.strftime("%H:%M:%S", time.localtime(now)),
        "timestamp": now,
        "cva": round(metrics.cva_smoothed, 1) if metrics.cva_smoothed is not None else None,
        "ear": round(metrics.ear_smoothed, 3) if metrics.ear_smoothed is not None else None,
        "bpm": round(metrics.blink_rate_bpm, 1),
        "score": round(metrics.session_score, 1),
        "slouching": metrics.sustained_slouch or metrics.is_slouching,
        "fatigue": metrics.ocular_fatigue,
        "too_close": metrics.is_too_close,
        "low_light": metrics.is_low_light,
        "blinks": metrics.blink_count_total,
    }

    latest_telemetry.update({
        "timestamp": now,
        "user_name": user_name,
        "cva_smoothed": data_point["cva"],
        "ear_smoothed": data_point["ear"],
        "blink_rate_bpm": data_point["bpm"],
        "blink_count_total": metrics.blink_count_total,
        "session_score": data_point["score"],
        "is_slouching": metrics.is_slouching,
        "sustained_slouch": metrics.sustained_slouch,
        "slouch_reason": metrics.slouch_reason,
        "ocular_fatigue": metrics.ocular_fatigue,
        "fatigue_reason": metrics.fatigue_reason,
        "is_too_close": metrics.is_too_close,
        "is_low_light": metrics.is_low_light,
        "ambient_luminance": round(metrics.ambient_luminance, 1),
        "voice_personality": voice_personality,
        "break_time_remaining": round(metrics.break_time_remaining, 0),
    })

    if not telemetry_history or (now - telemetry_history[-1]["timestamp"]) >= 1.0:
        telemetry_history.append(data_point)
        if len(telemetry_history) > MAX_HISTORY:
            telemetry_history.pop(0)

@app.route("/api/telemetry")
def get_telemetry():
    res = dict(latest_telemetry)
    res["history"] = telemetry_history[-60:]
    return jsonify(res)

VALID_PERSONALITIES = ["angry_hindi", "angry_english", "hindi_scolding", "scolding", "hindi_gentle", "gentle", "cyberpunk"]

@app.route("/api/set_voice", methods=["POST"])
def set_voice():
    data = request.get_json(force=True)
    personality = data.get("personality", "")
    if personality not in VALID_PERSONALITIES:
        return jsonify({"error": "Invalid personality"}), 400
    if _dispatcher_ref is not None:
        _dispatcher_ref.set_personality(personality)
        latest_telemetry["voice_personality"] = personality
        return jsonify({"success": True, "personality": personality})
    return jsonify({"error": "Dispatcher not ready"}), 503

@app.route("/api/set_name", methods=["POST"])
def set_name():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name cannot be empty"}), 400
    if _dispatcher_ref is not None:
        _dispatcher_ref.set_user_name(name)
        latest_telemetry["user_name"] = name
        return jsonify({"success": True, "name": name})
    return jsonify({"error": "Dispatcher not ready"}), 503

@app.route("/")
def index():
    return render_template_string(HTML_DASHBOARD)

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PostureGuard Pro — Personalized Ergonomic Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(30, 41, 59, 0.7);
      --accent-blue: #38bdf8;
      --accent-purple: #a855f7;
      --good: #22c55e;
      --warn: #eab308;
      --bad: #ef4444;
      --text: #f8fafc;
      --subtext: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 24px; min-height: 100vh; }

    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; background: rgba(15, 23, 42, 0.7); padding: 18px 22px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.07); backdrop-filter: blur(12px); flex-wrap: wrap; gap: 12px; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo-dot { width: 13px; height: 13px; background: var(--accent-blue); border-radius: 50%; box-shadow: 0 0 14px var(--accent-blue); animation: glowPulse 2s infinite; }
    @keyframes glowPulse { 0%,100%{box-shadow:0 0 8px var(--accent-blue);} 50%{box-shadow:0 0 22px var(--accent-blue);} }
    .header h1 { font-size: 22px; font-weight: 700; background: linear-gradient(135deg, #38bdf8, #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .status-badge { padding: 8px 16px; border-radius: 30px; font-size: 13px; font-weight: 600; transition: all 0.3s; display: inline-flex; align-items: center; gap: 7px; }
    .badge-good { background: rgba(34,197,94,0.14); color: var(--good); border: 1px solid rgba(34,197,94,0.3); }
    .badge-bad  { background: rgba(239,68,68,0.14); color: var(--bad); border: 1px solid rgba(239,68,68,0.3); animation: alertPulse 1.4s infinite; }
    @keyframes alertPulse { 0%,100%{transform:scale(1);} 50%{transform:scale(1.04);} }

    /* Personalization Bar */
    .user-panel { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px; padding: 18px 22px; margin-bottom: 22px; backdrop-filter: blur(10px); display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
    .user-panel label { font-size: 14px; font-weight: 600; color: var(--accent-blue); display: flex; align-items: center; gap: 8px; }
    .name-input { background: rgba(15, 23, 42, 0.8); border: 1.5px solid rgba(56, 189, 248, 0.3); color: #fff; padding: 8px 14px; border-radius: 10px; font-size: 14px; outline: none; transition: all 0.2s; }
    .name-input:focus { border-color: var(--accent-blue); box-shadow: 0 0 10px rgba(56, 189, 248, 0.3); }
    .save-btn { background: var(--accent-blue); color: #000; font-weight: 700; border: none; padding: 8px 18px; border-radius: 10px; cursor: pointer; transition: all 0.2s; }
    .save-btn:hover { background: #7dd3fc; box-shadow: 0 0 12px rgba(56, 189, 248, 0.4); }

    /* Metric Cards */
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 22px; }
    .card { background: var(--card-bg); padding: 20px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.05); backdrop-filter: blur(10px); transition: all 0.22s ease; position: relative; overflow: hidden; }
    .card:hover { transform: translateY(-3px); border-color: rgba(56,189,248,0.35); box-shadow: 0 10px 22px -8px rgba(0,0,0,0.5); }
    .card::before { content:''; position:absolute; top:0; left:0; width:4px; height:100%; background:var(--accent-blue); border-radius:2px; }
    .card.card-warn::before { background:var(--warn); }
    .card.card-bad::before { background:var(--bad); }
    .card-title { font-size: 12px; color: var(--subtext); text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; margin-bottom: 8px; }
    .card-value { font-size: 30px; font-weight: 700; }
    .card-subtext { font-size: 11px; color: var(--subtext); margin-top: 5px; }

    /* Voice Selector Panel */
    .voice-panel { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px; padding: 20px 22px; margin-bottom: 22px; backdrop-filter: blur(10px); }
    .voice-panel h3 { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
    .voice-btns { display: flex; flex-wrap: wrap; gap: 10px; }
    .voice-btn { padding: 9px 18px; border-radius: 10px; border: 1.5px solid rgba(168,85,247,0.3); background: rgba(168,85,247,0.08); color: #c084fc; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.18s; }
    .voice-btn:hover { background: rgba(168,85,247,0.22); border-color: #a855f7; }
    .voice-btn.active { background: #a855f7; color: #fff; border-color: #a855f7; box-shadow: 0 0 14px rgba(168,85,247,0.45); }
    
    /* Gussa Mode Special Style */
    .voice-btn.btn-angry { border-color: rgba(239,68,68,0.5); background: rgba(239,68,68,0.12); color: #ef4444; }
    .voice-btn.btn-angry:hover { background: rgba(239,68,68,0.3); border-color: #ef4444; }
    .voice-btn.btn-angry.active { background: #ef4444; color: #fff; border-color: #ef4444; box-shadow: 0 0 16px rgba(239,68,68,0.6); animation: angryPulse 1.2s infinite; }
    @keyframes angryPulse { 0%,100%{transform:scale(1);} 50%{transform:scale(1.05);} }

    .voice-label { display: flex; flex-direction: column; line-height: 1.3; }
    .voice-label .lang-tag { font-size: 10px; opacity: 0.7; font-weight: 400; text-transform: uppercase; letter-spacing: 0.5px; }

    /* Charts Grid */
    .charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
    .chart-box { background: var(--card-bg); padding: 22px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.05); backdrop-filter: blur(10px); }
    .chart-box h3 { font-size: 15px; font-weight: 600; margin-bottom: 16px; color: var(--text); }

    .info-row { display: flex; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
    .info-chip { background: rgba(30,41,59,0.6); border: 1px solid rgba(255,255,255,0.07); border-radius: 10px; padding: 8px 16px; font-size: 13px; display: flex; align-items: center; gap: 8px; }
    .info-chip .label { color: var(--subtext); }
    .info-chip .val { font-weight: 600; color: var(--text); }

    @media(max-width:860px) { .charts-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div class="brand">
      <div class="logo-dot"></div>
      <h1>PostureGuard Pro — Personalized Dashboard</h1>
    </div>
    <div id="statusBadge" class="status-badge badge-good">● Ergonomics Optimal</div>
  </div>

  <!-- Personalized User Name Input -->
  <div class="user-panel">
    <label for="userNameInput">👤 Personalized Voice Name:</label>
    <input type="text" id="userNameInput" class="name-input" placeholder="Enter your name (e.g. Muskan)" value="Muskan">
    <button class="save-btn" onclick="saveUserName()">Save Name</button>
    <span id="nameStatus" style="font-size:12px; color:var(--good); display:none;">✓ Name updated for voice alerts!</span>
  </div>

  <!-- Metric Cards -->
  <div class="grid">
    <div class="card" id="scoreCard">
      <div class="card-title">Session Score</div>
      <div class="card-value" id="scoreVal">100</div>
      <div class="card-subtext" id="scoreSub">Optimal Posture</div>
    </div>
    <div class="card" id="cvaCard">
      <div class="card-title">CVA Angle</div>
      <div class="card-value" id="cvaVal">--°</div>
      <div class="card-subtext">Craniovertebral Tilt</div>
    </div>
    <div class="card" id="blinkCard">
      <div class="card-title">Blink Rate</div>
      <div class="card-value" id="bpmVal">-- bpm</div>
      <div class="card-subtext" id="blinkSub">Total Blinks: 0</div>
    </div>
    <div class="card" id="breakCard">
      <div class="card-title">20-20-20 Break</div>
      <div class="card-value" id="breakVal">20:00</div>
      <div class="card-subtext">Next Eye Relief Break</div>
    </div>
  </div>

  <!-- Info Row -->
  <div class="info-row">
    <div class="info-chip"><span class="label">💡 Room Light:</span><span class="val" id="lightVal">Good</span></div>
    <div class="info-chip"><span class="label">📏 Distance:</span><span class="val" id="distVal">Normal</span></div>
    <div class="info-chip"><span class="label">🎙️ Active Mode:</span><span class="val" id="activeModeChip" style="color:#ef4444">🔥 Gussa Hindi Mode</span></div>
  </div>

  <!-- Voice / Language Selector including Gussa Mode -->
  <div class="voice-panel">
    <h3>🎙️ Alert Voice Language &amp; Personality Selector</h3>
    <div class="voice-btns">
      <button class="voice-btn btn-angry active" id="btn-angry_hindi" onclick="setVoice('angry_hindi')">
        <div class="voice-label"><span>😡 🔥 Gussa Hindi Mode</span><span class="lang-tag">Hindi · Aggressive Scolding</span></div>
      </button>
      <button class="voice-btn btn-angry" id="btn-angry_english" onclick="setVoice('angry_english')">
        <div class="voice-label"><span>😡 🔥 Angry English Mode</span><span class="lang-tag">English · Aggressive Scolding</span></div>
      </button>
      <button class="voice-btn" id="btn-hindi_scolding" onclick="setVoice('hindi_scolding')">
        <div class="voice-label"><span>🔊 कड़क हिंदी</span><span class="lang-tag">Hindi · Firm Scolding</span></div>
      </button>
      <button class="voice-btn" id="btn-scolding" onclick="setVoice('scolding')">
        <div class="voice-label"><span>🔊 Strict English</span><span class="lang-tag">English · Firm Scolding</span></div>
      </button>
      <button class="voice-btn" id="btn-hindi_gentle" onclick="setVoice('hindi_gentle')">
        <div class="voice-label"><span>🌸 सौम्य हिंदी</span><span class="lang-tag">Hindi · Gentle</span></div>
      </button>
      <button class="voice-btn" id="btn-gentle" onclick="setVoice('gentle')">
        <div class="voice-label"><span>🌸 Soft English</span><span class="lang-tag">English · Gentle</span></div>
      </button>
      <button class="voice-btn" id="btn-cyberpunk" onclick="setVoice('cyberpunk')">
        <div class="voice-label"><span>🤖 Cyberpunk AI</span><span class="lang-tag">English · Robotic</span></div>
      </button>
    </div>
  </div>

  <!-- Charts -->
  <div class="charts-grid">
    <div class="chart-box">
      <h3>📐 CVA Posture Angle Trend (°)</h3>
      <canvas id="cvaChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>📊 Session Score + Blink Count</h3>
      <canvas id="scoreChart"></canvas>
    </div>
  </div>

  <script>
    const cvaCtx = document.getElementById('cvaChart').getContext('2d');
    const scoreCtx = document.getElementById('scoreChart').getContext('2d');

    const cvaChart = new Chart(cvaCtx, {
      type: 'line',
      data: { labels: [], datasets: [{
        label: 'CVA Angle (°)', data: [],
        borderColor: '#38bdf8', backgroundColor: 'rgba(56,189,248,0.08)',
        fill: true, tension: 0.4, pointRadius: 2
      }]},
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#94a3b8' }}},
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748b', maxTicksLimit: 8 }},
          y: { min: 30, max: 75, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#94a3b8' }}
        }
      }
    });

    const scoreChart = new Chart(scoreCtx, {
      type: 'line',
      data: { labels: [], datasets: [
        { label: 'Session Score', data: [], borderColor: '#4ade80', backgroundColor: 'rgba(74,222,128,0.08)', fill: true, tension: 0.4, pointRadius: 2, yAxisID: 'y' },
        { label: 'Blinks', data: [], borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.08)', fill: false, tension: 0.4, pointRadius: 2, yAxisID: 'y1' }
      ]},
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#94a3b8' }}},
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748b', maxTicksLimit: 8 }},
          y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#94a3b8' }, position: 'left' },
          y1: { min: 0, grid: { drawOnChartArea: false }, ticks: { color: '#f59e0b' }, position: 'right' }
        }
      }
    });

    const VOICE_LABELS = {
      'angry_hindi': '😡 🔥 Gussa Hindi Mode',
      'angry_english': '😡 🔥 Angry English Mode',
      'hindi_scolding': '🔊 कड़क हिंदी (Hindi Scolding)',
      'scolding': '🔊 Strict English',
      'hindi_gentle': '🌸 सौम्य हिंदी (Hindi Gentle)',
      'gentle': '🌸 Soft English',
      'cyberpunk': '🤖 Cyberpunk AI'
    };

    let currentPersonality = 'angry_hindi';

    async function saveUserName() {
      const name = document.getElementById('userNameInput').value.trim();
      if (!name) return;
      try {
        const res = await fetch('/api/set_name', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ name: name })
        });
        const d = await res.json();
        if (d.success) {
          const status = document.getElementById('nameStatus');
          status.style.display = 'inline';
          setTimeout(() => status.style.display = 'none', 3000);
        }
      } catch(e) { console.error(e); }
    }

    async function setVoice(p) {
      try {
        const res = await fetch('/api/set_voice', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ personality: p })
        });
        const d = await res.json();
        if (d.success) {
          currentPersonality = p;
          document.querySelectorAll('.voice-btn').forEach(b => b.classList.remove('active'));
          document.getElementById('btn-' + p).classList.add('active');
          document.getElementById('activeModeChip').innerText = VOICE_LABELS[p] || p;
        }
      } catch(e) { console.error(e); }
    }

    async function pollTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        const data = await res.json();

        if (data.user_name && document.activeElement !== document.getElementById('userNameInput')) {
          document.getElementById('userNameInput').value = data.user_name;
        }

        // Score card
        const score = Math.round(data.session_score);
        document.getElementById('scoreVal').innerText = score + '/100';
        document.getElementById('scoreSub').innerText = score >= 80 ? '✅ Optimal' : score >= 50 ? '⚠️ Fair' : '❌ Poor';

        // CVA card
        document.getElementById('cvaVal').innerText = (data.cva_smoothed != null ? data.cva_smoothed : '--') + '°';

        // Blink card
        const bpm = data.blink_rate_bpm != null ? data.blink_rate_bpm.toFixed(1) : '--';
        document.getElementById('bpmVal').innerText = bpm + ' bpm';
        document.getElementById('blinkSub').innerText = 'Total Blinks: ' + (data.blink_count_total || 0);

        // Break timer
        const rem = data.break_time_remaining || 0;
        const mins = Math.floor(rem / 60);
        const secs = Math.floor(rem % 60);
        document.getElementById('breakVal').innerText = `${mins}:${secs < 10 ? '0' : ''}${secs}`;

        // Lighting & Distance
        document.getElementById('lightVal').innerText = data.is_low_light ? '⚠️ Dim Room' : '✅ Good';
        document.getElementById('distVal').innerText = data.is_too_close ? '⚠️ Too Close!' : '✅ Normal';

        // Status badge
        const badge = document.getElementById('statusBadge');
        if (data.is_slouching || data.ocular_fatigue || data.is_too_close) {
          badge.className = 'status-badge badge-bad';
          const msg = data.slouch_reason || data.fatigue_reason || (data.is_too_close ? 'Too Close to Screen' : 'Bad Posture');
          badge.innerText = '⚠️ ' + msg;
        } else {
          badge.className = 'status-badge badge-good';
          badge.innerText = '● Ergonomics Optimal';
        }

        // Charts
        if (data.history && data.history.length) {
          const labels = data.history.map(h => h.time);
          cvaChart.data.labels = labels;
          cvaChart.data.datasets[0].data = data.history.map(h => h.cva);
          cvaChart.update('none');

          scoreChart.data.labels = labels;
          scoreChart.data.datasets[0].data = data.history.map(h => h.score);
          scoreChart.data.datasets[1].data = data.history.map(h => h.blinks || 0);
          scoreChart.update('none');
        }
      } catch(e) {}
    }

    setInterval(pollTelemetry, 1000);
    pollTelemetry();
  </script>
</body>
</html>
"""

def start_server_thread():
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=config.WEB_SERVER_PORT, debug=False, use_reloader=False), daemon=True)
    t.start()
