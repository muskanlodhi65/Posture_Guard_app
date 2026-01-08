"""
config.py
---------
Centralized configuration for PostureGuard: Real-Time Edge Ergonomics &
Screen-Fatigue Analytics Platform.

All thresholds, landmark indices, buffer sizes, and smoothing constants
live here so the rest of the codebase never hardcodes a "magic number".
"""

# =========================================================================
# VIDEO / CAPTURE SETTINGS
# =========================================================================
CAMERA_INDEX = 0                 # Default webcam index (change if using an external cam)
FRAME_WIDTH = 960                # Capture width  (kept modest for >=30 FPS on CPU)
FRAME_HEIGHT = 540               # Capture height
TARGET_FPS = 30                  # Target processing FPS
FLIP_HORIZONTAL = True           # Mirror the feed for a natural "selfie" view

# =========================================================================
# MEDIAPIPE POSE LANDMARK INDICES (mediapipe.solutions.pose)
# =========================================================================
# Full body pose landmark map (only the ones we need are named below).
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_EAR = 7
RIGHT_EAR = 8

POSE_MIN_DETECTION_CONFIDENCE = 0.6
POSE_MIN_TRACKING_CONFIDENCE = 0.6
POSE_MODEL_COMPLEXITY = 1        # 0 = lite (fastest), 1 = full, 2 = heavy

# Minimum visibility score (mediapipe landmark.visibility) required to
# trust a pose landmark. Below this we treat the landmark as "occluded".
POSE_VISIBILITY_THRESHOLD = 0.5

# =========================================================================
# MEDIAPIPE FACE MESH LANDMARK INDICES (mediapipe.solutions.face_mesh)
# =========================================================================
# 6-point eye landmark sets used for the classic Eye Aspect Ratio (EAR)
# formula. Order per eye: [p1 (outer corner), p2 (upper-outer), p3 (upper-
# inner), p4 (inner corner), p5 (lower-inner), p6 (lower-outer)]
# These indices are the well-established FaceMesh landmark IDs used across
# the CV community for EAR-based blink detection.
RIGHT_EYE_EAR_IDX = [33, 160, 158, 133, 153, 144]
LEFT_EYE_EAR_IDX = [362, 385, 387, 263, 373, 380]

# Face oval indices used to build a bounding box for a "distance proxy"
# (how close the user's face is to the camera). We only need extremities.
FACE_OVAL_EXTREMES_IDX = [10, 152, 234, 454]  # top, chin, left cheek, right cheek

FACEMESH_MIN_DETECTION_CONFIDENCE = 0.6
FACEMESH_MIN_TRACKING_CONFIDENCE = 0.6
FACEMESH_REFINE_LANDMARKS = True  # needed for stable eye/iris landmarks

# =========================================================================
# TEMPORAL SMOOTHING (Exponential Moving Average)
# =========================================================================
EMA_ALPHA_CVA = 0.30       # smoothing factor for Craniovertebral Angle
EMA_ALPHA_SHOULDER = 0.30  # smoothing factor for shoulder height / tilt
EMA_ALPHA_EAR = 0.40       # smoothing factor for Eye Aspect Ratio (blinks are fast -> less smoothing)

# =========================================================================
# SLIDING WINDOW / TEMPORAL BUFFER
# =========================================================================
BUFFER_WINDOW_SEC = 5.0        # sustained-posture evaluation window
BUFFER_MAX_SAMPLES = 300       # hard cap on samples kept in the deque (safety)
SUSTAINED_BAD_RATIO = 0.70     # fraction of samples in window that must be "bad" to flag

# =========================================================================
# CALIBRATION
# =========================================================================
CALIBRATION_DURATION_SEC = 5.0   # user sits in ideal posture for this long
CALIBRATION_MIN_SAMPLES = 15     # minimum valid samples required to accept calibration

# =========================================================================
# POSTURE / SLOUCH THRESHOLDS
# =========================================================================
# CVA (Craniovertebral Angle): larger angle = more upright, smaller = more
# forward-head / slouched posture. We flag "slouching" when the *smoothed*
# current CVA drops this many degrees below the calibrated baseline.
CVA_SLOUCH_DELTA_DEG = 8.0

# Absolute fallback: if CVA ever falls below this hard floor, flag slouching
# even if baseline calibration is unusually low.
CVA_ABSOLUTE_FLOOR_DEG = 42.0

# Shoulder vertical drop: if the smoothed midpoint of the shoulders moves
# down (in normalized image coords, y grows downward) by more than this
# fraction of the calibrated face-size distance proxy, flag slumping.
SHOULDER_DROP_RATIO_THRESHOLD = 0.18

# Shoulder roll / lateral tilt: absolute difference in y between left and
# right shoulder (normalized by face distance proxy) beyond this -> uneven
# / leaning posture.
SHOULDER_TILT_RATIO_THRESHOLD = 0.12

# =========================================================================
# EYE ASPECT RATIO (EAR) / BLINK / FATIGUE THRESHOLDS
# =========================================================================
EAR_DEFAULT_THRESHOLD = 0.21          # fallback if calibration unavailable
EAR_DYNAMIC_THRESHOLD_RATIO = 0.78    # blink threshold = calibrated_baseline_EAR * this ratio
EAR_CONSEC_FRAMES_FOR_BLINK = 2       # min consecutive "closed" frames to count as a blink
EAR_PROLONGED_CLOSED_SEC = 2.0        # eyes closed longer than this -> drowsiness/fatigue flag

BLINK_RATE_WINDOW_SEC = 60.0          # rolling window for blinks-per-minute calc
LOW_BLINK_RATE_BPM_THRESHOLD = 10     # BPM below this -> ocular fatigue flag (low blink rate = staring/fatigue)
HIGH_BLINK_RATE_BPM_THRESHOLD = 30    # BPM above this -> also a fatigue/eye-strain signal (excessive blinking)

# =========================================================================
# ALERT / NOTIFICATION SETTINGS
# =========================================================================
ALERT_PERSISTENCE_SEC = 4.0     # violation must persist this long before alert fires
ALERT_DEBOUNCE_SEC = 20.0       # minimum gap between repeated alerts of the same type
ALERT_SOUND_ENABLED = True
ALERT_NOTIFICATION_ENABLED = True
ALERT_BEEP_FREQUENCY_HZ = 1000  # winsound beep frequency (Windows only)
ALERT_BEEP_DURATION_MS = 300

# =========================================================================
# SESSION SCORING
# =========================================================================
SESSION_SCORE_START = 100.0
SESSION_SCORE_SLOUCH_PENALTY_PER_SEC = 0.6
SESSION_SCORE_FATIGUE_PENALTY_PER_SEC = 0.4
SESSION_SCORE_RECOVERY_PER_SEC = 0.3   # score regen per second of good posture
SESSION_SCORE_MIN = 0.0
SESSION_SCORE_MAX = 100.0

# =========================================================================
# UI / DASHBOARD
# =========================================================================
WINDOW_NAME = "PostureGuard - Real-Time Edge Ergonomics Dashboard"
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
UI_PANEL_ALPHA = 0.55              # transparency of the overlay telemetry panel

# =========================================================================
# MISC / ROBUSTNESS
# =========================================================================
MAX_CONSECUTIVE_FRAME_FAILURES = 30   # camera read failures before we bail out
NO_PERSON_GRACE_SEC = 2.0             # how long we tolerate "no landmarks" before UI warns loudly
