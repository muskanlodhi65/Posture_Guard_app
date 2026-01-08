"""
main.py
-------
PostureGuard entry point: opens the webcam, runs the MediaPipe-based
PostureFatigueTracker on every frame, renders a live OpenCV telemetry
dashboard with a skeletal overlay, and dispatches debounced alerts on
sustained violations.

Controls (while the video window is focused):
    q / ESC  -> quit
    c        -> re-run the 5-second calibration phase
    s        -> toggle sound alerts on/off
    n        -> toggle desktop notifications on/off

Run:
    python main.py
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
from tracker import FrameMetrics, PostureFatigueTracker


# =========================================================================
# UI HELPERS
# =========================================================================

def draw_translucent_panel(frame: np.ndarray, x: int, y: int, w: int, h: int,
                            color=config.COLOR_PANEL_BG, alpha: float = config.UI_PANEL_ALPHA) -> None:
    """Draw a semi-transparent filled rectangle panel onto `frame` in place."""
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
    """Draw shoulder/ear landmarks + connecting lines, and eye contours."""
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

    if metrics.eye_landmarks_px:
        eye_color = config.COLOR_WARN if metrics.is_eyes_closed else config.COLOR_ACCENT
        for eye_key in ("left_eye", "right_eye"):
            eye_pts = metrics.eye_landmarks_px.get(eye_key)
            if not eye_pts:
                continue
            poly = np.array([[int(px), int(py)] for px, py in eye_pts], dtype=np.int32)
            cv2.polylines(frame, [poly], isClosed=True, color=eye_color, thickness=1, lineType=cv2.LINE_AA)


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
                    sound_on: bool, notif_on: bool) -> None:
    h, w = frame.shape[:2]
    panel_w = 300
    panel_h = 250
    margin = 12
    draw_translucent_panel(frame, margin, margin, panel_w, panel_h)

    x = margin + 14
    y = margin + 28
    line_gap = 26

    put_text(frame, "PostureGuard Telemetry", (x, y), config.FONT_SCALE_TITLE, config.COLOR_ACCENT, 2)
    y += line_gap + 4

    posture_color = config.COLOR_BAD if metrics.sustained_slouch else (
        config.COLOR_WARN if metrics.is_slouching else config.COLOR_GOOD
    )
    posture_label = "SLOUCHING" if metrics.sustained_slouch else ("Adjusting..." if metrics.is_slouching else "GOOD")
    cva_text = f"{metrics.cva_smoothed:.1f} deg" if metrics.cva_smoothed is not None else "N/A"
    put_text(frame, f"CVA: {cva_text}", (x, y), config.FONT_SCALE_VALUE, config.COLOR_TEXT); y += line_gap
    put_text(frame, f"Posture: {posture_label}", (x, y), config.FONT_SCALE_VALUE, posture_color); y += line_gap

    ear_text = f"{metrics.ear_smoothed:.3f}" if metrics.ear_smoothed is not None else "N/A"
    eye_color = config.COLOR_WARN if metrics.is_eyes_closed else config.COLOR_GOOD
    put_text(frame, f"EAR: {ear_text}", (x, y), config.FONT_SCALE_VALUE, config.COLOR_TEXT); y += line_gap
    put_text(frame, f"Blink Rate: {metrics.blink_rate_bpm:.1f} bpm", (x, y), config.FONT_SCALE_VALUE, config.COLOR_TEXT); y += line_gap

    fatigue_color = config.COLOR_BAD if metrics.ocular_fatigue else config.COLOR_GOOD
    fatigue_label = "FATIGUE" if metrics.ocular_fatigue else "Alert"
    put_text(frame, f"Ocular State: {fatigue_label}", (x, y), config.FONT_SCALE_VALUE, fatigue_color); y += line_gap

    score_color = (
        config.COLOR_GOOD if metrics.session_score >= 70 else
        config.COLOR_WARN if metrics.session_score >= 40 else
        config.COLOR_BAD
    )
    put_text(frame, f"Session Score: {metrics.session_score:.0f}/100", (x, y), config.FONT_SCALE_VALUE, score_color); y += line_gap

    put_text(frame, f"FPS: {fps:.1f}   Blinks: {metrics.blink_count_total}", (x, y), config.FONT_SCALE_LABEL, config.COLOR_TEXT)

    # --- status dot, top-right ---
    dot_color = config.COLOR_BAD if (metrics.sustained_slouch or metrics.ocular_fatigue) else config.COLOR_GOOD
    cv2.circle(frame, (w - 30, 30), 12, dot_color, -1, lineType=cv2.LINE_AA)

    # --- footer hint bar ---
    hint = f"[c] recalibrate  [s] sound:{'ON' if sound_on else 'OFF'}  [n] notify:{'ON' if notif_on else 'OFF'}  [q] quit"
    draw_translucent_panel(frame, 0, h - 30, w, 30, color=(15, 15, 15), alpha=0.6)
    put_text(frame, hint, (10, h - 10), config.FONT_SCALE_LABEL, config.COLOR_TEXT)

    if metrics.slouch_reason and metrics.sustained_slouch:
        put_text(frame, f"Cause: {metrics.slouch_reason}", (margin + 14, margin + panel_h - 10),
                  config.FONT_SCALE_LABEL, config.COLOR_WARN)


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
        # Retry once with the default backend hint removed, common fix on Windows/Linux
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
    print("Initializing PostureGuard...")
    print(f"Attempting to open camera index {config.CAMERA_INDEX} ...")

    cap = open_camera(config.CAMERA_INDEX)
    if cap is None:
        print(
            f"ERROR: Could not open webcam at index {config.CAMERA_INDEX}. "
            "Check that a camera is connected, not in use by another app, "
            "and that OS camera permissions are granted."
        )
        return 1

    try:
        tracker = PostureFatigueTracker()
    except ImportError as exc:
        print(f"ERROR: {exc}")
        cap.release()
        return 1

    dispatcher = AlertDispatcher()
    sound_on = config.ALERT_SOUND_ENABLED
    notif_on = config.ALERT_NOTIFICATION_ENABLED

    cv2.namedWindow(config.WINDOW_NAME, cv2.WINDOW_NORMAL)

    consecutive_failures = 0
    fps = 0.0
    fps_smoother_alpha = 0.15
    prev_tick = time.time()

    print("Camera opened. Starting calibration -- please sit upright and look at the screen.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_failures += 1
                print(f"WARNING: Failed to read frame ({consecutive_failures}/"
                      f"{config.MAX_CONSECUTIVE_FRAME_FAILURES}).")
                if consecutive_failures >= config.MAX_CONSECUTIVE_FRAME_FAILURES:
                    print("ERROR: Too many consecutive camera read failures. Exiting.")
                    break
                time.sleep(0.05)
                continue
            consecutive_failures = 0

            if config.FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            metrics = tracker.process(frame)

            # --- FPS (EMA-smoothed) ---
            now_tick = time.time()
            instant_dt = now_tick - prev_tick
            prev_tick = now_tick
            if instant_dt > 0:
                instant_fps = 1.0 / instant_dt
                fps = instant_fps if fps == 0 else (
                    fps_smoother_alpha * instant_fps + (1 - fps_smoother_alpha) * fps
                )

            # --- drawing ---
            draw_skeleton_overlay(frame, metrics)

            if metrics.is_calibrating:
                draw_calibration_ui(frame, metrics)
            else:
                draw_dashboard(frame, metrics, fps, sound_on, notif_on)

            if metrics.warning:
                draw_warning_banner(frame, metrics.warning)

            # --- alert dispatch (debounced, non-blocking) ---
            if not metrics.is_calibrating:
                dispatcher.evaluate(
                    key="slouch",
                    is_active=metrics.sustained_slouch,
                    title="PostureGuard: Slouching detected",
                    message="You've been slouching for a while. Sit up straight!",
                )
                dispatcher.evaluate(
                    key="fatigue",
                    is_active=metrics.ocular_fatigue,
                    title="PostureGuard: Eye fatigue detected",
                    message="Your blink pattern suggests eye strain. Take a 20-second break.",
                )

            cv2.imshow(config.WINDOW_NAME, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # 'q' or ESC
                break
            elif key == ord("c"):
                print("Recalibrating...")
                tracker.start_calibration()
            elif key == ord("s"):
                sound_on = not sound_on
                dispatcher.sound_enabled = sound_on
            elif key == ord("n"):
                notif_on = not notif_on
                dispatcher.notifications_enabled = notif_on

            # Window closed via the 'x' button
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
