"""Locale catalog loading, validation, and safe fallback to English."""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from server.config import get_settings
from server.models import LanguageOption, NoticeTypeOption

logger = logging.getLogger(__name__)

LOCALE_CODES: tuple[str, ...] = ("en", "hi", "mr", "gu", "ta", "te", "bn")
NOTICE_IDS: tuple[str, ...] = (
    "cheque_bounce",
    "rent_eviction",
    "loan_recovery",
    "consumer",
    "maintenance",
    "property",
    "employment",
    "tax",
    "generic",
)
LANGUAGE_ALIASES: dict[str, str] = {
    "en": "en",
    "en-in": "en",
    "english": "en",
    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
    "mr": "mr",
    "mr-in": "mr",
    "marathi": "mr",
    "gu": "gu",
    "gu-in": "gu",
    "gujarati": "gu",
    "ta": "ta",
    "ta-in": "ta",
    "tamil": "ta",
    "te": "te",
    "te-in": "te",
    "telugu": "te",
    "bn": "bn",
    "bn-in": "bn",
    "bengali": "bn",
}


def normalize_language(code: str | None) -> str:
    if not code:
        return "en"
    normalized = code.strip().lower().replace("_", "-")
    return LANGUAGE_ALIASES.get(normalized, "en")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively fill a translated catalog from English.

    Lists are replaced wholesale when present. This keeps translated step lists
    intact while guaranteeing that a missing key never crashes a request.
    """

    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


@dataclass(frozen=True, slots=True)
class LocaleStore:
    locales: Mapping[str, dict[str, Any]]
    languages: tuple[LanguageOption, ...]

    @classmethod
    def load(cls, data_dir: Path) -> "LocaleStore":
        raw: dict[str, dict[str, Any]] = {}
        for code in LOCALE_CODES:
            path = data_dir / "locales" / f"{code}.json"
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if not isinstance(payload, dict):
                    raise ValueError("locale root must be an object")
                raw[code] = payload
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Could not load locale %s: %s", code, exc)

        if "en" not in raw:
            raise RuntimeError(
                "The English locale catalog is missing. Restore server/data/locales/en.json."
            )

        english = raw["en"]
        locales: dict[str, dict[str, Any]] = {}
        for code in LOCALE_CODES:
            candidate = raw.get(code)
            if candidate is None:
                logger.warning("Falling back to English for locale %s", code)
                locales[code] = copy.deepcopy(english)
                continue
            merged = _deep_merge(english, candidate)
            merged["code"] = code
            locales[code] = merged
            _validate_locale(code, merged)

        languages = tuple(
            LanguageOption(
                code=code,  # type: ignore[arg-type]
                english_name=str(locales[code].get("english_name", code)),
                native_name=str(locales[code].get("native_name", code)),
                tts_lang=str(locales[code].get("tts_lang", f"{code}-IN")),
            )
            for code in LOCALE_CODES
        )
        return cls(locales=locales, languages=languages)

    def get(self, code: str | None) -> dict[str, Any]:
        return self.locales.get(normalize_language(code), self.locales["en"])

    def labels(self, code: str | None) -> dict[str, str]:
        raw = self.get(code).get("labels", {})
        return {str(key): str(value) for key, value in raw.items()}

    def notice(self, code: str | None, notice_type: str) -> dict[str, Any]:
        locale = self.get(code)
        notices = locale.get("notices", {})
        if notice_type in notices and isinstance(notices[notice_type], dict):
            return notices[notice_type]
        return locale["notices"]["generic"]

    def english_notice(self, notice_type: str) -> dict[str, Any]:
        notices = self.locales["en"].get("notices", {})
        return notices.get(notice_type, notices["generic"])

    def glossary(self, code: str | None) -> dict[str, dict[str, str]]:
        raw = self.get(code).get("glossary", {})
        result: dict[str, dict[str, str]] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[str(key)] = {
                    "term": str(value.get("term", key)),
                    "meaning": str(value.get("meaning", "")),
                }
        return result

    def notice_options(self) -> list[NoticeTypeOption]:
        options: list[NoticeTypeOption] = []
        english = self.locales["en"]["notices"]
        for notice_id in NOTICE_IDS:
            notice = english[notice_id]
            options.append(
                NoticeTypeOption(
                    id=notice_id,  # type: ignore[arg-type]
                    label=str(notice.get("label", notice_id)),
                    label_en=str(notice.get("label", notice_id)),
                    statute=str(notice.get("statute", "")),
                    severity=str(notice.get("severity", "warning")),  # type: ignore[arg-type]
                )
            )
        return options

    def tts_lang(self, code: str | None) -> str:
        return str(self.get(code).get("tts_lang", "en-IN"))


def _validate_locale(code: str, locale: dict[str, Any]) -> None:
    labels = locale.get("labels")
    notices = locale.get("notices")
    steps = locale.get("common_steps")
    if not isinstance(labels, dict):
        logger.warning("Locale %s has no labels object", code)
    if not isinstance(notices, dict):
        logger.warning("Locale %s has no notices object", code)
        return
    if not isinstance(steps, list) or len(steps) != 5:
        logger.warning("Locale %s should have exactly five common steps", code)
    for notice_id in NOTICE_IDS:
        notice = notices.get(notice_id)
        if not isinstance(notice, dict):
            logger.warning("Locale %s is missing notice type %s", code, notice_id)
            continue
        required = (
            "label",
            "statute",
            "topic",
            "allegation",
            "consequence",
            "deadline_label",
            "default_days",
            "severity",
            "extra_step_title",
            "extra_step_detail",
        )
        missing = [key for key in required if key not in notice]
        if missing:
            logger.warning(
                "Locale %s notice %s is missing keys: %s", code, notice_id, missing
            )


@lru_cache(maxsize=1)
def get_locale_store() -> LocaleStore:
    return LocaleStore.load(get_settings().data_dir)
