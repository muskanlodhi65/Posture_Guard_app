"""
alerts.py
---------
Non-blocking, INSTANT alert dispatcher with bilingual Voice Personalities.
Uses Windows SAPI (win32com) for zero-delay speech on Windows.
Falls back to pyttsx3 if win32com is unavailable.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Dict, Optional

import config

# ---- Windows SAPI (instant, non-blocking) ----
_SAPI_AVAILABLE = False
_sapi_speaker = None
try:
    import win32com.client
    _sapi_speaker = win32com.client.Dispatch("SAPI.SpVoice")
    _sapi_speaker.Rate = 0   # normal speed
    _sapi_speaker.Volume = 100
    _SAPI_AVAILABLE = True
except Exception:
    pass

# ---- pyttsx3 fallback ----
_PYTTSX3_AVAILABLE = False
if not _SAPI_AVAILABLE:
    try:
        import pyttsx3
        _PYTTSX3_AVAILABLE = True
    except Exception:
        pyttsx3 = None

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


# =========================================================================
# PERSONALITY MESSAGE TEMPLATES (Hindi + English)
# =========================================================================
PERSONALITY_PROMPTS = {
    "hindi_scolding": {
        "slouch": "Arey! Seedhe baitho abhi! Jhuk kar mat baitho bilkul!",
        "fatigue": "Arey! Aankhein faad ke dekh rahe ho! Abhi break lo!",
        "too_close": "Arey! Screen se peeche hato! Aankhein kharaab ho jaayengi!",
        "low_light": "Yaar! Kamre mein light on karo! Itne andheron mein kaam mat karo!",
        "break": "Bees minute ho gaye! Abhi 20 second ke liye door dekho aur gardan ghoomao!",
    },
    "scolding": {
        "slouch": "Hey! Stop slouching right now! Sit up straight immediately!",
        "fatigue": "Hey! Your eyes are strained! Take a break right now!",
        "too_close": "Hey! Move back from the screen! You are way too close!",
        "low_light": "Hey! Turn on the lights! Your room is dangerously dark!",
        "break": "20 minutes up! Look away 20 feet for 20 seconds now!",
    },
    "hindi_gentle": {
        "slouch": "Please apni peeth seedhi karein aur shoulders relax karein.",
        "fatigue": "Aapki aankhein thak gayi hain. Thoda aaram le lijiye.",
        "too_close": "Aankhon ki sehat ke liye screen se thoda peeche hakar baithein.",
        "low_light": "Kamre mein roshni kam hai. Thodi light jala lijiye please.",
        "break": "Aankhon ko aaram dene ka waqt aa gaya hai. 20 second ke liye door dekhein.",
    },
    "gentle": {
        "slouch": "A gentle reminder to sit up straight and relax your shoulders.",
        "fatigue": "Your eyes look tired. Please close them for a moment.",
        "too_close": "Please move back a little to protect your eyesight.",
        "low_light": "The room seems a little dark. Consider switching on a light.",
        "break": "Time for your 20-second eye break! Look at something far away.",
    },
    "cyberpunk": {
        "slouch": "Warning: Spinal alignment failure detected. Correct posture immediately.",
        "fatigue": "Ocular fatigue alert: Visual system overloaded. Initiating rest protocol.",
        "too_close": "Proximity breach! Screen distance critical. Recalibrate position.",
        "low_light": "Low ambient light detected. Ocular damage risk elevated.",
        "break": "20-20-20 protocol activated. Optical reset required. Look away now.",
    }
}

VALID_PERSONALITIES = list(PERSONALITY_PROMPTS.keys())


class AlertDispatcher:
    def __init__(
        self,
        persistence_sec: float = config.ALERT_PERSISTENCE_SEC,
        debounce_sec: float = config.ALERT_DEBOUNCE_SEC,
        sound_enabled: bool = config.ALERT_SOUND_ENABLED,
        notifications_enabled: bool = config.ALERT_NOTIFICATION_ENABLED,
        personality: str = "hindi_scolding",
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

        print(f"[PostureGuard] Voice engine: {'Windows SAPI (instant)' if _SAPI_AVAILABLE else 'pyttsx3 (fallback)'}")
        print(f"[PostureGuard] Active personality: {personality}")

    def set_personality(self, personality: str) -> None:
        if personality in PERSONALITY_PROMPTS:
            self.personality = personality
            print(f"[PostureGuard] Voice personality changed to: {personality}")

    def get_prompt_text(self, key: str, detail_reason: str = "") -> str:
        base_dict = PERSONALITY_PROMPTS.get(self.personality, PERSONALITY_PROMPTS["hindi_scolding"])
        return base_dict.get(key, "")

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
        self._dispatch_async("PostureGuard: Break Time!", "Take a 20-second eye break now!", text)

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
            self._speak_warning(voice_prompt)

    # ------------------------------------------------------------------
    def _speak_warning(self, text: str) -> bool:
        if not text:
            return False

        # Windows SAPI — instant, non-blocking with SVSFlagsAsync
        if _SAPI_AVAILABLE and _sapi_speaker is not None:
            if not self._speech_lock.acquire(blocking=False):
                return True
            try:
                SVSFlagsAsync = 1  # speak asynchronously — no blocking
                _sapi_speaker.Speak(text, SVSFlagsAsync)
                return True
            except Exception as e:
                print(f"[PostureGuard SAPI Error]: {e}")
                return False
            finally:
                self._speech_lock.release()

        # pyttsx3 fallback
        if _PYTTSX3_AVAILABLE:
            if not self._speech_lock.acquire(blocking=False):
                return True
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 175)
                engine.setProperty("volume", 1.0)
                engine.say(text)
                engine.runAndWait()
                return True
            except Exception as e:
                print(f"[PostureGuard Voice Error]: {e}")
                return False
            finally:
                self._speech_lock.release()

        # Beep fallback
        self._play_beep()
        return False

    def _send_notification(self, title: str, message: str) -> None:
        if _PLYER_AVAILABLE:
            try:
                _plyer_notification.notify(
                    title=title, message=message, app_name="PostureGuard", timeout=4,
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
