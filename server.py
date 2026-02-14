"""
server.py
---------
Flask Web Server providing real-time telemetry API and interactive
analytics web dashboard for PostureGuard Pro.
"""

from __future__ import annotations

import threading
import time
from flask import Flask, jsonify, render_template_string
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
  <title>PostureGuard Pro - Live Analytics</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
    body { background: #0f172a; color: #f8fafc; padding: 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
    .header h1 { font-size: 24px; font-weight: 700; color: #38bdf8; }
    .badge { padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 600; }
    .bg-good { background: #166534; color: #4ade80; }
    .bg-bad { background: #991b1b; color: #fca5a5; }
    
    .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
    .card { background: #1e293b; padding: 20px; border-radius: 12px; border: 1fr solid #334155; }
    .card-title { font-size: 13px; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase; }
    .card-value { font-size: 28px; font-weight: 700; }
    
    .charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .chart-container { background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }
    .chart-container h3 { font-size: 16px; margin-bottom: 16px; color: #e2e8f0; }
  </style>
</head>
<body>
  <div class="header">
    <h1>PostureGuard Pro Live Analytics</h1>
    <div id="statusBadge" class="badge bg-good">System Active</div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-title">Session Score</div>
      <div class="card-value" id="scoreVal">100</div>
    </div>
    <div class="card">
      <div class="card-title">CVA Angle</div>
      <div class="card-value" id="cvaVal">55.0°</div>
    </div>
    <div class="card">
      <div class="card-title">Blink Rate</div>
      <div class="card-value" id="bpmVal">16 bpm</div>
    </div>
    <div class="card">
      <div class="card-title">Break Timer</div>
      <div class="card-value" id="breakVal">20:00</div>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-container">
      <h3>CVA Posture Angle Trend (°)</h3>
      <canvas id="cvaChart"></canvas>
    </div>
    <div class="chart-container">
      <h3>Session Score History</h3>
      <canvas id="scoreChart"></canvas>
    </div>
  </div>

  <script>
    const cvaCtx = document.getElementById('cvaChart').getContext('2d');
    const scoreCtx = document.getElementById('scoreChart').getContext('2d');

    const cvaChart = new Chart(cvaCtx, {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'CVA Angle', data: [], borderColor: '#38bdf8', tension: 0.3 }] },
      options: { scales: { y: { min: 30, max: 75 } } }
    });

    const scoreChart = new Chart(scoreCtx, {
      type: 'line',
      data: { labels: [], datasets: [{ label: 'Session Score', data: [], borderColor: '#4ade80', tension: 0.3 }] },
      options: { scales: { y: { min: 0, max: 100 } } }
    });

    async function pollTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        const data = await res.json();
        
        document.getElementById('scoreVal').innerText = Math.round(data.session_score) + '/100';
        document.getElementById('cvaVal').innerText = (data.cva_smoothed || '--') + '°';
        document.getElementById('bpmVal').innerText = (data.blink_rate_bpm || 0) + ' bpm';

        const rem = data.break_time_remaining || 0;
        const mins = Math.floor(rem / 60);
        const secs = Math.floor(rem % 60);
        document.getElementById('breakVal').innerText = `${mins}:${secs < 10 ? '0' : ''}${secs}`;

        const badge = document.getElementById('statusBadge');
        if (data.is_slouching || data.ocular_fatigue) {
          badge.className = 'badge bg-bad';
          badge.innerText = 'Alert: ' + (data.slouch_reason || data.fatigue_reason || 'Bad Posture');
        } else {
          badge.className = 'badge bg-good';
          badge.innerText = 'Posture Good';
        }

        if (data.history) {
          const labels = data.history.map(h => h.time);
          cvaChart.data.labels = labels;
          cvaChart.data.datasets[0].data = data.history.map(h => h.cva);
          cvaChart.update();

          scoreChart.data.labels = labels;
          scoreChart.data.datasets[0].data = data.history.map(h => h.score);
          scoreChart.update();
        }
      } catch (e) {}
    }

    setInterval(pollTelemetry, 1000);
  </script>
</body>
</html>
"""

def start_server_thread():
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=config.WEB_SERVER_PORT, debug=False, use_reloader=False), daemon=True)
    t.start()
