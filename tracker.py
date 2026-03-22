"""
tracker.py
----------
Wraps MediaPipe Vision Tasks (PoseLandmarker + FaceLandmarker) inference, owns calibration state,
temporal EMA smoothing, the sliding-window "sustained bad posture"
buffer, the blink/EAR state machine, and rolling session scoring.

This is the stateful heart of PostureGuard. `main.py` calls
`PostureFatigueTracker.process(frame)` once per video frame and receives
back a `FrameMetrics` snapshot ready for UI rendering and alerting.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
except ImportError as exc:  # pragma: no cover - handled at runtime in main.py
    raise ImportError(
        "mediapipe is required for tracker.py. Install it with "
        "`pip install mediapipe`."
    ) from exc

import config
import geometry


# =========================================================================
# DATA CONTAINERS
# =========================================================================

@dataclass
class Baseline:
    """Personal ergonomic baseline captured during the calibration phase."""
    cva: float = 0.0
    shoulder_y: float = 0.0
    shoulder_tilt: float = 0.0
    face_diag: float = 0.0
    ear: float = config.EAR_DEFAULT_THRESHOLD / config.EAR_DYNAMIC_THRESHOLD_RATIO
    calibrated: bool = False

    @property
    def ear_blink_threshold(self) -> float:
        if self.calibrated and self.ear > 0:
            return self.ear * config.EAR_DYNAMIC_THRESHOLD_RATIO
        return config.EAR_DEFAULT_THRESHOLD


@dataclass
class FrameMetrics:
    """Everything the UI layer needs to render one processed frame."""
    timestamp: float
    landmarks_found: bool = False
    face_found: bool = False

    cva_raw: Optional[float] = None
    cva_smoothed: Optional[float] = None
    shoulder_mid_y: Optional[float] = None
    shoulder_tilt: Optional[float] = None
    face_diag: Optional[float] = None

    ear_raw: Optional[float] = None
    ear_smoothed: Optional[float] = None

    is_slouching: bool = False
    sustained_slouch: bool = False
    slouch_reason: str = ""

    is_eyes_closed: bool = False
    prolonged_closed: bool = False
    blink_count_total: int = 0
    blink_rate_bpm: float = 0.0
    ocular_fatigue: bool = False
    fatigue_reason: str = ""

    session_score: float = config.SESSION_SCORE_START

    is_calibrating: bool = False
    calibration_progress: float = 0.0  # 0..1
    calibration_done: bool = False

    is_too_close: bool = False
    is_low_light: bool = False
    ambient_luminance: float = 0.0

    break_recommended: bool = False
    break_time_remaining: float = config.BREAK_REMINDER_INTERVAL_SEC

    pose_landmarks_px: Optional[dict] = None   # for drawing skeleton
    eye_landmarks_px: Optional[dict] = None    # for drawing eye contours

    warning: str = ""  # e.g. "No person detected", "Move closer to camera"


# =========================================================================
# TRACKER
# =========================================================================

class PostureFatigueTracker:
    """
    Stateful pipeline: raw frame -> MediaPipe landmarks -> geometry ->
    EMA smoothing -> calibration-relative classification -> sliding-window
    sustained-alert logic -> blink/fatigue state machine -> session score.
    """

    def __init__(self) -> None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        pose_model_path = os.path.join(base_dir, "pose_landmarker.task")
        face_model_path = os.path.join(base_dir, "face_landmarker.task")

        pose_options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=pose_model_path),
            running_mode=vision.RunningMode.IMAGE,
            min_pose_detection_confidence=config.POSE_MIN_DETECTION_CONFIDENCE,
            min_pose_presence_confidence=config.POSE_MIN_TRACKING_CONFIDENCE,
            min_tracking_confidence=config.POSE_MIN_TRACKING_CONFIDENCE,
        )
        face_options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=face_model_path),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=config.FACEMESH_MIN_DETECTION_CONFIDENCE,
            min_face_presence_confidence=config.FACEMESH_MIN_TRACKING_CONFIDENCE,
            min_tracking_confidence=config.FACEMESH_MIN_TRACKING_CONFIDENCE,
        )

        self.pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        self.face_landmarker = vision.FaceLandmarker.create_from_options(face_options)

        # --- calibration state ---
        self.baseline = Baseline()
        self.is_calibrating = False
        self.calibration_start_time: Optional[float] = None
        self._calib_cva: List[float] = []
        self._calib_shoulder_y: List[float] = []
        self._calib_shoulder_tilt: List[float] = []
        self._calib_face_diag: List[float] = []
        self._calib_ear: List[float] = []

        # --- EMA smoothing state ---
        self._ema_cva: Optional[float] = None
        self._ema_shoulder_y: Optional[float] = None
        self._ema_shoulder_tilt: Optional[float] = None
        self._ema_ear: Optional[float] = None

        # --- sliding window buffers: (timestamp, is_bad: bool) ---
        self.posture_buffer: Deque[Tuple[float, bool]] = deque()
        self.fatigue_buffer: Deque[Tuple[float, bool]] = deque()

        # --- blink state machine ---
        self._eye_closed_consec_frames = 0
        self._eye_closed_since: Optional[float] = None
        self.blink_count_total = 0
        self._blink_timestamps: Deque[float] = deque()

        # --- session score ---
        self.session_score = config.SESSION_SCORE_START
        self._last_process_time: Optional[float] = None

        # --- "no person" grace tracking ---
        self._last_seen_time: Optional[float] = None

        # --- break timer state ---
        self.session_start_time = time.time()
        self.last_break_time = time.time()

        # start calibration automatically on construction
        self.start_calibration()

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------
    def start_calibration(self) -> None:
        """(Re)start the calibration phase. Resets baseline + EMA state."""
        self.is_calibrating = True
        self.calibration_start_time = time.time()
        self.last_break_time = time.time()
        self._calib_cva = []
        self._calib_shoulder_y = []
        self._calib_shoulder_tilt = []
        self._calib_face_diag = []
        self._calib_ear = []
        self.baseline = Baseline()
        self._ema_cva = None
        self._ema_shoulder_y = None
        self._ema_shoulder_tilt = None
        self._ema_ear = None
        self.posture_buffer.clear()
        self.fatigue_buffer.clear()

    def reset_break_timer(self) -> None:
        self.last_break_time = time.time()

    def close(self) -> None:
        """Release MediaPipe resources."""
        self.pose_landmarker.close()
        self.face_landmarker.close()

    # ------------------------------------------------------------------
    # Main per-frame entry point
    # ------------------------------------------------------------------
    def process(self, frame_bgr: np.ndarray) -> FrameMetrics:
        now = time.time()
        dt = 0.0 if self._last_process_time is None else max(0.0, now - self._last_process_time)
        self._last_process_time = now

        h, w = frame_bgr.shape[:2]

        # --- Low light room luminance check ---
        gray = np.mean(frame_bgr, axis=2)
        ambient_luminance = float(np.mean(gray))

        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        pose_result = self.pose_landmarker.detect(mp_image)
        face_result = self.face_landmarker.detect(mp_image)

        metrics = FrameMetrics(timestamp=now)
        metrics.ambient_luminance = ambient_luminance
        metrics.is_low_light = ambient_luminance < config.LOW_LIGHT_LUMINANCE_THRESHOLD

        # 20-20-20 Break Timer calculation
        elapsed_since_break = now - self.last_break_time
        metrics.break_time_remaining = max(0.0, config.BREAK_REMINDER_INTERVAL_SEC - elapsed_since_break)
        if elapsed_since_break >= config.BREAK_REMINDER_INTERVAL_SEC:
            metrics.break_recommended = True

        pose_ok, pose_data = self._extract_pose(pose_result, w, h)
        face_ok, face_data = self._extract_face(face_result, w, h)

        metrics.landmarks_found = pose_ok
        metrics.face_found = face_ok

        # Debug: print detection status every ~3 seconds (90 frames at 30fps)
        if not hasattr(self, '_debug_frame_count'):
            self._debug_frame_count = 0
        self._debug_frame_count += 1
        if self._debug_frame_count % 90 == 0:
            print(f"[DEBUG] Pose detected: {pose_ok} | Face detected: {face_ok} | Light: {round(ambient_luminance, 1)}")

        if not pose_ok and not face_ok:
            self._handle_no_person(now, metrics)
            return metrics

        self._last_seen_time = now

        if pose_ok:
            self._process_posture(pose_data, face_data, metrics, now)
        if face_ok:
            self._process_eyes(face_data, metrics, now, dt)

            # --- Too close to screen check ---
            if self.baseline.calibrated and self.baseline.face_diag > 1e-3 and metrics.face_diag:
                if metrics.face_diag > (self.baseline.face_diag * config.FACE_TOO_CLOSE_RATIO):
                    metrics.is_too_close = True

        if self.is_calibrating:
            self._update_calibration(metrics, now)
        else:
            self._update_sustained_buffers(metrics, now)
            self._update_session_score(metrics, dt)

        metrics.is_calibrating = self.is_calibrating
        metrics.calibration_done = self.baseline.calibrated
        metrics.session_score = self.session_score
        metrics.blink_count_total = self.blink_count_total
        return metrics

    # ------------------------------------------------------------------
    # Landmark extraction helpers
    # ------------------------------------------------------------------
    def _extract_pose(self, pose_result, w: int, h: int):
        if not pose_result.pose_landmarks or len(pose_result.pose_landmarks) == 0:
            return False, None

        lm = pose_result.pose_landmarks[0]
        needed = {
            "left_shoulder": lm[config.LEFT_SHOULDER],
            "right_shoulder": lm[config.RIGHT_SHOULDER],
            "left_ear": lm[config.LEFT_EAR],
            "right_ear": lm[config.RIGHT_EAR],
        }

        visible = {
            name: (getattr(p, "visibility", 1.0) >= config.POSE_VISIBILITY_THRESHOLD)
            for name, p in needed.items()
        }

        # We need at least one full ear-shoulder pair to compute CVA.
        if not ((visible["left_shoulder"] and visible["left_ear"]) or
                (visible["right_shoulder"] and visible["right_ear"])):
            return False, None

        px = {name: (p.x * w, p.y * h) for name, p in needed.items()}
        px_visible = visible

        return True, {
            "points_px": px,
            "visible": px_visible,
            "raw_landmarks": lm,
        }

    def _extract_face(self, face_result, w: int, h: int):
        if not face_result.face_landmarks or len(face_result.face_landmarks) == 0:
            return False, None

        lm = face_result.face_landmarks[0]

        try:
            right_eye_px = [(lm[i].x * w, lm[i].y * h) for i in config.RIGHT_EYE_EAR_IDX]
            left_eye_px = [(lm[i].x * w, lm[i].y * h) for i in config.LEFT_EYE_EAR_IDX]
            oval_px = [(lm[i].x * w, lm[i].y * h) for i in config.FACE_OVAL_EXTREMES_IDX]
        except IndexError:
            return False, None

        return True, {
            "right_eye_px": right_eye_px,
            "left_eye_px": left_eye_px,
            "face_oval_px": oval_px,
        }

    # ------------------------------------------------------------------
    # Posture (CVA / slouch) processing
    # ------------------------------------------------------------------
    def _process_posture(self, pose_data, face_data, metrics: FrameMetrics, now: float) -> None:
        pts = pose_data["points_px"]
        vis = pose_data["visible"]

        cva_samples = []
        if vis["left_shoulder"] and vis["left_ear"]:
            cva_samples.append(geometry.calculate_cva(pts["left_shoulder"], pts["left_ear"]))
        if vis["right_shoulder"] and vis["right_ear"]:
            cva_samples.append(geometry.calculate_cva(pts["right_shoulder"], pts["right_ear"]))
        cva_raw = float(np.mean(cva_samples)) if cva_samples else None

        if vis["left_shoulder"] and vis["right_shoulder"]:
            shoulder_mid = geometry.midpoint(pts["left_shoulder"], pts["right_shoulder"])
            shoulder_tilt_raw = abs(pts["left_shoulder"][1] - pts["right_shoulder"][1])
        elif vis["left_shoulder"]:
            shoulder_mid = pts["left_shoulder"]
            shoulder_tilt_raw = 0.0
        elif vis["right_shoulder"]:
            shoulder_mid = pts["right_shoulder"]
            shoulder_tilt_raw = 0.0
        else:
            shoulder_mid = None
            shoulder_tilt_raw = None

        face_diag = None
        if face_data is not None:
            bbox = geometry.bbox_from_points(face_data["face_oval_px"])
            face_diag = geometry.bbox_diagonal(bbox)

        # --- EMA smoothing ---
        if cva_raw is not None:
            self._ema_cva = geometry.ema_update(self._ema_cva, cva_raw, config.EMA_ALPHA_CVA)
        if shoulder_mid is not None:
            self._ema_shoulder_y = geometry.ema_update(
                self._ema_shoulder_y, shoulder_mid[1], config.EMA_ALPHA_SHOULDER
            )
        if shoulder_tilt_raw is not None:
            self._ema_shoulder_tilt = geometry.ema_update(
                self._ema_shoulder_tilt, shoulder_tilt_raw, config.EMA_ALPHA_SHOULDER
            )

        metrics.cva_raw = cva_raw
        metrics.cva_smoothed = self._ema_cva
        metrics.shoulder_mid_y = self._ema_shoulder_y
        metrics.shoulder_tilt = self._ema_shoulder_tilt
        metrics.face_diag = face_diag
        metrics.pose_landmarks_px = pts

        if self.is_calibrating:
            return  # classification happens only once calibrated

        self._classify_posture(metrics, face_diag)

    def _classify_posture(self, metrics: FrameMetrics, face_diag: Optional[float]) -> None:
        if not self.baseline.calibrated or metrics.cva_smoothed is None:
            metrics.is_slouching = False
            return

        reasons = []

        # 1) CVA drop relative to personal baseline
        cva_delta = self.baseline.cva - metrics.cva_smoothed
        if cva_delta >= config.CVA_SLOUCH_DELTA_DEG:
            reasons.append("Forward head tilt")

        # 2) Absolute CVA floor (safety net regardless of baseline quality)
        if metrics.cva_smoothed < config.CVA_ABSOLUTE_FLOOR_DEG:
            reasons.append("Low CVA")

        # 3) Shoulder vertical drop, normalized by face-size distance proxy
        ref_diag = face_diag or self.baseline.face_diag
        if (metrics.shoulder_mid_y is not None and ref_diag and ref_diag > 1e-3
                and self.baseline.shoulder_y):
            drop = (metrics.shoulder_mid_y - self.baseline.shoulder_y) / ref_diag
            if drop >= config.SHOULDER_DROP_RATIO_THRESHOLD:
                reasons.append("Shoulder slump")

        # 4) Shoulder lateral tilt (leaning to one side)
        if (metrics.shoulder_tilt is not None and ref_diag and ref_diag > 1e-3):
            tilt_ratio = metrics.shoulder_tilt / ref_diag
            if tilt_ratio >= config.SHOULDER_TILT_RATIO_THRESHOLD:
                reasons.append("Uneven shoulders")

        metrics.is_slouching = len(reasons) > 0
        metrics.slouch_reason = ", ".join(reasons)

    # ------------------------------------------------------------------
    # Eyes: EAR / blink / fatigue processing
    # ------------------------------------------------------------------
    def _process_eyes(self, face_data, metrics: FrameMetrics, now: float, dt: float) -> None:
        right_ear = geometry.eye_aspect_ratio(face_data["right_eye_px"])
        left_ear = geometry.eye_aspect_ratio(face_data["left_eye_px"])
        ear_raw = (right_ear + left_ear) / 2.0

        self._ema_ear = geometry.ema_update(self._ema_ear, ear_raw, config.EMA_ALPHA_EAR)

        metrics.ear_raw = ear_raw
        metrics.ear_smoothed = self._ema_ear
        metrics.eye_landmarks_px = {
            "right_eye": face_data["right_eye_px"],
            "left_eye": face_data["left_eye_px"],
        }

        threshold = self.baseline.ear_blink_threshold
        eyes_closed = self._ema_ear is not None and self._ema_ear < threshold
        metrics.is_eyes_closed = eyes_closed

        if self.is_calibrating:
            return

        # --- blink counting state machine ---
        if eyes_closed:
            self._eye_closed_consec_frames += 1
            if self._eye_closed_since is None:
                self._eye_closed_since = now
        else:
            if self._eye_closed_consec_frames >= config.EAR_CONSEC_FRAMES_FOR_BLINK:
                self.blink_count_total += 1
                self._blink_timestamps.append(now)
            self._eye_closed_consec_frames = 0
            self._eye_closed_since = None

        # --- prolonged closed-eye detection (drowsiness) ---
        prolonged = False
        if self._eye_closed_since is not None:
            closed_duration = now - self._eye_closed_since
            if closed_duration >= config.EAR_PROLONGED_CLOSED_SEC:
                prolonged = True
        metrics.prolonged_closed = prolonged

        # --- rolling blink rate (BPM) ---
        while self._blink_timestamps and (now - self._blink_timestamps[0]) > config.BLINK_RATE_WINDOW_SEC:
            self._blink_timestamps.popleft()

        elapsed_for_rate = min(now - (self.calibration_start_time or now), config.BLINK_RATE_WINDOW_SEC)
        elapsed_for_rate = max(elapsed_for_rate, 5.0)  # avoid wild extrapolation in first seconds
        bpm = (len(self._blink_timestamps) / elapsed_for_rate) * 60.0
        metrics.blink_rate_bpm = bpm

        fatigue_reasons = []
        if prolonged:
            fatigue_reasons.append("Prolonged eye closure")
        if elapsed_for_rate >= config.BLINK_RATE_WINDOW_SEC and bpm < config.LOW_BLINK_RATE_BPM_THRESHOLD:
            fatigue_reasons.append("Low blink rate")
        if elapsed_for_rate >= config.BLINK_RATE_WINDOW_SEC and bpm > config.HIGH_BLINK_RATE_BPM_THRESHOLD:
            fatigue_reasons.append("Excessive blinking")

        metrics.ocular_fatigue = len(fatigue_reasons) > 0
        metrics.fatigue_reason = ", ".join(fatigue_reasons)

    # ------------------------------------------------------------------
    # Calibration accumulation
    # ------------------------------------------------------------------
    def _update_calibration(self, metrics: FrameMetrics, now: float) -> None:
        elapsed = now - (self.calibration_start_time or now)
        metrics.calibration_progress = min(1.0, elapsed / config.CALIBRATION_DURATION_SEC)

        if metrics.cva_smoothed is not None:
            self._calib_cva.append(metrics.cva_smoothed)
        if metrics.shoulder_mid_y is not None:
            self._calib_shoulder_y.append(metrics.shoulder_mid_y)
        if metrics.shoulder_tilt is not None:
            self._calib_shoulder_tilt.append(metrics.shoulder_tilt)
        if metrics.face_diag is not None:
            self._calib_face_diag.append(metrics.face_diag)
        if metrics.ear_smoothed is not None:
            self._calib_ear.append(metrics.ear_smoothed)

        if elapsed >= config.CALIBRATION_DURATION_SEC:
            self._finalize_calibration()

    def _finalize_calibration(self) -> None:
        enough = len(self._calib_cva) >= config.CALIBRATION_MIN_SAMPLES
        if enough:
            self.baseline = Baseline(
                cva=float(np.mean(self._calib_cva)) if self._calib_cva else 55.0,
                shoulder_y=float(np.mean(self._calib_shoulder_y)) if self._calib_shoulder_y else 0.0,
                shoulder_tilt=float(np.mean(self._calib_shoulder_tilt)) if self._calib_shoulder_tilt else 0.0,
                face_diag=float(np.mean(self._calib_face_diag)) if self._calib_face_diag else 0.0,
                ear=float(np.mean(self._calib_ear)) if self._calib_ear else (
                    config.EAR_DEFAULT_THRESHOLD / config.EAR_DYNAMIC_THRESHOLD_RATIO
                ),
                calibrated=True,
            )
        else:
            # Not enough good samples (e.g. user stepped out of frame) --
            # extend calibration instead of locking in a bad baseline.
            self.calibration_start_time = time.time()
            return

        self.is_calibrating = False
        self.session_score = config.SESSION_SCORE_START

    # ------------------------------------------------------------------
    # Sliding-window sustained-alert logic
    # ------------------------------------------------------------------
    def _update_sustained_buffers(self, metrics: FrameMetrics, now: float) -> None:
        self.posture_buffer.append((now, metrics.is_slouching))
        self.fatigue_buffer.append((now, metrics.ocular_fatigue or metrics.prolonged_closed))

        self._trim_buffer(self.posture_buffer, now)
        self._trim_buffer(self.fatigue_buffer, now)

        metrics.sustained_slouch = self._is_sustained(self.posture_buffer)
        metrics.ocular_fatigue = metrics.ocular_fatigue or self._is_sustained(self.fatigue_buffer)

    @staticmethod
    def _trim_buffer(buf: Deque[Tuple[float, bool]], now: float) -> None:
        while buf and (now - buf[0][0]) > config.BUFFER_WINDOW_SEC:
            buf.popleft()
        while len(buf) > config.BUFFER_MAX_SAMPLES:
            buf.popleft()

    @staticmethod
    def _is_sustained(buf: Deque[Tuple[float, bool]]) -> bool:
        if not buf:
            return False
        bad_count = sum(1 for _, is_bad in buf if is_bad)
        ratio = bad_count / len(buf)
        # Require a reasonably full window before declaring "sustained"
        span = buf[-1][0] - buf[0][0]
        if span < config.BUFFER_WINDOW_SEC * 0.6:
            return False
        return ratio >= config.SUSTAINED_BAD_RATIO

    # ------------------------------------------------------------------
    # "No person in frame" handling
    # ------------------------------------------------------------------
    def _handle_no_person(self, now: float, metrics: FrameMetrics) -> None:
        metrics.warning = "No person detected - please sit in front of the camera"
        if self._last_seen_time is not None and (now - self._last_seen_time) > config.NO_PERSON_GRACE_SEC:
            # Don't let the score rot indefinitely while nobody's there;
            # simply freeze it rather than penalizing an empty chair.
            pass
        metrics.session_score = self.session_score
        metrics.is_calibrating = self.is_calibrating
        metrics.calibration_done = self.baseline.calibrated
        metrics.blink_count_total = self.blink_count_total

    # ------------------------------------------------------------------
    # Session scoring
    # ------------------------------------------------------------------
    def _update_session_score(self, metrics: FrameMetrics, dt: float) -> None:
        if dt <= 0 or dt > 1.0:
            # Guard against huge dt spikes (e.g. window was paused/minimized)
            dt = min(dt, 1.0 / config.TARGET_FPS) if dt > 0 else 0.0

        penalty = 0.0
        if metrics.sustained_slouch:
            penalty += config.SESSION_SCORE_SLOUCH_PENALTY_PER_SEC * dt
        if metrics.ocular_fatigue:
            penalty += config.SESSION_SCORE_FATIGUE_PENALTY_PER_SEC * dt

        if penalty > 0:
            self.session_score -= penalty
        else:
            self.session_score += config.SESSION_SCORE_RECOVERY_PER_SEC * dt

        self.session_score = geometry.clamp(
            self.session_score, config.SESSION_SCORE_MIN, config.SESSION_SCORE_MAX
        )
