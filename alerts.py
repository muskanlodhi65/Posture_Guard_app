"""
alerts.py
---------
Non-blocking, debounced alert dispatcher with multiple Voice Personalities
("scolding", "gentle", "cyberpunk") for posture, fatigue, screen proximity,
low-light room conditions, and 20-20-20 break reminders.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Dict, Optional

import config

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except Exception:
    pyttsx3 = None
    _PYTTSX3_AVAILABLE = False

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


# Personality message templates
PERSONALITY_PROMPTS = {
    "scolding": {
        "slouch": "Hey! Stop slouching right now! Sit up straight!",
        "fatigue": "Hey! Look at your eyes! Wake up and take a break!",
        "too_close": "Hey! Step back! You are way too close to the screen!",
        "low_light": "Hey! Turn on the lights! Your room is too dark for your eyes!",
        "break": "Time's up! Look away 20 feet for 20 seconds and stretch your neck!",
    },
    "gentle": {
        "slouch": "Gentle reminder to straighten your back and relax your shoulders.",
        "fatigue": "Your eyes seem tired. Take a deep breath and close your eyes for a moment.",
        "too_close": "Please sit back comfortably to protect your eyesight.",
        "low_light": "The room seems dim. Consider turning on a warm light.",
        "break": "It's time for a 20-second break! Look out the window and stretch gently.",
    },
    "cyberpunk": {
        "slouch": "Warning: Postural alignment degraded. Re-aligning spine protocol.",
        "fatigue": "Warning: Ocular scan indicates visual fatigue. System break recommended.",
        "too_close": "Proximity limit breached! Recalibrating distance to monitor.",
        "low_light": "Ambient light low. Ocular strain risk elevated.",
        "break": "20-20-20 protocol activated. Initiate 20-second optical reset.",
    }
}


class AlertDispatcher:
    def __init__(
        self,
        persistence_sec: float = config.ALERT_PERSISTENCE_SEC,
        debounce_sec: float = config.ALERT_DEBOUNCE_SEC,
        sound_enabled: bool = config.ALERT_SOUND_ENABLED,
        notifications_enabled: bool = config.ALERT_NOTIFICATION_ENABLED,
        personality: str = config.VOICE_PERSONALITY_MODE,
    ) -> None:
        self.persistence_sec = persistence_sec
        self.debounce_sec = debounce_sec
        self.sound_enabled = sound_enabled
        self.notifications_enabled = notifications_enabled
        self.personality = personality

        self._violation_start_time: Dict[str, Optional[float]] = {}
        self._last_fired: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._speech_lock = threading.Lock()

    def set_personality(self, personality: str) -> None:
        if personality in PERSONALITY_PROMPTS:
            self.personality = personality

    def get_prompt_text(self, key: str, detail_reason: str = "") -> str:
        base_dict = PERSONALITY_PROMPTS.get(self.personality, PERSONALITY_PROMPTS["scolding"])
        base = base_dict.get(key, "")
        if detail_reason:
            return f"{base} {detail_reason}"
        return base

    def evaluate(
        self,
        key: str,
        is_active: bool,
        title: str,
        message: str,
        voice_prompt: str = "",
        now: Optional[float] = None
    ) -> bool:
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

        final_voice_text = voice_prompt or self.get_prompt_text(key)
        self._dispatch_async(title, message, final_voice_text)
        return True

    def trigger_break_alert(self) -> None:
        text = self.get_prompt_text("break")
        self._dispatch_async(
            "PostureGuard: 20-20-20 Break Time",
            "Take 20 seconds to look 20 feet away and stretch!",
            text
        )

    # ------------------------------------------------------------------
    def _dispatch_async(self, title: str, message: str, voice_prompt: str) -> None:
        thread = threading.Thread(
            target=self._dispatch, args=(title, message, voice_prompt), daemon=True
        )
        thread.start()

    def _dispatch(self, title: str, message: str, voice_prompt: str) -> None:
        if self.notifications_enabled:
            self._send_notification(title, message)
        if self.sound_enabled:
            spoken = self._speak_warning(voice_prompt)
            if not spoken:
                self._play_beep()

    # ------------------------------------------------------------------
    def _speak_warning(self, text: str) -> bool:
        if not _PYTTSX3_AVAILABLE:
            return False

        if not self._speech_lock.acquire(blocking=False):
            return True

        try:
            engine = pyttsx3.init()
            rate = 175 if self.personality == "scolding" else (140 if self.personality == "gentle" else 160)
            engine.setProperty("rate", rate)
            engine.setProperty("volume", 1.0)
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception as e:
            print(f"[PostureGuard Voice Warning Error]: {e}")
            return False
        finally:
            self._speech_lock.release()

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
                pass
        print(f"[PostureGuard ALERT] {title}: {message}")

    def _play_beep(self) -> None:
        if _WINSOUND_AVAILABLE:
            try:
                _winsound.Beep(config.ALERT_BEEP_FREQUENCY_HZ, config.ALERT_BEEP_DURATION_MS)
                return
            except Exception:
                pass
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass
