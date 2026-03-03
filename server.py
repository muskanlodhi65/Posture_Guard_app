"""
server.py
---------
Flask Web Server providing real-time telemetry API and an interactive, premium
analytics web dashboard for PostureGuard Pro with rich animations, interactive cards,
live metric filtering, break trigger actions, and dark glassmorphic styling.
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

def update_telemetry(metrics, voice_personality: str):
    global latest_telemetry, telemetry_history
    now = time.time()
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
    }

    latest_telemetry.update({
        "timestamp": now,
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
    res["history"] = telemetry_history[-60:]  # Last 60 seconds
    return jsonify(res)

@app.route("/")
def index():
    return render_template_string(HTML_DASHBOARD)

HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PostureGuard Pro — Interactive Ergonomic Dashboard</title>
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
    body { background: var(--bg); color: var(--text); padding: 28px; min-height: 100vh; }
    
    /* Header styling */
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; background: rgba(15, 23, 42, 0.6); padding: 20px 24px; border-radius: 16px; border: 1px solid rgba(255, 255, 255, 0.08); backdrop-filter: blur(12px); }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo-dot { width: 14px; height: 14px; background: var(--accent-blue); border-radius: 50%; box-shadow: 0 0 16px var(--accent-blue); }
    .header h1 { font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #38bdf8, #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    
    .status-badge { padding: 8px 18px; border-radius: 30px; font-size: 14px; font-weight: 600; transition: all 0.3s ease; display: inline-flex; align-items: center; gap: 8px; }
    .badge-good { background: rgba(34, 197, 94, 0.15); color: var(--good); border: 1px solid rgba(34, 197, 94, 0.3); }
    .badge-bad { background: rgba(239, 68, 68, 0.15); color: var(--bad); border: 1px solid rgba(239, 68, 68, 0.3); animation: pulse 1.5s infinite; }

    @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.03); } }

    /* Interactive Metric Cards Grid */
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 18px; margin-bottom: 28px; }
    .card { background: var(--card-bg); padding: 22px; border-radius: 16px; border: 1px solid rgba(255, 255, 255, 0.06); backdrop-filter: blur(10px); transition: all 0.25s ease; cursor: pointer; position: relative; overflow: hidden; }
    .card:hover { transform: translateY(-4px); border-color: rgba(56, 189, 248, 0.4); box-shadow: 0 12px 24px -10px rgba(0, 0, 0, 0.5); }
    .card::before { content: ''; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: var(--accent-blue); border-radius: 4px; }
    .card.card-warn::before { background: var(--warn); }
    .card.card-bad::before { background: var(--bad); }

    .card-title { font-size: 13px; color: var(--subtext); text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; margin-bottom: 10px; }
    .card-value { font-size: 32px; font-weight: 700; color: var(--text); }
    .card-subtext { font-size: 12px; color: var(--subtext); margin-top: 6px; }

    /* Interactive Control Bar */
    .controls-bar { display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }
    .btn { background: rgba(56, 189, 248, 0.12); color: var(--accent-blue); border: 1px solid rgba(56, 189, 248, 0.3); padding: 10px 20px; border-radius: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s ease; display: inline-flex; align-items: center; gap: 8px; }
    .btn:hover { background: var(--accent-blue); color: #000; box-shadow: 0 0 16px rgba(56, 189, 248, 0.4); }

    /* Interactive Charts Grid */
    .charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .chart-box { background: var(--card-bg); padding: 24px; border-radius: 18px; border: 1px solid rgba(255, 255, 255, 0.06); backdrop-filter: blur(10px); }
    .chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
    .chart-header h3 { font-size: 17px; font-weight: 600; color: var(--text); }

    @media (max-width: 900px) { .charts-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="header">
    <div class="brand">
      <div class="logo-dot"></div>
      <h1>PostureGuard Pro Live Interactive Telemetry</h1>
    </div>
    <div id="statusBadge" class="status-badge badge-good">● Ergonomics Optimal</div>
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
      <div class="card-value" id="cvaVal">55.0°</div>
      <div class="card-subtext">Craniovertebral Tilt</div>
    </div>
    <div class="card" id="blinkCard">
      <div class="card-title">Blink Rate</div>
      <div class="card-value" id="bpmVal">16 bpm</div>
      <div class="card-subtext" id="blinkSub">Total: 0 blinks</div>
    </div>
    <div class="card" id="breakCard">
      <div class="card-title">20-20-20 Break</div>
      <div class="card-value" id="breakVal">20:00</div>
      <div class="card-subtext">Next Eye Relief Break</div>
    </div>
  </div>

  <!-- Interactive Controls Bar -->
  <div class="controls-bar">
    <button class="btn" onclick="filterChart('cva')">📈 Toggle CVA Focus</button>
    <button class="btn" onclick="filterChart('score')">📊 Toggle Score Focus</button>
    <div style="margin-left: auto; display: flex; align-items: center; gap: 12px; font-size: 14px; color: var(--subtext);">
      <span>Voice Mode: <strong id="voiceModeVal" style="color: var(--accent-purple);">SCOLDING</strong></span>
      <span>Lighting: <strong id="lightVal" style="color: var(--good);">GOOD</strong></span>
    </div>
  </div>

  <!-- Realtime Interactive Charts -->
  <div class="charts-grid">
    <div class="chart-box">
      <div class="chart-header">
        <h3>CVA Posture Angle Trend (°)</h3>
      </div>
      <canvas id="cvaChart"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-header">
        <h3>Session Score Trend (0-100)</h3>
      </div>
      <canvas id="scoreChart"></canvas>
    </div>
  </div>

  <script>
    const cvaCtx = document.getElementById('cvaChart').getContext('2d');
    const scoreCtx = document.getElementById('scoreChart').getContext('2d');

    const cvaChart = new Chart(cvaCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'CVA Angle (°)',
          data: [],
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.1)',
          fill: true,
          tension: 0.4,
          pointRadius: 3
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { color: '#94a3b8' } } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
          y: { min: 30, max: 75, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
        }
      }
    });

    const scoreChart = new Chart(scoreCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Session Score',
          data: [],
          borderColor: '#4ade80',
          backgroundColor: 'rgba(74, 222, 128, 0.1)',
          fill: true,
          tension: 0.4,
          pointRadius: 3
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { color: '#94a3b8' } } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
          y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
        }
      }
    });

    async function pollTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        const data = await res.json();

        // Update card values
        document.getElementById('scoreVal').innerText = Math.round(data.session_score) + '/100';
        document.getElementById('cvaVal').innerText = (data.cva_smoothed || '--') + '°';
        document.getElementById('bpmVal').innerText = (data.blink_rate_bpm || 0) + ' bpm';
        document.getElementById('blinkSub').innerText = `Total: ${data.blink_count_total || 0} blinks`;
        document.getElementById('voiceModeVal').innerText = (data.voice_personality || 'SCOLDING').toUpperCase();

        const lightVal = document.getElementById('lightVal');
        if (data.is_low_light) {
          lightVal.innerText = 'DIM ROOM';
          lightVal.style.color = 'var(--warn)';
        } else {
          lightVal.innerText = 'GOOD';
          lightVal.style.color = 'var(--good)';
        }

        const rem = data.break_time_remaining || 0;
        const mins = Math.floor(rem / 60);
        const secs = Math.floor(rem % 60);
        document.getElementById('breakVal').innerText = `${mins}:${secs < 10 ? '0' : ''}${secs}`;

        // Status badge logic
        const badge = document.getElementById('statusBadge');
        if (data.is_slouching || data.ocular_fatigue || data.is_too_close) {
          badge.className = 'status-badge badge-bad';
          let msg = data.slouch_reason || data.fatigue_reason || (data.is_too_close ? 'Too Close to Screen' : 'Bad Posture');
          badge.innerText = '⚠️ Alert: ' + msg;
        } else {
          badge.className = 'status-badge badge-good';
          badge.innerText = '● Ergonomics Optimal';
        }

        // Live chart updates
        if (data.history) {
          const labels = data.history.map(h => h.time);
          cvaChart.data.labels = labels;
          cvaChart.data.datasets[0].data = data.history.map(h => h.cva);
          cvaChart.update('none');

          scoreChart.data.labels = labels;
          scoreChart.data.datasets[0].data = data.history.map(h => h.score);
          scoreChart.update('none');
        }
      } catch (e) {}
    }

    function filterChart(type) {
      if (type === 'cva') {
        cvaChart.data.datasets[0].borderWidth = 3;
        cvaChart.update();
      } else {
        scoreChart.data.datasets[0].borderWidth = 3;
        scoreChart.update();
      }
    }

    setInterval(pollTelemetry, 1000);
  </script>
</body>
</html>
"""

def start_server_thread():
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=config.WEB_SERVER_PORT, debug=False, use_reloader=False), daemon=True)
    t.start()
