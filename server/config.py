"""Application configuration.

All values are read from environment variables (or a local .env file) once at
startup. Nothing here performs network access, so the app can always boot in a
fully offline demo mode.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    cleaned = raw.strip()
    return cleaned or default


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    version: str
    environment: str
    debug: bool
    host: str
    port: int
    timezone: str
    trust_proxy: bool

    base_dir: Path
    static_dir: Path
    templates_dir: Path
    data_dir: Path

    sarvam_api_key: str
    sarvam_base_url: str
    sarvam_translate_model: str
    sarvam_tts_model: str
    sarvam_stt_model: str
    sarvam_tts_speaker: str
    sarvam_translate_timeout: float
    sarvam_tts_timeout: float
    sarvam_stt_timeout: float
    sarvam_max_retries: int

    max_upload_mb: int
    max_pdf_pages: int
    max_text_chars: int
    max_tts_chars: int
    max_translate_chars: int
    max_stt_mb: int

    rate_limit_analyze: int
    rate_limit_voice: int
    rate_limit_window_seconds: int

    @property
    def sarvam_configured(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def mode(self) -> str:
        return "live" if self.sarvam_configured else "offline-demo"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_stt_bytes(self) -> int:
        return self.max_stt_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = _env_str("APP_ENV", "development").lower()
    debug_default = environment not in {"production", "prod"}
    return Settings(
        app_name="NyayaDost",
        version="1.0.0",
        environment=environment,
        debug=_env_bool("APP_DEBUG", debug_default),
        host=_env_str("APP_HOST", "127.0.0.1"),
        port=_env_int("APP_PORT", 8000, 1, 65535),
        timezone=_env_str("APP_TIMEZONE", "Asia/Kolkata"),
        trust_proxy=_env_bool("TRUST_PROXY", False),
        base_dir=BASE_DIR,
        static_dir=BASE_DIR / "static",
        templates_dir=BASE_DIR / "templates",
        data_dir=BASE_DIR / "server" / "data",
        sarvam_api_key=_env_str("SARVAM_API_KEY", ""),
        sarvam_base_url=_env_str("SARVAM_BASE_URL", "https://api.sarvam.ai").rstrip("/"),
        sarvam_translate_model=_env_str("SARVAM_TRANSLATE_MODEL", "mayura:v1"),
        sarvam_tts_model=_env_str("SARVAM_TTS_MODEL", "bulbul:v3"),
        sarvam_stt_model=_env_str("SARVAM_STT_MODEL", "saaras:v4"),
        sarvam_tts_speaker=_env_str("SARVAM_TTS_SPEAKER", "shubh"),
        sarvam_translate_timeout=_env_float("SARVAM_TRANSLATE_TIMEOUT", 15.0, 3.0, 60.0),
        sarvam_tts_timeout=_env_float("SARVAM_TTS_TIMEOUT", 25.0, 5.0, 90.0),
        sarvam_stt_timeout=_env_float("SARVAM_STT_TIMEOUT", 35.0, 5.0, 120.0),
        sarvam_max_retries=_env_int("SARVAM_MAX_RETRIES", 1, 0, 3),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 10, 1, 50),
        max_pdf_pages=_env_int("MAX_PDF_PAGES", 60, 1, 300),
        max_text_chars=_env_int("MAX_TEXT_CHARS", 50000, 1000, 200000),
        max_tts_chars=_env_int("MAX_TTS_CHARS", 900, 100, 2500),
        max_translate_chars=_env_int("MAX_TRANSLATE_CHARS", 5000, 500, 20000),
        max_stt_mb=_env_int("MAX_STT_MB", 10, 1, 50),
        rate_limit_analyze=_env_int("RATE_LIMIT_ANALYZE", 30, 1, 1000),
        rate_limit_voice=_env_int("RATE_LIMIT_VOICE", 25, 1, 1000),
        rate_limit_window_seconds=_env_int("RATE_LIMIT_WINDOW_SECONDS", 60, 10, 3600),
    )
