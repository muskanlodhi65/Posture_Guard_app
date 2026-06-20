"""
main.py
-------
Main execution pipeline for PostureGuard.
Integrates MediaPipe tracking, Flask live analytics web server,
thread-safe Indian accent voice dispatcher, and OpenCV camera overlay UI with OPEN DASHBOARD button.
"""

from __future__ import annotations

import sys
import time
import webbrowser
import cv2
import numpy as np

from alerts import AlertDispatcher
import config
from server import register_dispatcher, start_server_thread, update_telemetry
from tracker import FrameMetrics, PostureFatigueTracker

# =========================================================================
# UI DRAWING HELPERS
# =========================================================================

def draw_translucent_panel(
    frame: np.ndarray, x: int, y: int, w: int, h: int,
    color: tuple = (20, 20, 20), alpha: float = 0.55
) -> None:
    sub = frame[y:y+h, x:x+w]
    rect = np.full_like(sub, color, dtype=np.uint8)
    frame[y:y+h, x:x+w] = cv2.addWeighted(sub, 1 - alpha, rect, alpha, 0)


def put_text(
    frame: np.ndarray, text: str, pos: tuple,
    scale: float = 0.6, color: tuple = (255, 255, 255), thickness: int = 1
) -> None:
    cv2.putText(frame, text, pos, config.FONT_FAMILY, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, pos, config.FONT_FAMILY, scale, color, thickness, cv2.LINE_AA)


def draw_skeleton_overlay(frame: np.ndarray, metrics: FrameMetrics) -> None:
    if metrics.eye_landmarks_px:
        for eye_key in ("left_eye", "right_eye"):
            pts = metrics.eye_landmarks_px.get(eye_key, [])
            if len(pts) >= 6:
                pts_int = np.array(pts, dtype=np.int32)
                cv2.polylines(frame, [pts_int], True, (255, 255, 0), 1, cv2.LINE_AA)


def draw_calibration_ui(frame: np.ndarray, metrics: FrameMetrics) -> None:
    h, w = frame.shape[:2]
    draw_translucent_panel(frame, 0, 0, w, h, color=(10, 10, 30), alpha=0.6)
    pct = int(metrics.calibration_progress * 100)
    bar_w = int((w - 200) * metrics.calibration_progress)
    cv2.rectangle(frame, (100, h // 2), (w - 100, h // 2 + 30), (50, 50, 50), -1)
    cv2.rectangle(frame, (100, h // 2), (100 + bar_w, h // 2 + 30), (0, 255, 255), -1)
    put_text(frame, "CALIBRATING ERGONOMIC BASELINE...", (100, h // 2 - 20), 0.8, (0, 255, 255), 2)
    put_text(frame, f"Sit up straight and look at the screen ({pct}%)", (100, h // 2 + 60), 0.6, (255, 255, 255))


def draw_dashboard(
    frame: np.ndarray,
    metrics: FrameMetrics,
    fps: float,
    sound_on: bool,
    notif_on: bool,
    personality: str,
) -> None:
    h, w = frame.shape[:2]

    # --- Left HUD Panel ---
    panel_w, panel_h = 420, 235
    draw_translucent_panel(frame, 10, 10, panel_w, panel_h, color=(20, 20, 20), alpha=0.65)

    x, y = 20, 32
    line_gap = 25

    posture_color = config.COLOR_BAD if metrics.sustained_slouch else config.COLOR_GOOD
    posture_label = "SLOUCHING" if metrics.sustained_slouch else ("Bad" if metrics.is_slouching else "Good")
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

    put_text(frame, f"FPS: {fps:.1f} | Web: http://127.0.0.1:5000", (x, y), config.FONT_SCALE_LABEL, config.COLOR_TEXT)

    # --- Top-Right GLOWING "OPEN DASHBOARD" BUTTON ---
    btn_w, btn_h = 240, 42
    btn_x, btn_y = w - btn_w - 20, 15
    draw_translucent_panel(frame, btn_x, btn_y, btn_w, btn_h, color=(168, 85, 247), alpha=0.85)
    cv2.rectangle(frame, (btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h), (56, 189, 248), 2, cv2.LINE_AA)
    put_text(frame, "OPEN DASHBOARD [D]", (btn_x + 16, btn_y + 27), 0.65, (255, 255, 255), 2)

    # --- Status dot ---
    dot_color = config.COLOR_BAD if (metrics.sustained_slouch or metrics.ocular_fatigue or metrics.is_too_close) else config.COLOR_GOOD
    cv2.circle(frame, (w - 285, 35), 10, dot_color, -1, lineType=cv2.LINE_AA)

    # --- Footer hint bar ---
    hint = f"[d]OPEN DASHBOARD [c]calib [p]mode:{personality[:6]} [s]voice:{'ON' if sound_on else 'OFF'} [b]reset-break [q]quit"
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
    if sys.platform.startswith("win"):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            print(f"Camera {index} opened via DirectShow backend.")
            return cap

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(index, cv2.CAP_ANY)

    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


# =========================================================================
# MAIN LOOP
# =========================================================================

def main() -> int:
    print("Initializing PostureGuard Pro...")

    # Start Flask Analytics Web Server
    start_server_thread()
    print("Live Web Dashboard running at http://127.0.0.1:5000")

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

    personalities = ["angry_hindi", "angry_english", "hindi_scolding", "scolding", "hindi_gentle", "gentle", "cyberpunk"]
    personality_idx = 0
    dispatcher = AlertDispatcher(personality=personalities[personality_idx], user_name=config.USER_NAME)
    register_dispatcher(dispatcher)
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
                    cap.release()
                    cap = open_camera(config.CAMERA_INDEX) or cap
                continue
            consecutive_failures = 0

            if config.FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            metrics = tracker.process(frame)
            update_telemetry(metrics, dispatcher.personality)

            now_tick = time.time()
            instant_dt = now_tick - prev_tick
            prev_tick = now_tick
            if instant_dt > 0:
                instant_fps = 1.0 / instant_dt
                fps = instant_fps if fps == 0 else (
                    fps_smoother_alpha * instant_fps + (1 - fps_smoother_alpha) * fps
                )

            draw_skeleton_overlay(frame, metrics)

            if metrics.is_calibrating:
                draw_calibration_ui(frame, metrics)
            else:
                draw_dashboard(frame, metrics, fps, sound_on, notif_on, dispatcher.personality)

            if metrics.warning:
                draw_warning_banner(frame, metrics.warning)

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
                    voice_prompt=dispatcher.get_prompt_text("too_close")
                )
                dispatcher.evaluate(
                    key="low_light",
                    is_active=metrics.is_low_light,
                    title="PostureGuard: Low ambient light",
                    message="Room illumination is low. Turn on more lights.",
                    voice_prompt=dispatcher.get_prompt_text("low_light")
                )
                if metrics.break_recommended:
                    dispatcher.trigger_break_alert()
                    tracker.reset_break_timer()

            cv2.imshow(config.WINDOW_NAME, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("d"):
                print("Opening Live Dashboard in Browser...")
                webbrowser.open("http://127.0.0.1:5000")
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
                pass
            except cv2.error:
                pass

    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()
        print("PostureGuard shut down cleanly.")


if __name__ == "__main__":
    sys.exit(main())
