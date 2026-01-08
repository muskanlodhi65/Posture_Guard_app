"""
alerts.py
---------
Non-blocking, debounced alert dispatcher for posture and fatigue
violations. Tries desktop notifications via `plyer` first, falls back to
`winsound` on Windows, and finally to the terminal bell / console print
so the app never crashes or blocks just because a notification backend
is unavailable.

All dispatch calls are debounced per alert-type so the user isn't spammed
every frame while a violation persists.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Dict, Optional

import config

# --- Optional backends (all imported defensively) -----------------------
try:
    from plyer import notification as _plyer_notification
    _PLYER_AVAILABLE = True
except Exception:
    _plyer_notification = None
    _PLYER_AVAILABLE = False

try:
    import winsound as _winsound
    _WINSOUND_AVAILABLE = sys.platform.startswith("win")
except Exception:
    _winsound = None
    _WINSOUND_AVAILABLE = False


class AlertDispatcher:
    """
    Tracks, per alert-type key, how long a violation has persisted and
    when it was last fired, then dispatches audio + desktop notifications
    without blocking the main video loop (dispatch runs in a daemon
    thread).
    """

    def __init__(
        self,
        persistence_sec: float = config.ALERT_PERSISTENCE_SEC,
        debounce_sec: float = config.ALERT_DEBOUNCE_SEC,
        sound_enabled: bool = config.ALERT_SOUND_ENABLED,
        notifications_enabled: bool = config.ALERT_NOTIFICATION_ENABLED,
    ) -> None:
        self.persistence_sec = persistence_sec
        self.debounce_sec = debounce_sec
        self.sound_enabled = sound_enabled
        self.notifications_enabled = notifications_enabled

        # violation_start_time[key] -> timestamp the violation condition
        # first became True (reset to None the moment it clears)
        self._violation_start_time: Dict[str, Optional[float]] = {}
        # last_fired[key] -> timestamp the alert last actually fired
        self._last_fired: Dict[str, float] = {}
        self._lock = threading.Lock()

    def evaluate(self, key: str, is_active: bool, title: str, message: str, now: Optional[float] = None) -> bool:
        """
        Call once per frame per alert-type (e.g. "slouch", "fatigue").
        Returns True if an alert was fired this call.

        `is_active` should be the *sustained* violation flag (already
        debounced by the temporal buffer in tracker.py) -- this class adds
        a second layer: minimum persistence before first fire, and a
        cooldown between repeat fires.
        """
        now = now if now is not None else time.time()

        with self._lock:
            if not is_active:
                self._violation_start_time[key] = None
                return False

            start = self._violation_start_time.get(key)
            if start is None:
                self._violation_start_time[key] = now
                return False

            persisted_for = now - start
            if persisted_for < self.persistence_sec:
                return False

            last_fired = self._last_fired.get(key, 0.0)
            if (now - last_fired) < self.debounce_sec:
                return False

            self._last_fired[key] = now

        self._dispatch_async(title, message)
        return True

    # ------------------------------------------------------------------
    def _dispatch_async(self, title: str, message: str) -> None:
        thread = threading.Thread(
            target=self._dispatch, args=(title, message), daemon=True
        )
        thread.start()

    def _dispatch(self, title: str, message: str) -> None:
        if self.notifications_enabled:
            self._send_notification(title, message)
        if self.sound_enabled:
            self._play_beep()

    # ------------------------------------------------------------------
    def _send_notification(self, title: str, message: str) -> None:
        if _PLYER_AVAILABLE:
            try:
                _plyer_notification.notify(
                    title=title,
                    message=message,
                    app_name="PostureGuard",
                    timeout=5,
                )
                return
            except Exception:
                pass  # fall through to console
        # Fallback: print to console so the alert is never silently lost.
        print(f"[PostureGuard ALERT] {title}: {message}")

    def _play_beep(self) -> None:
        if _WINSOUND_AVAILABLE:
            try:
                _winsound.Beep(config.ALERT_BEEP_FREQUENCY_HZ, config.ALERT_BEEP_DURATION_MS)
                return
            except Exception:
                pass
        # Cross-platform fallback: terminal bell character.
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass
