"""
alerts.py
---------
Studio-Quality HD Sound Dispatcher (44.1kHz 16-bit Stereo) with Pure Devanagari Hindi Speech.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from typing import Dict, Optional

import config

# --- Primary Voice Engine: gTTS + Pygame HD Audio ---
_GTTS_AVAILABLE = False
try:
    from gtts import gTTS
    import pygame
    # Studio Quality Audio Setup: 44.1kHz, 16-bit, Stereo, clean buffer
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    _GTTS_AVAILABLE = True
except Exception:
    _GTTS_AVAILABLE = False

# ---- Windows SAPI (Offline fallback) ----
_SAPI_AVAILABLE = False
_sapi_speaker = None
_indian_voice = None

try:
    import win32com.client
    _sapi_speaker = win32com.client.Dispatch("SAPI.SpVoice")
    _sapi_speaker.Rate = 1
    _sapi_speaker.Volume = 100
    for i, voice in enumerate(_sapi_speaker.GetVoices()):
        desc = voice.GetDescription()
        if "Ravi" in desc or "Heera" in desc or "India" in desc:
            _indian_voice = voice
            break
    _SAPI_AVAILABLE = True
except Exception:
    pass

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
# CORRECT DEVANAGARI HINDI TEMPLATES FOR HD CLEAR PRONUNCIATION
# =========================================================================
PERSONALITY_PROMPTS = {
    "angry_hindi": {
        "slouch": "{name}! क्या कर रहे हो! पूरे टाइम झुक कर क्यों बैठे हो! सीधे बैठो अभी!",
        "fatigue": "{name}! आँखें ख़राब करोगे क्या अपनी! तुरंत काम बंद करो और ब्रेक लो!",
        "too_close": "{name}! अरे! स्क्रीन में घुस जाओगे क्या! पीछे हटो तुरंत!",
        "low_light": "{name}! अँधेरे में क्यों बैठे हो! कमरे की लाइट ऑन करो अभी!",
        "break": "{name}! बीस मिनट पूरे हो गए हैं! अभी बीस सेकंड के लिए दूर देखो, गर्दन घुमाओ, और पानी पियो!",
        "_lang": "hi",
        "_tld": "co.in"
    },
    "angry_english": {
        "slouch": "Hey {name}! What are you doing! Stop slouching right now! Sit up straight!",
        "fatigue": "Hey {name}! Are you trying to ruin your eyes! Take a break immediately!",
        "too_close": "Hey {name}! Step back right now! You are way too close to the screen!",
        "low_light": "Hey {name}! Turn on the lights immediately! It is dangerously dark in here!",
        "break": "Hey {name}! Time is up! Get up right now, look away for 20 seconds, and drink some water!",
        "_lang": "en",
        "_tld": "co.in"
    },
    "hindi_scolding": {
        "slouch": "{name}! सीधे बैठो अभी! झुक कर बैठना बंद करो!",
        "fatigue": "{name}! तुम्हारी आँखें थक चुकी हैं! तुरंत काम बंद करो और ब्रेक लो!",
        "too_close": "{name}! पीछे हटो तुरंत! स्क्रीन के बहुत पास बैठे हो!",
        "low_light": "{name}! लाइट ऑन करो अभी! इतने अँधेरे में मत बैठो!",
        "break": "{name}! बीस मिनट हो गए! अभी बीस सेकंड के लिए दूर देखो, गर्दन घुमाओ, और पानी पियो!",
        "_lang": "hi",
        "_tld": "co.in"
    },
    "scolding": {
        "slouch": "Hey {name}! Stop slouching right now! Sit up straight immediately!",
        "fatigue": "Hey {name}! Your eyes are exhausted! Stop working and take a break right now!",
        "too_close": "Hey {name}! Step back immediately! You are way too close to the screen!",
        "low_light": "Hey {name}! Turn on the lights right now! It is too dark in here!",
        "break": "Time is up {name}! Look away for 20 seconds, stretch your body, and drink water now!",
        "_lang": "en",
        "_tld": "co.in"
    },
    "hindi_gentle": {
        "slouch": "{name}, कृपया अपनी पीठ सीधी करें और शोल्डर्स रिलैक्स करें।",
        "fatigue": "{name}, आपकी आँखें थक गई हैं। थोड़ा आराम ले लीजिए।",
        "too_close": "{name}, आँखों की सेहत के लिए स्क्रीन से थोड़ा पीछे हटकर बैठें।",
        "low_light": "{name}, कमरे में रोशनी कम है। थोड़ी लाइट जला लीजिए।",
        "break": "{name}, आँखों को आराम देने का वक़्त आ गया है। बीस सेकंड के लिए दूर देखें और थोड़ा पानी पी लें।",
        "_lang": "hi",
        "_tld": "co.in"
    },
    "gentle": {
        "slouch": "A gentle reminder for {name} to sit up straight and relax your shoulders.",
        "fatigue": "Your eyes look tired {name}. Please close them for a moment.",
        "too_close": "Please move back a little {name} to protect your eyesight.",
        "low_light": "{name}, the room seems a little dark. Consider switching on a light.",
        "break": "Time for your 20-second eye break {name}! Look far away, stretch gently, and drink a glass of water.",
        "_lang": "en",
        "_tld": "co.in"
    },
    "cyberpunk": {
        "slouch": "WARNING USER {name}: Spinal alignment failure detected. Correct posture immediately!",
        "fatigue": "OCULAR FATIGUE ALERT FOR {name}: Visual system overloaded. Initiating rest protocol!",
        "too_close": "PROXIMITY BREACH {name}! Screen distance critical. Recalibrate position!",
        "low_light": "LOW LIGHT WARNING {name}: Ocular damage risk elevated. Increase lighting!",
        "break": "20-20-20 PROTOCOL ACTIVATED FOR {name}! Look away now and hydrate!",
        "_lang": "en",
        "_tld": "com"
    }
}


class AlertDispatcher:
    def __init__(
        self,
        persistence_sec: float = config.ALERT_PERSISTENCE_SEC,
        debounce_sec: float = config.ALERT_DEBOUNCE_SEC,
        sound_enabled: bool = config.ALERT_SOUND_ENABLED,
        notifications_enabled: bool = config.ALERT_NOTIFICATION_ENABLED,
        personality: str = "angry_hindi",
        user_name: str = config.USER_NAME,
    ) -> None:
        self.persistence_sec = persistence_sec
        self.debounce_sec = debounce_sec
        self.sound_enabled = sound_enabled
        self.notifications_enabled = notifications_enabled
        self.personality = personality
        self.user_name = user_name

        self._violation_start_time: Dict[str, Optional[float]] = {}
        self._last_fired: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._speech_lock = threading.Lock()
        self._audio_cache: Dict[str, str] = {}

        print(f"[PostureGuard] Personalized Voice Engine Active for: '{user_name}'")
        print(f"[PostureGuard] Primary Voice Engine: {'gTTS (Studio Quality HD 44.1kHz)' if _GTTS_AVAILABLE else 'Windows SAPI'}")

    def set_user_name(self, name: str) -> None:
        name_clean = name.strip()
        if name_clean:
            self.user_name = name_clean
            print(f"[PostureGuard] User Name Updated to: '{self.user_name}'")

    def set_personality(self, personality: str) -> None:
        if personality in PERSONALITY_PROMPTS:
            self.personality = personality
            print(f"[PostureGuard] Voice Personality Changed to: {personality}")

    def get_prompt_text(self, key: str, detail_reason: str = "") -> str:
        base_dict = PERSONALITY_PROMPTS.get(self.personality, PERSONALITY_PROMPTS["angry_hindi"])
        template = base_dict.get(key, "")
        return template.format(name=self.user_name)

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
        self._dispatch_async("PostureGuard: Break & Water Time!", f"{self.user_name}, take a 20s break & drink water!", text)

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

        if not self._speech_lock.acquire(blocking=False):
            return True

        try:
            p_config = PERSONALITY_PROMPTS.get(self.personality, PERSONALITY_PROMPTS["angry_hindi"])
            lang = p_config.get("_lang", "hi")
            tld = p_config.get("_tld", "co.in")

            # 1. Primary: gTTS + Pygame HD (Studio 44.1kHz)
            if _GTTS_AVAILABLE:
                try:
                    cache_key = f"{self.user_name}_{self.personality}_{text}"
                    if cache_key in self._audio_cache and os.path.exists(self._audio_cache[cache_key]):
                        file_path = self._audio_cache[cache_key]
                    else:
                        tts = gTTS(text=text, lang=lang, tld=tld, slow=False)
                        fd, file_path = tempfile.mkstemp(suffix=".mp3")
                        os.close(fd)
                        tts.save(file_path)
                        self._audio_cache[cache_key] = file_path

                    pygame.mixer.music.set_volume(1.0)
                    pygame.mixer.music.load(file_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.04)
                    return True
                except Exception as e:
                    print(f"[gTTS Voice Error]: {e}, falling back to SAPI...")

            # 2. Offline Fallback: SAPI
            if _SAPI_AVAILABLE and _sapi_speaker is not None:
                import win32com.client
                import pythoncom
                pythoncom.CoInitialize()
                try:
                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    speaker.Rate = 1
                    speaker.Volume = 100
                    if _indian_voice is not None:
                        speaker.Voice = _indian_voice
                    speaker.Speak(text)
                    return True
                finally:
                    pythoncom.CoUninitialize()

            self._play_beep()
            return False
        except Exception as e:
            print(f"[PostureGuard Voice Error]: {e}")
            return False
        finally:
            self._speech_lock.release()

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
        try:
            import winsound
            winsound.Beep(config.ALERT_BEEP_FREQUENCY_HZ, config.ALERT_BEEP_DURATION_MS)
        except Exception:
            try:
                sys.stdout.write("\a")
                sys.stdout.flush()
            except Exception:
                pass
