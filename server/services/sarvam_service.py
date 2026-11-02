"""Sarvam AI integration with honest, functional offline fallbacks.

Live endpoints used when SARVAM_API_KEY is present:
  * POST /translate          (Mayura)
  * POST /text-to-speech     (Bulbul)
  * POST /speech-to-text     (Saaras)

If the key is missing, or a live call fails, the service returns a deterministic
fallback instead of raising. The API response always says whether content is
live or a demo, so the interface never presents mock audio as real speech.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import wave
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from server.config import Settings, get_settings
from server.errors import AppError
from server.services.audio import generate_demo_wav
from server.services.localization import LocaleStore, get_locale_store, normalize_language

logger = logging.getLogger(__name__)

SARVAM_LANGUAGE_CODES: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "bn": "bn-IN",
}

# Bulbul speaker names are model-specific. Passing a v2 voice to v3 (or a
# persona ID to v2) is rejected by the API, so the service remaps the configured
# default whenever the model changes. See the Sarvam Voices guide:
# https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices
BULBUL_V2_SPEAKERS = frozenset(
    {"anushka", "manisha", "vidya", "arya", "abhilash", "karun", "hitesh"}
)
BULBUL_V3_SPEAKERS = frozenset(
    {
        "shubh",
        "aditya",
        "ritu",
        "priya",
        "neha",
        "rahul",
        "pooja",
        "rohan",
        "simran",
        "kavya",
        "amit",
        "dev",
        "ishita",
        "shreya",
        "ratan",
        "varun",
        "manan",
        "sumit",
        "roopa",
        "kabir",
        "aayan",
        "ashutosh",
        "advait",
        "anand",
        "tanya",
        "tarun",
        "sunny",
        "mani",
        "gokul",
        "vijay",
        "shruti",
        "suhani",
        "mohit",
        "kavitha",
        "rehan",
        "soham",
        "rupali",
    }
)
BULBUL_V4_DEFAULT_SPEAKER = "shubh_enhi_ads"
BULBUL_V4_SPEAKER_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+){1,4}$")

# Sarvam enforces the character limit per model. Requests above the limit are
# rejected with HTTP 422, so the service trims to the model's limit and marks
# the response as truncated.
TRANSLATE_MODEL_LIMITS: dict[str, int] = {
    "mayura:v1": 1000,
    "sarvam-translate:v1": 2000,
}
TTS_MODEL_LIMITS: dict[str, int] = {
    "bulbul:v2": 1500,
    "bulbul:v3": 2500,
    "bulbul:v4-flash": 2500,
}

MOCK_PHRASES: dict[str, dict[str, str]] = {
    "hi": {
        "legal notice": "कानूनी नोटिस",
        "notice": "नोटिस",
        "cheque": "चेक",
        "bank": "बैंक",
        "payment": "भुगतान",
        "reply": "उत्तर",
        "deadline": "समय-सीमा",
        "court": "अदालत",
        "advocate": "वकील",
        "amount": "राशि",
        "tenant": "किरायेदार",
        "landlord": "मकान मालिक",
        "loan": "ऋण",
        "consumer": "उपभोक्ता",
        "maintenance": "भरण-पोषण",
        "property": "संपत्ति",
        "salary": "वेतन",
        "tax": "कर",
        "agreement": "समझौता",
        "receipt": "रसीद",
    },
    "mr": {
        "legal notice": "कायदेशीर नोटिस",
        "notice": "नोटिस",
        "cheque": "धनादेश",
        "bank": "बँक",
        "payment": "भुगतान",
        "reply": "उत्तर",
        "deadline": "मुदत",
        "court": "न्यायालय",
        "advocate": "वकील",
        "amount": "रक्कम",
        "tenant": "भाडेकरू",
        "landlord": "घरमालक",
        "loan": "कर्ज",
        "consumer": "ग्राहक",
        "maintenance": "पोटगी",
        "property": "मालमत्ता",
        "salary": "पगार",
        "tax": "कर",
        "agreement": "करार",
        "receipt": "पावती",
    },
    "gu": {
        "legal notice": "કાનૂની નોટિસ",
        "notice": "નોટિસ",
        "cheque": "ચેક",
        "bank": "બેંક",
        "payment": "ચુકવણી",
        "reply": "જવાબ",
        "deadline": "સમયમર્યાદા",
        "court": "અદાલત",
        "advocate": "વકીલ",
        "amount": "રકમ",
        "tenant": "ભાડૂત",
        "landlord": "મકાનમાલિક",
        "loan": "લોન",
        "consumer": "ગ્રાહક",
        "maintenance": "ભરણપોષણ",
        "property": "મિલકત",
        "salary": "પગાર",
        "tax": "કર",
        "agreement": "કરાર",
        "receipt": "રસીદ",
    },
    "ta": {
        "legal notice": "சட்ட நோட்டீஸ்",
        "notice": "நோட்டீஸ்",
        "cheque": "காசோலை",
        "bank": "வங்கி",
        "payment": "பணம் செலுத்துதல்",
        "reply": "பதில்",
        "deadline": "காலக்கெடு",
        "court": "நீதிமன்றம்",
        "advocate": "வழக்கறிஞர்",
        "amount": "தொகை",
        "tenant": "வாடகைதாரர்",
        "landlord": "வீட்டு உரிமையாளர்",
        "loan": "கடன்",
        "consumer": "நுகர்வோர்",
        "maintenance": "ஜீவனாம்சம்",
        "property": "சொத்து",
        "salary": "சம்பளம்",
        "tax": "வரி",
        "agreement": "ஒப்பந்தம்",
        "receipt": "ரசீது",
    },
    "te": {
        "legal notice": "చట్టపరమైన నోటీసు",
        "notice": "నోటీసు",
        "cheque": "చెక్",
        "bank": "బ్యాంకు",
        "payment": "చెల్లింపు",
        "reply": "ప్రత్యుత్తరం",
        "deadline": "గడువు",
        "court": "కోర్టు",
        "advocate": "న్యాయవాది",
        "amount": "మొత్తం",
        "tenant": "అద్దెదారు",
        "landlord": "యజమాని",
        "loan": "రుణం",
        "consumer": "వినియోగదారు",
        "maintenance": "భరణం",
        "property": "ఆస్తి",
        "salary": "జీతం",
        "tax": "పన్ను",
        "agreement": "ఒప్పందం",
        "receipt": "రసీదు",
    },
    "bn": {
        "legal notice": "আইনি নোটিশ",
        "notice": "নোটিশ",
        "cheque": "চেক",
        "bank": "ব্যাংক",
        "payment": "পেমেন্ট",
        "reply": "উত্তর",
        "deadline": "সময়সীমা",
        "court": "আদালত",
        "advocate": "আইনজীবী",
        "amount": "টাকা",
        "tenant": "ভাড়াটিয়া",
        "landlord": "বাড়িওয়ালা",
        "loan": "ঋণ",
        "consumer": "ভোক্তা",
        "maintenance": "ভরণপোষণ",
        "property": "সম্পত্তি",
        "salary": "বেতন",
        "tax": "কর",
        "agreement": "চুক্তি",
        "receipt": "রসিদ",
    },
    "en": {},
}


@dataclass(frozen=True, slots=True)
class TranslationResult:
    text: str
    provider: str
    mode: str
    is_mock: bool
    degraded: bool = False
    warning: str | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SpeechResult:
    audio: bytes
    mime_type: str
    duration_seconds: float
    provider: str
    mode: str
    is_mock: bool
    degraded: bool = False
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    transcript: str
    language_code: str
    provider: str
    mode: str
    is_mock: bool
    degraded: bool = False
    warning: str | None = None


class SarvamService:
    def __init__(
        self,
        settings: Settings | None = None,
        locales: LocaleStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.locales = locales or get_locale_store()
        self._session = requests.Session()
        retry = Retry(
            total=self.settings.sarvam_max_retries,
            connect=self.settings.sarvam_max_retries,
            read=0,
            status=self.settings.sarvam_max_retries,
            backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str = "en-IN",
    ) -> TranslationResult:
        target = normalize_language(target_language)
        cleaned = text.strip()
        if not cleaned:
            return TranslationResult(
                text="",
                provider="none",
                mode="offline",
                is_mock=False,
                warning="There was no text to translate.",
            )

        truncated = len(cleaned) > self.settings.max_translate_chars
        if truncated:
            cleaned = cleaned[: self.settings.max_translate_chars].rstrip()

        if target == "en":
            return TranslationResult(
                text=cleaned,
                provider="passthrough",
                mode="live" if self.settings.sarvam_configured else "offline",
                is_mock=False,
                truncated=truncated,
            )

        if not self.settings.sarvam_configured:
            return self._mock_translate(cleaned, target, truncated, degraded=False)

        try:
            payload = {
                "input": cleaned,
                "source_language_code": self._sarvam_code(source_language, default="en-IN"),
                "target_language_code": SARVAM_LANGUAGE_CODES[target],
                "mode": "formal",
                "model": self.settings.sarvam_translate_model,
            }
            data = self._post_json(
                "/translate", payload, timeout=self.settings.sarvam_translate_timeout
            )
            translated = data.get("translated_text")
            if not isinstance(translated, str) or not translated.strip():
                raise ValueError("Sarvam returned no translated_text")
            return TranslationResult(
                text=translated.strip(),
                provider="sarvam-mayura",
                mode="live",
                is_mock=False,
                truncated=truncated,
            )
        except Exception as exc:
            logger.warning("Sarvam translation failed, using fallback: %s", exc)
            return self._mock_translate(
                cleaned,
                target,
                truncated,
                degraded=True,
                reason="Sarvam translation could not be reached",
            )

    def text_to_speech(
        self,
        text: str,
        language: str,
        speaker: str | None = None,
        pace: float = 1.0,
    ) -> SpeechResult:
        target = normalize_language(language)
        cleaned = text.strip()
        if not cleaned:
            cleaned = self.locales.labels(target).get("audio", "Listen to this explanation")
        truncated = len(cleaned) > self.settings.max_tts_chars
        if truncated:
            cleaned = self._cut_at_sentence(cleaned, self.settings.max_tts_chars)

        chosen_speaker = (speaker or self.settings.sarvam_tts_speaker).strip()[:40]
        safe_pace = max(0.5, min(2.0, float(pace)))

        if not self.settings.sarvam_configured:
            return self._mock_speech(
                cleaned,
                target,
                chosen_speaker,
                degraded=False,
                reason="Sarvam is not configured",
            )

        try:
            payload = {
                "inputs": [cleaned],
                "target_language_code": SARVAM_LANGUAGE_CODES[target],
                "speaker": chosen_speaker,
                "pace": safe_pace,
                "model": self.settings.sarvam_tts_model,
                "enable_preprocessing": True,
            }
            data = self._post_json(
                "/text-to-speech", payload, timeout=self.settings.sarvam_tts_timeout
            )
            raw_audio = self._extract_audio(data)
            audio_bytes = base64.b64decode(raw_audio, validate=False)
            if not audio_bytes:
                raise ValueError("Sarvam returned empty audio")
            duration = self._audio_duration(audio_bytes, cleaned)
            return SpeechResult(
                audio=audio_bytes,
                mime_type="audio/wav",
                duration_seconds=duration,
                provider="sarvam-bulbul",
                mode="live",
                is_mock=False,
            )
        except Exception as exc:
            logger.warning("Sarvam TTS failed, using demo audio: %s", exc)
            return self._mock_speech(
                cleaned,
                target,
                chosen_speaker,
                degraded=True,
                reason="Sarvam voice could not be reached",
            )

    def speech_to_text(
        self,
        audio: bytes,
        filename: str,
        content_type: str | None,
        language: str | None = None,
    ) -> TranscriptResult:
        target = normalize_language(language)
        if not audio:
            raise AppError(
                "empty_audio",
                "That recording is empty.",
                hint="Record again and speak for at least a few seconds.",
                status_code=422,
            )
        if len(audio) > self.settings.max_stt_bytes:
            raise AppError(
                "audio_too_large",
                f"That recording is larger than {self.settings.max_stt_mb} MB.",
                hint="Record a shorter message, or upload a smaller audio file.",
                status_code=413,
            )
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "dictation.webm")[:80]
        mime = (content_type or "audio/webm").split(";")[0].strip().lower()
        allowed = {
            "audio/webm",
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp3",
            "audio/mp4",
            "audio/m4a",
            "audio/ogg",
            "application/octet-stream",
        }
        if mime not in allowed:
            raise AppError(
                "unsupported_audio",
                "That audio format is not supported.",
                hint="Use a WAV, MP3, M4A, OGG, or WebM recording.",
                status_code=415,
            )

        if not self.settings.sarvam_configured:
            return self._mock_transcript(target, degraded=False)

        try:
            files = {"file": (safe_name, audio, mime)}
            form = {
                "model": self.settings.sarvam_stt_model,
                "language_code": SARVAM_LANGUAGE_CODES[target] if target != "en" else "unknown",
            }
            data = self._post_files(
                "/speech-to-text",
                files=files,
                data=form,
                timeout=self.settings.sarvam_stt_timeout,
            )
            transcript = data.get("transcript")
            if not isinstance(transcript, str) or not transcript.strip():
                raise ValueError("Sarvam returned no transcript")
            language_code = data.get("language_code")
            return TranscriptResult(
                transcript=transcript.strip(),
                language_code=str(language_code or SARVAM_LANGUAGE_CODES[target]),
                provider="sarvam-saaras",
                mode="live",
                is_mock=False,
            )
        except Exception as exc:
            logger.warning("Sarvam STT failed, using demo transcript: %s", exc)
            return self._mock_transcript(target, degraded=True)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # pragma: no cover - defensive shutdown
            pass

    # ------------------------------------------------------------------
    # Live HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "api-subscription-key": self.settings.sarvam_api_key,
            "Accept": "application/json",
        }

    def _post_json(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        url = f"{self.settings.sarvam_base_url}{path}"
        try:
            response = self._session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"network error calling {path}: {exc.__class__.__name__}") from exc
        return self._checked_json(response, path)

    def _post_files(
        self,
        path: str,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        url = f"{self.settings.sarvam_base_url}{path}"
        try:
            response = self._session.post(
                url,
                files=files,
                data=data,
                headers=self._headers(),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"network error calling {path}: {exc.__class__.__name__}") from exc
        return self._checked_json(response, path)

    @staticmethod
    def _checked_json(response: requests.Response, path: str) -> dict[str, Any]:
        if response.status_code >= 400:
            snippet = (response.text or "")[:300].replace("\n", " ")
            raise RuntimeError(f"{path} returned HTTP {response.status_code}: {snippet}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{path} returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{path} returned an unexpected JSON shape")
        return payload

    # ------------------------------------------------------------------
    # Offline fallbacks
    # ------------------------------------------------------------------

    def _mock_translate(
        self,
        text: str,
        target: str,
        truncated: bool,
        *,
        degraded: bool,
        reason: str | None = None,
    ) -> TranslationResult:
        locale = self.locales.get(target)
        labels = self.locales.labels(target)
        phrases: dict[str, str] = dict(MOCK_PHRASES.get(target, {}))
        for notice_id, notice in locale.get("notices", {}).items():
            if not isinstance(notice, dict):
                continue
            english = self.locales.english_notice(notice_id)
            english_label = str(english.get("label", "")).strip()
            native_label = str(notice.get("label", "")).strip()
            if english_label and native_label:
                phrases[english_label] = native_label

        translated = text
        replacement_count = 0
        for phrase in sorted(phrases, key=len, reverse=True):
            if not phrase:
                continue
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            translated, count = pattern.subn(phrases[phrase], translated)
            replacement_count += count

        badge = labels.get("offline_badge", "Offline demo")
        header = f"[{badge}]"
        warning = (
            "Offline phrasebook preview: key legal terms were translated, but the full "
            "sentence is not a complete Mayura translation. Add SARVAM_API_KEY for full translation."
        )
        if replacement_count == 0:
            warning = (
                "Offline preview: no known legal terms were found to translate. "
                "Add SARVAM_API_KEY for a complete Mayura translation."
            )
        if degraded:
            warning = f"{reason or 'Sarvam could not be reached'}. " + warning

        return TranslationResult(
            text=f"{header}\n{translated}",
            provider="offline-phrasebook",
            mode="offline",
            is_mock=True,
            degraded=degraded,
            warning=warning,
            truncated=truncated,
        )

    def _mock_speech(
        self,
        text: str,
        language: str,
        speaker: str,
        *,
        degraded: bool,
        reason: str,
    ) -> SpeechResult:
        audio, duration = generate_demo_wav(text, language)
        warning = (
            "Sarvam voice is not configured, so this is a soft demo tone. "
            "Use the device voice button to hear the full explanation read aloud."
        )
        if degraded:
            warning = (
                f"{reason}; using a soft demo tone instead. "
                "Use the device voice button to hear the full explanation."
            )
        return SpeechResult(
            audio=audio,
            mime_type="audio/wav",
            duration_seconds=duration,
            provider="offline-demo-tone",
            mode="offline",
            is_mock=True,
            degraded=degraded,
            warning=warning,
        )

    def _mock_transcript(self, language: str, *, degraded: bool) -> TranscriptResult:
        locale = self.locales.get(language)
        labels = self.locales.labels(language)
        notice = self.locales.notice(language, "cheque_bounce")
        summary = str(locale.get("summary_frame", "{topic}")).format(
            topic=notice.get("topic", ""),
            sender=labels.get("sender_unknown", "The sender"),
            allegation=notice.get("allegation", ""),
            date_clause=labels.get("date_clause_none", ""),
            consequence=notice.get("consequence", ""),
        )
        transcript = f"{notice.get('label', 'Legal notice')}\n\n{summary}"
        warning = (
            "Demo transcript: Sarvam Saaras is not configured, so this sample notice was "
            "inserted instead of transcribing your recording. Edit it or paste your own text."
        )
        if degraded:
            warning = (
                "Sarvam speech-to-text could not be reached, so a sample notice was inserted. "
                "Edit it or paste your own text."
            )
        return TranscriptResult(
            transcript=transcript,
            language_code=SARVAM_LANGUAGE_CODES.get(language, "en-IN"),
            provider="offline-demo-transcript",
            mode="offline",
            is_mock=True,
            degraded=degraded,
            warning=warning,
        )

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _sarvam_code(code: str, default: str = "en-IN") -> str:
        normalized = (code or "").strip().lower().replace("_", "-")
        if normalized == "auto":
            return "auto"
        if normalized in SARVAM_LANGUAGE_CODES:
            return SARVAM_LANGUAGE_CODES[normalized]
        if normalized.endswith("-in") and normalized.split("-")[0] in SARVAM_LANGUAGE_CODES:
            return normalized
        return default

    @staticmethod
    def _cut_at_sentence(text: str, limit: int) -> str:
        candidate = text[:limit]
        boundary = max(
            candidate.rfind(". "),
            candidate.rfind("। "),
            candidate.rfind("? "),
            candidate.rfind("! "),
        )
        if boundary > limit * 0.55:
            return candidate[: boundary + 1].strip()
        return candidate.strip()

    @staticmethod
    def _extract_audio(data: dict[str, Any]) -> str:
        audios = data.get("audios")
        if isinstance(audios, list) and audios:
            first = audios[0]
            if isinstance(first, str) and first.strip():
                return first
            if isinstance(first, dict):
                for key in ("audio", "audio_base64", "base64"):
                    value = first.get(key)
                    if isinstance(value, str) and value.strip():
                        return value
        for key in ("audio", "audio_base64", "base64"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        raise ValueError("Sarvam returned no audio payload")

    @staticmethod
    def _audio_duration(audio: bytes, text: str) -> float:
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                if rate > 0:
                    return round(frames / rate, 2)
        except Exception:
            pass
        return round(max(1.0, min(60.0, len(text) / 13.0)), 2)


@lru_cache(maxsize=1)
def get_sarvam_service() -> SarvamService:
    return SarvamService()
