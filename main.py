"""
main.py
-------
PostureGuard Pro entry point: runs webcam capture, evaluates posture & eye fatigue,
monitors ambient lighting, screen distance proximity, 20-20-20 break timer,
serves Flask Live Web Dashboard, and plays personality voice alerts.

Controls:
    q / ESC  -> quit
    c        -> recalibrate baseline
    s        -> toggle audio voice alerts on/off
    n        -> toggle desktop notifications on/off
    p        -> cycle voice personality (scolding -> gentle -> cyberpunk)
    b        -> reset 20-20-20 break timer
"""

from __future__ import annotations

import sys
import time
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:
    print("ERROR: OpenCV is required. Install it with `pip install opencv-python`.")
    sys.exit(1)

import config
from alerts import AlertDispatcher
from server import start_server_thread, update_telemetry
from tracker import FrameMetrics, PostureFatigueTracker


# =========================================================================
# UI HELPERS
# =========================================================================

def draw_translucent_panel(frame: np.ndarray, x: int, y: int, w: int, h: int,
                            color=config.COLOR_PANEL_BG, alpha: float = config.UI_PANEL_ALPHA) -> None:
    x2, y2 = x + w, y + h
    x2 = min(x2, frame.shape[1])
    y2 = min(y2, frame.shape[0])
    if x2 <= x or y2 <= y:
        return
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x2, y2), color, thickness=-1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)


def put_text(frame: np.ndarray, text: str, org, scale: float, color, thickness: int = config.FONT_THICKNESS,
             font=cv2.FONT_HERSHEY_SIMPLEX) -> None:
    cv2.putText(frame, text, org, font, scale, color, thickness, lineType=cv2.LINE_AA)


def draw_skeleton_overlay(frame: np.ndarray, metrics: FrameMetrics) -> None:
    if metrics.pose_landmarks_px:
        pts = metrics.pose_landmarks_px
        color = config.COLOR_BAD if metrics.is_slouching else config.COLOR_GOOD

        def draw_point(name, radius=5):
            if name in pts:
                p = (int(pts[name][0]), int(pts[name][1]))
                cv2.circle(frame, p, radius, color, -1, lineType=cv2.LINE_AA)
            return pts.get(name)

        ls = draw_point("left_shoulder")
        rs = draw_point("right_shoulder")
        le = draw_point("left_ear")
        re = draw_point("right_ear")

        def draw_line(p1, p2):
            if p1 is not None and p2 is not None:
                cv2.line(frame, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), color, 2, cv2.LINE_AA)

        draw_line(ls, rs)
        draw_line(ls, le)
        draw_line(rs, re)


def draw_calibration_ui(frame: np.ndarray, metrics: FrameMetrics) -> None:
    h, w = frame.shape[:2]
    draw_translucent_panel(frame, 0, 0, w, h, color=(20, 20, 20), alpha=0.35)

    msg = "CALIBRATING - Sit upright, face the camera naturally"
    (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, config.FONT_SCALE_TITLE, 2)
    put_text(frame, msg, ((w - tw) // 2, h // 2 - 40), config.FONT_SCALE_TITLE, config.COLOR_TEXT, 2)

    bar_w, bar_h = int(w * 0.5), 24
    bar_x, bar_y = (w - bar_w) // 2, h // 2
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), config.COLOR_TEXT, 2)
    fill_w = int(bar_w * metrics.calibration_progress)
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), config.COLOR_ACCENT, -1)

    pct_msg = f"{int(metrics.calibration_progress * 100)}%"
    put_text(frame, pct_msg, (bar_x + bar_w + 15, bar_y + bar_h - 5), config.FONT_SCALE_VALUE, config.COLOR_TEXT, 1)


