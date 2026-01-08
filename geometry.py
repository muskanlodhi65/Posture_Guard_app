"""
geometry.py
-----------
Pure math utilities: Euclidean distances, vector/angle computations,
Craniovertebral Angle (CVA), and Eye Aspect Ratio (EAR).

No MediaPipe or OpenCV imports here on purpose -- this module is a
self-contained, unit-testable numeric layer built on NumPy.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

import numpy as np

Point2D = Tuple[float, float]


def to_np(point: Sequence[float]) -> np.ndarray:
    """Convert a 2-tuple / list into a numpy float array."""
    return np.array([point[0], point[1]], dtype=np.float64)


def euclidean_distance(p1: Sequence[float], p2: Sequence[float]) -> float:
    """Euclidean distance between two 2D points."""
    a = to_np(p1)
    b = to_np(p2)
    return float(np.linalg.norm(a - b))


def midpoint(p1: Sequence[float], p2: Sequence[float]) -> Point2D:
    """Midpoint between two 2D points."""
    a = to_np(p1)
    b = to_np(p2)
    m = (a + b) / 2.0
    return float(m[0]), float(m[1])


def vector_angle_to_horizontal(origin: Sequence[float], tip: Sequence[float]) -> float:
    """
    Angle (in degrees, 0-180) between the vector (origin -> tip) and the
    horizontal axis, measured taking image coordinates into account
    (y grows downward). A perfectly horizontal vector returns 0 deg; a
    perfectly vertical vector (tip directly above origin) returns 90 deg.
    """
    dx = tip[0] - origin[0]
    dy = origin[1] - tip[1]  # invert y so "up" is positive
    angle_rad = math.atan2(abs(dy), abs(dx) if dx != 0 else 1e-9)
    return math.degrees(angle_rad)


def calculate_cva(shoulder: Sequence[float], ear: Sequence[float]) -> float:
    """
    Craniovertebral Angle (CVA).

    Clinically, CVA is the angle formed at the C7 vertebra (approximated
    here by the shoulder landmark) between:
      (a) a horizontal reference line through C7, and
      (b) the line joining C7 to the tragus of the ear.

    A larger CVA (closer to 90 deg) indicates a more upright, neutral neck
    posture. A smaller CVA indicates forward-head posture / slouching.

    Coordinates are expected in image space (x right-positive, y
    down-positive), which is what MediaPipe returns.
    """
    dx = ear[0] - shoulder[0]
    dy = shoulder[1] - ear[1]  # invert y: "ear above shoulder" should be positive
    angle_rad = math.atan2(dy, dx if dx != 0 else 1e-9)
    angle_deg = math.degrees(angle_rad)
    # Normalize to a 0-90 style "tilt from horizontal" reading regardless
    # of whether dx came out negative (e.g. user facing the other way).
    angle_deg = abs(angle_deg)
    if angle_deg > 90:
        angle_deg = 180 - angle_deg
    return angle_deg


def eye_aspect_ratio(eye_points: Sequence[Sequence[float]]) -> float:
    """
    Compute the Eye Aspect Ratio (EAR) given 6 ordered 2D eye landmarks:
        p1: outer corner
        p2: upper-outer lid
        p3: upper-inner lid
        p4: inner corner
        p5: lower-inner lid
        p6: lower-outer lid

    EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)

    A high EAR (~0.25-0.35) indicates an open eye; EAR collapses toward 0
    as the eye closes.
    """
    if len(eye_points) != 6:
        raise ValueError(f"eye_aspect_ratio expects exactly 6 points, got {len(eye_points)}")

    p1, p2, p3, p4, p5, p6 = eye_points

    vertical_1 = euclidean_distance(p2, p6)
    vertical_2 = euclidean_distance(p3, p5)
    horizontal = euclidean_distance(p1, p4)

    if horizontal < 1e-6:
        return 0.0

    ear = (vertical_1 + vertical_2) / (2.0 * horizontal)
    return float(ear)


def bbox_from_points(points: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    """Axis-aligned bounding box (xmin, ymin, xmax, ymax) for a set of points."""
    arr = np.array(points, dtype=np.float64)
    xmin, ymin = arr.min(axis=0)
    xmax, ymax = arr.max(axis=0)
    return float(xmin), float(ymin), float(xmax), float(ymax)


def bbox_diagonal(bbox: Tuple[float, float, float, float]) -> float:
    """Diagonal length of a bounding box; used as a face-size distance proxy."""
    xmin, ymin, xmax, ymax = bbox
    return float(math.hypot(xmax - xmin, ymax - ymin))


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value into [lo, hi]."""
    return max(lo, min(hi, value))


def ema_update(previous: float | None, current: float, alpha: float) -> float:
    """
    Exponential Moving Average update.

        ema_t = alpha * current + (1 - alpha) * ema_(t-1)

    If `previous` is None (first sample), the current value seeds the EMA.
    """
    if previous is None:
        return float(current)
    return float(alpha * current + (1.0 - alpha) * previous)
