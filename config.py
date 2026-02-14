"""
config.py
---------
Centralized configuration for PostureGuard: Real-Time Edge Ergonomics &
Screen-Fatigue Analytics Platform.

All thresholds, landmark indices, buffer sizes, voice modes, and feature toggles live here.
"""

# =========================================================================
# VIDEO / CAPTURE SETTINGS
# =========================================================================
CAMERA_INDEX = 0                 # Default webcam index
FRAME_WIDTH = 960                # Capture width
FRAME_HEIGHT = 540               # Capture height
TARGET_FPS = 30                  # Target processing FPS
FLIP_HORIZONTAL = True           # Mirror the feed for a natural view

# =========================================================================
# MEDIAPIPE POSE & FACE LANDMARK INDICES
# =========================================================================
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_EAR = 7
RIGHT_EAR = 8

POSE_MIN_DETECTION_CONFIDENCE = 0.6
POSE_MIN_TRACKING_CONFIDENCE = 0.6
POSE_MODEL_COMPLEXITY = 1
POSE_VISIBILITY_THRESHOLD = 0.5

RIGHT_EYE_EAR_IDX = [33, 160, 158, 133, 153, 144]
LEFT_EYE_EAR_IDX = [362, 385, 387, 263, 373, 380]
FACE_OVAL_EXTREMES_IDX = [10, 152, 234, 454]  # top, chin, left cheek, right cheek

FACEMESH_MIN_DETECTION_CONFIDENCE = 0.6
FACEMESH_MIN_TRACKING_CONFIDENCE = 0.6
FACEMESH_REFINE_LANDMARKS = True

# =========================================================================
# TEMPORAL SMOOTHING (Exponential Moving Average)
# =========================================================================
EMA_ALPHA_CVA = 0.30       # smoothing factor for Craniovertebral Angle
EMA_ALPHA_SHOULDER = 0.30  # smoothing factor for shoulder height / tilt
EMA_ALPHA_EAR = 0.40       # smoothing factor for Eye Aspect Ratio

# =========================================================================
# SLIDING WINDOW / TEMPORAL BUFFER
# =========================================================================
BUFFER_WINDOW_SEC = 5.0        # sustained-posture evaluation window
BUFFER_MAX_SAMPLES = 300       # hard cap on samples kept in deque
SUSTAINED_BAD_RATIO = 0.70     # fraction of samples in window that must be "bad"

# =========================================================================
# CALIBRATION
# =========================================================================
CALIBRATION_DURATION_SEC = 5.0   # calibration duration in seconds
CALIBRATION_MIN_SAMPLES = 15     # minimum valid samples required

# =========================================================================
# POSTURE / SLOUCH THRESHOLDS
# =========================================================================
CVA_SLOUCH_DELTA_DEG = 8.0
CVA_ABSOLUTE_FLOOR_DEG = 42.0
SHOULDER_DROP_RATIO_THRESHOLD = 0.18
SHOULDER_TILT_RATIO_THRESHOLD = 0.12

# Face Distance (Too close to screen threshold)
FACE_TOO_CLOSE_RATIO = 1.45       # face_diag > calibrated_face_diag * 1.45 -> too close

# Low-Light Detection Threshold
LOW_LIGHT_LUMINANCE_THRESHOLD = 45.0  # Average grayscale brightness below this -> low light

# 20-20-20 Rule Timer
BREAK_REMINDER_INTERVAL_SEC = 1200.0   # 20 minutes (20 * 60)
BREAK_STRETCH_DURATION_SEC = 20.0      # 20 seconds stretch break

# =========================================================================
# EYE ASPECT RATIO (EAR) / BLINK / FATIGUE THRESHOLDS
# =========================================================================
EAR_DEFAULT_THRESHOLD = 0.21
EAR_DYNAMIC_THRESHOLD_RATIO = 0.78
EAR_CONSEC_FRAMES_FOR_BLINK = 2
EAR_PROLONGED_CLOSED_SEC = 2.0

BLINK_RATE_WINDOW_SEC = 60.0
LOW_BLINK_RATE_BPM_THRESHOLD = 10
HIGH_BLINK_RATE_BPM_THRESHOLD = 30

# =========================================================================
# ALERT / VOICE PERSONALITY MODES
# =========================================================================
# Available voice personalities: "scolding", "gentle", "cyberpunk"
VOICE_PERSONALITY_MODE = "scolding"

ALERT_PERSISTENCE_SEC = 4.0
ALERT_DEBOUNCE_SEC = 15.0
ALERT_SOUND_ENABLED = True
ALERT_NOTIFICATION_ENABLED = True
ALERT_BEEP_FREQUENCY_HZ = 1000
ALERT_BEEP_DURATION_MS = 300

# =========================================================================
# SESSION SCORING & ANALYTICS
# =========================================================================
SESSION_SCORE_START = 100.0
SESSION_SCORE_SLOUCH_PENALTY_PER_SEC = 0.6
SESSION_SCORE_FATIGUE_PENALTY_PER_SEC = 0.4
SESSION_SCORE_RECOVERY_PER_SEC = 0.3
SESSION_SCORE_MIN = 0.0
SESSION_SCORE_MAX = 100.0

WEB_SERVER_PORT = 5000

# =========================================================================
# UI / DASHBOARD
# =========================================================================
WINDOW_NAME = "PostureGuard Pro - Ergonomics & Analytics"
COLOR_GOOD = (60, 200, 60)        # BGR green
COLOR_BAD = (40, 40, 230)         # BGR red
COLOR_WARN = (0, 200, 255)        # BGR amber
COLOR_TEXT = (245, 245, 245)      # near-white
COLOR_PANEL_BG = (30, 30, 30)     # dark panel background
COLOR_ACCENT = (255, 180, 40)     # BGR light blue-ish accent
FONT_SCALE_LABEL = 0.55
FONT_SCALE_VALUE = 0.65
FONT_SCALE_TITLE = 0.8
FONT_THICKNESS = 1
UI_PANEL_ALPHA = 0.55

# =========================================================================
# MISC / ROBUSTNESS
# =========================================================================
MAX_CONSECUTIVE_FRAME_FAILURES = 30
NO_PERSON_GRACE_SEC = 2.0