def draw_dashboard(frame: np.ndarray, metrics: FrameMetrics, fps: float,
                    sound_on: bool, notif_on: bool, personality: str) -> None:
    h, w = frame.shape[:2]
    panel_w = 340
    panel_h = 310
    margin = 12
    draw_translucent_panel(frame, margin, margin, panel_w, panel_h)

    x = margin + 14
    y = margin + 26
    line_gap = 24

    put_text(frame, "PostureGuard Pro Telemetry", (x, y), config.FONT_SCALE_TITLE, config.COLOR_ACCENT, 2)
    y += line_gap + 2

    posture_color = config.COLOR_BAD if metrics.sustained_slouch else (
        config.COLOR_WARN if metrics.is_slouching else config.COLOR_GOOD
    )
    posture_label = "SLOUCHING" if metrics.sustained_slouch else ("Adjusting..." if metrics.is_slouching else "GOOD")
    cva_text = f"{metrics.cva_smoothed:.1f} deg" if metrics.cva_smoothed is not None else "N/A"
    put_text(frame, f"CVA: {cva_text} | Posture: {posture_label}", (x, y), config.FONT_SCALE_VALUE, posture_color); y += line_gap

    ear_text = f"{metrics.ear_smoothed:.3f}" if metrics.ear_smoothed is not None else "N/A"
    fatigue_color = config.COLOR_BAD if metrics.ocular_fatigue else config.COLOR_GOOD
    fatigue_label = "FATIGUE" if metrics.ocular_fatigue else "Alert"
    put_text(frame, f"EAR: {ear_text} | Ocular: {fatigue_label}", (x, y), config.FONT_SCALE_VALUE, fatigue_color); y += line_gap

    put_text(frame, f"Blink Rate: {metrics.blink_rate_bpm:.1f} bpm (Total: {metrics.blink_count_total})", (x, y), config.FONT_SCALE_VALUE, config.COLOR_TEXT); y += line_gap

    # Proximity & Lighting indicators
    prox_color = config.COLOR_BAD if metrics.is_too_close else config.COLOR_GOOD
    prox_text = "TOO CLOSE" if metrics.is_too_close else "Optimal Distance"
    light_color = config.COLOR_WARN if metrics.is_low_light else config.COLOR_GOOD
    light_text = "LOW LIGHT" if metrics.is_low_light else "Good Lighting"
    put_text(frame, f"Screen Dist: {prox_text}", (x, y), config.FONT_SCALE_VALUE, prox_color); y += line_gap
    put_text(frame, f"Room Light: {light_text} ({metrics.ambient_luminance:.0f})", (x, y), config.FONT_SCALE_VALUE, light_color); y += line_gap

    # 20-20-20 Break Timer
    rem_min = int(metrics.break_time_remaining // 60)
    rem_sec = int(metrics.break_time_remaining % 60)
    timer_color = config.COLOR_WARN if metrics.break_recommended else config.COLOR_TEXT
    put_text(frame, f"Next Break: {rem_min:02d}:{rem_sec:02d}", (x, y), config.FONT_SCALE_VALUE, timer_color); y += line_gap

    score_color = (
        config.COLOR_GOOD if metrics.session_score >= 70 else
        config.COLOR_WARN if metrics.session_score >= 40 else
        config.COLOR_BAD
    )
    put_text(frame, f"Session Score: {metrics.session_score:.0f}/100 | Mode: {personality.upper()}", (x, y), config.FONT_SCALE_VALUE, score_color); y += line_gap

    put_text(frame, f"FPS: {fps:.1f} | Web Dashboard: http://localhost:5000", (x, y), config.FONT_SCALE_LABEL, config.COLOR_TEXT)

    # --- status dot, top-right ---
    dot_color = config.COLOR_BAD if (metrics.sustained_slouch or metrics.ocular_fatigue or metrics.is_too_close) else config.COLOR_GOOD
    cv2.circle(frame, (w - 30, 30), 12, dot_color, -1, lineType=cv2.LINE_AA)

    # --- footer hint bar ---
    hint = f"[c]calib [p]mode:{personality[:6]} [s]voice:{'ON' if sound_on else 'OFF'} [b]reset-break [q]quit"
    draw_translucent_panel(frame, 0, h - 30, w, 30, color=(15, 15, 15), alpha=0.6)
    put_text(frame, hint, (10, h - 10), config.FONT_SCALE_LABEL, config.COLOR_TEXT)


def draw_warning_banner(frame: np.ndarray, text: str) -> None:
    h, w = frame.shape[:2]
    draw_translucent_panel(frame, 0, h - 70, w, 40, color=(0, 0, 120), alpha=0.7)
    put_text(frame, text, (16, h - 42), config.FONT_SCALE_VALUE, (255, 255, 255), 2)


# =========================================================================
# CAMERA INITIALIZATION
# =========================================================================

def open_camera(index: int) -> Optional[cv2.VideoCapture]:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(index, cv2.CAP_ANY)

    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)
    return cap


