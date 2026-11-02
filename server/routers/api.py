"""JSON API for NyayaDost.

Every route is defensive: expected failures raise :class:`AppError` with a
citizen-friendly message, while unexpected failures are logged with the request
ID and converted by the application-level handlers in ``server.main``.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, cast

from fastapi import APIRouter, File, Form, Query, Request, UploadFile

from server.config import get_settings
from server.errors import AppError, DocumentError, RateLimitError
from server.models import (
    AnalysisResponse,
    AnalyzeRequest,
    AppLimits,
    BootstrapResponse,
    GuideResponse,
    HealthResponse,
    LanguageOption,
    LegalAidOptionsResponse,
    LegalAidResponse,
    NoticeTypeOption,
    STTResponse,
    TTSRequest,
    TTSResponse,
    TranslateRequest,
    TranslationResponse,
)
from server.services.content import (
    find_legal_aid,
    get_guide,
    get_legal_aid_options,
    get_samples,
)
from server.services.document_parser import parse_pdf_bytes, sanitize_filename
from server.services.localization import (
    LANGUAGE_ALIASES,
    NOTICE_IDS,
    get_locale_store,
    normalize_language,
)
from server.services.ratelimit import client_identifier, get_rate_limiter
from server.services.sarvam_service import get_sarvam_service
from server.services.simplifier import analyze_notice, now_ist_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["api"])

_ALLOWED_PDF_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
    "binary/octet-stream",
}


def _enforce_rate_limit(request: Request, category: str, limit: int) -> None:
    settings = get_settings()
    key = f"{category}:{client_identifier(request)}"
    result = get_rate_limiter().check(
        key, limit, settings.rate_limit_window_seconds
    )
    if not result.allowed:
        raise RateLimitError(result.retry_after)


def _resolve_language(raw: str, field: str = "language") -> str:
    cleaned = (raw or "").strip().lower().replace("_", "-")
    if cleaned not in LANGUAGE_ALIASES:
        raise AppError(
            "unsupported_language",
            "That language is not available yet.",
            hint="Choose English, Hindi, Marathi, Gujarati, Tamil, Telugu, or Bengali.",
            status_code=422,
            details={"field": field},
        )
    return normalize_language(cleaned)


# ---------------------------------------------------------------------------
# Bootstrap and health
# ---------------------------------------------------------------------------


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(language: str = Query(default="en", max_length=20)) -> BootstrapResponse:
    settings = get_settings()
    store = get_locale_store()
    code = _resolve_language(language)
    options: list[NoticeTypeOption] = []
    for notice_id in NOTICE_IDS:
        english = store.english_notice(notice_id)
        localized = store.notice(code, notice_id)
        options.append(
            NoticeTypeOption(
                id=cast(Any, notice_id),
                label=str(localized.get("label", english.get("label", notice_id))),
                label_en=str(english.get("label", notice_id)),
                statute=str(english.get("statute", "")),
                severity=cast(Any, english.get("severity", "warning")),
            )
        )

    return BootstrapResponse(
        version=settings.version,
        mode=cast(Any, settings.mode),
        sarvam_configured=settings.sarvam_configured,
        languages=[LanguageOption(**language.model_dump()) for language in store.languages],
        notice_types=options,
        samples=get_samples(),
        limits=AppLimits(
            max_upload_mb=settings.max_upload_mb,
            max_text_chars=settings.max_text_chars,
            max_tts_chars=settings.max_tts_chars,
            max_pdf_pages=settings.max_pdf_pages,
        ),
        generated_at=now_ist_iso(),
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    store = get_locale_store()
    return HealthResponse(
        status="ok",
        version=settings.version,
        mode=cast(Any, settings.mode),
        sarvam_configured=settings.sarvam_configured,
        locales=sorted(store.locales.keys()),
        time_ist=now_ist_iso(),
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(payload: AnalyzeRequest, request: Request) -> AnalysisResponse:
    settings = get_settings()
    _enforce_rate_limit(request, "analyze", settings.rate_limit_analyze)
    return analyze_notice(
        text=payload.text,
        language=payload.language,
        source_name=payload.source_name,
        source_kind="text",
    )


@router.post("/analyze/upload", response_model=AnalysisResponse)
async def analyze_upload(
    request: Request,
    file: UploadFile = File(...),
    language: str = Form(default="en"),
) -> AnalysisResponse:
    settings = get_settings()
    _enforce_rate_limit(request, "analyze", settings.rate_limit_analyze)
    code = _resolve_language(language)
    display_name = sanitize_filename(file.filename)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_PDF_TYPES:
        raise DocumentError(
            "unsupported_file",
            "That file type is not supported for upload.",
            hint="Upload a PDF, or paste the notice text in the text tab.",
        )

    try:
        data = await file.read(settings.max_upload_bytes + 1)
    except Exception as exc:
        logger.warning("Could not read uploaded file %s: %s", display_name, exc)
        raise DocumentError(
            "upload_read_failed",
            "We could not read that upload.",
            hint="Try again, or paste the notice text instead.",
        ) from exc
    finally:
        try:
            await file.close()
        except Exception:  # pragma: no cover - defensive cleanup
            pass

    if len(data) > settings.max_upload_bytes:
        raise DocumentError(
            "pdf_too_large",
            f"That PDF is larger than {settings.max_upload_mb} MB.",
            hint="Upload a smaller PDF, or paste only the notice text.",
            status_code=413,
        )

    parsed = parse_pdf_bytes(data, display_name)
    return analyze_notice(
        text=parsed.text,
        language=code,
        source_name=display_name,
        source_kind="pdf",
        pages=parsed.pages,
        truncated=parsed.truncated,
        warnings=parsed.warnings,
    )


# ---------------------------------------------------------------------------
# Sarvam-backed voice and translation
# ---------------------------------------------------------------------------


@router.post("/translate", response_model=TranslationResponse)
def translate(payload: TranslateRequest, request: Request) -> TranslationResponse:
    settings = get_settings()
    _enforce_rate_limit(request, "voice", settings.rate_limit_voice)
    result = get_sarvam_service().translate(
        payload.text,
        payload.target_language,
        payload.source_language,
    )
    return TranslationResponse(
        translated_text=result.text,
        source_language=payload.source_language,
        target_language=payload.target_language,
        provider=result.provider,
        mode=cast(Any, result.mode),
        is_mock=result.is_mock,
        degraded=result.degraded,
        warning=result.warning,
        truncated=result.truncated,
    )


@router.post("/tts", response_model=TTSResponse)
def text_to_speech(payload: TTSRequest, request: Request) -> TTSResponse:
    settings = get_settings()
    _enforce_rate_limit(request, "voice", settings.rate_limit_voice)
    result = get_sarvam_service().text_to_speech(
        payload.text,
        payload.language,
        payload.speaker,
        payload.pace,
    )
    transcript = payload.text.strip()
    if len(transcript) > settings.max_tts_chars:
        transcript = transcript[: settings.max_tts_chars].rstrip()
    return TTSResponse(
        audio_base64=base64.b64encode(result.audio).decode("ascii"),
        mime_type=result.mime_type,
        duration_seconds=result.duration_seconds,
        transcript=transcript,
        language=payload.language,
        speaker=(payload.speaker or settings.sarvam_tts_speaker),
        provider=result.provider,
        mode=cast(Any, result.mode),
        is_mock=result.is_mock,
        degraded=result.degraded,
        warning=result.warning,
    )


@router.post("/stt", response_model=STTResponse)
async def speech_to_text(
    request: Request,
    file: UploadFile = File(...),
    language: str = Form(default="en"),
) -> STTResponse:
    settings = get_settings()
    _enforce_rate_limit(request, "voice", settings.rate_limit_voice)
    code = _resolve_language(language)
    try:
        audio = await file.read(settings.max_stt_bytes + 1)
    except Exception as exc:
        logger.warning("Could not read uploaded audio: %s", exc)
        raise AppError(
            "audio_read_failed",
            "We could not read that recording.",
            hint="Try recording again, or upload a smaller audio file.",
            status_code=422,
        ) from exc
    finally:
        try:
            await file.close()
        except Exception:  # pragma: no cover - defensive cleanup
            pass

    if len(audio) > settings.max_stt_bytes:
        raise AppError(
            "audio_too_large",
            f"That recording is larger than {settings.max_stt_mb} MB.",
            hint="Record a shorter message, or upload a smaller audio file.",
            status_code=413,
        )

    result = get_sarvam_service().speech_to_text(
        audio,
        sanitize_filename(file.filename or "dictation.webm"),
        file.content_type,
        code,
    )
    return STTResponse(
        transcript=result.transcript,
        language_code=result.language_code,
        provider=result.provider,
        mode=cast(Any, result.mode),
        is_mock=result.is_mock,
        degraded=result.degraded,
        warning=result.warning,
    )


# ---------------------------------------------------------------------------
# NyayaGuide and legal aid
# ---------------------------------------------------------------------------


@router.get("/guide/{notice_type}", response_model=GuideResponse)
def guide(
    notice_type: str,
    language: str = Query(default="en", max_length=20),
) -> GuideResponse:
    if notice_type not in NOTICE_IDS:
        raise AppError(
            "guide_not_found",
            "That guide is not available.",
            hint="Choose a notice type from the list and try again.",
            status_code=404,
        )
    return get_guide(notice_type, _resolve_language(language))


@router.get("/legal-aid/options", response_model=LegalAidOptionsResponse)
def legal_aid_options() -> LegalAidOptionsResponse:
    return get_legal_aid_options()


@router.get("/legal-aid", response_model=LegalAidResponse)
def legal_aid(
    state: str = Query(min_length=2, max_length=80),
    district: str = Query(min_length=2, max_length=80),
) -> LegalAidResponse:
    return find_legal_aid(state, district)