# =========================================================================
# MAIN LOOP
# =========================================================================

def main() -> int:
    print("Initializing PostureGuard Pro...")

    # Start Flask Analytics Web Server
    start_server_thread()
    print("Live Web Dashboard running at http://localhost:5000")

    cap = open_camera(config.CAMERA_INDEX)
    if cap is None:
        print(f"ERROR: Could not open camera at index {config.CAMERA_INDEX}.")
        return 1

    try:
        tracker = PostureFatigueTracker()
    except ImportError as exc:
        print(f"ERROR: {exc}")
        cap.release()
        return 1

    personalities = ["scolding", "gentle", "cyberpunk"]
    personality_idx = 0
    dispatcher = AlertDispatcher(personality=personalities[personality_idx])
    sound_on = config.ALERT_SOUND_ENABLED
    notif_on = config.ALERT_NOTIFICATION_ENABLED

    cv2.namedWindow(config.WINDOW_NAME, cv2.WINDOW_NORMAL)

    consecutive_failures = 0
    fps = 0.0
    fps_smoother_alpha = 0.15
    prev_tick = time.time()

    print("Camera opened. Starting calibration phase...")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_failures += 1
                time.sleep(0.1)
                if consecutive_failures % 30 == 0:
                    # Attempt cap re-initialization
                    cap.release()
                    cap = open_camera(config.CAMERA_INDEX) or cap
                continue
            consecutive_failures = 0

            if config.FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            metrics = tracker.process(frame)

            # Update telemetry for Web Server
            update_telemetry(metrics, dispatcher.personality)

            # FPS Calculation
            now_tick = time.time()
            instant_dt = now_tick - prev_tick
            prev_tick = now_tick
            if instant_dt > 0:
                instant_fps = 1.0 / instant_dt
                fps = instant_fps if fps == 0 else (
                    fps_smoother_alpha * instant_fps + (1 - fps_smoother_alpha) * fps
                )

            # Drawing
            draw_skeleton_overlay(frame, metrics)

            if metrics.is_calibrating:
                draw_calibration_ui(frame, metrics)
            else:
                draw_dashboard(frame, metrics, fps, sound_on, notif_on, dispatcher.personality)

            if metrics.warning:
                draw_warning_banner(frame, metrics.warning)

            # Evaluated Alerts
            if not metrics.is_calibrating:
                dispatcher.evaluate(
                    key="slouch",
                    is_active=metrics.sustained_slouch,
                    title="PostureGuard: Slouching detected",
                    message="You've been slouching for a while. Sit up straight!",
                    voice_prompt=dispatcher.get_prompt_text("slouch", metrics.slouch_reason)
                )
                dispatcher.evaluate(
                    key="fatigue",
                    is_active=metrics.ocular_fatigue,
                    title="PostureGuard: Eye fatigue detected",
                    message="Your blink pattern suggests eye strain. Take a break.",
                    voice_prompt=dispatcher.get_prompt_text("fatigue", metrics.fatigue_reason)
                )
                dispatcher.evaluate(
                    key="too_close",
                    is_active=metrics.is_too_close,
                    title="PostureGuard: Too close to screen",
                    message="Move back from the monitor to protect your eyes.",
                )
                dispatcher.evaluate(
                    key="low_light",
                    is_active=metrics.is_low_light,
                    title="PostureGuard: Low ambient light",
                    message="Room illumination is low. Turn on more lights.",
                )
                if metrics.break_recommended:
                    dispatcher.trigger_break_alert()
                    tracker.reset_break_timer()

            cv2.imshow(config.WINDOW_NAME, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("c"):
                tracker.start_calibration()
            elif key == ord("s"):
                sound_on = not sound_on
                dispatcher.sound_enabled = sound_on
            elif key == ord("n"):
                notif_on = not notif_on
                dispatcher.notifications_enabled = notif_on
            elif key == ord("p"):
                personality_idx = (personality_idx + 1) % len(personalities)
                dispatcher.set_personality(personalities[personality_idx])
                print(f"Switched Voice Personality to: {personalities[personality_idx]}")
            elif key == ord("b"):
                tracker.reset_break_timer()
                print("20-20-20 Break Timer Reset.")

            try:
                if cv2.getWindowProperty(config.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break

    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()
        print("PostureGuard shut down cleanly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
