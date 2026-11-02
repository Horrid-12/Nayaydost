"""Strict request and response contracts for the NyayaDost API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LanguageCode = Literal["en", "hi", "mr", "gu", "ta", "te", "bn"]
NoticeTypeId = Literal[
    "cheque_bounce",
    "rent_eviction",
    "loan_recovery",
    "consumer",
    "maintenance",
    "property",
    "employment",
    "tax",
    "generic",
]
Severity = Literal["critical", "warning", "normal"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Shared response pieces
# ---------------------------------------------------------------------------


class LanguageOption(BaseModel):
    code: LanguageCode
    english_name: str
    native_name: str
    tts_lang: str


class NoticeTypeOption(BaseModel):
    id: NoticeTypeId
    label: str
    label_en: str
    statute: str
    severity: Severity


class SampleNotice(BaseModel):
    id: str
    title: str
    description: str
    notice_type: NoticeTypeId
    text: str


class SourceInfo(BaseModel):
    name: str
    kind: Literal["pdf", "text"]
    pages: int | None = None
    characters: int
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    label: str
    value: str


class Deadline(BaseModel):
    label: str
    date: str = Field(description="ISO date, YYYY-MM-DD")
    date_display: str = Field(description="Indian format DD/MM/YYYY")
    days_remaining: int
    source: Literal["stated", "estimated", "statutory"]
    source_label: str
    severity: Severity
    note: str | None = None


class Step(BaseModel):
    id: str
    title: str
    detail: str
    priority: int


class GlossaryItem(BaseModel):
    key: str
    term: str
    meaning: str


class ReplyDraft(BaseModel):
    note: str
    subject: str
    template: str


class AnalysisResponse(BaseModel):
    analysis_id: str
    notice_type: NoticeTypeId
    notice_type_label: str
    notice_type_label_en: str
    statute: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)
    language: LanguageCode
    mode: Literal["offline", "live", "hybrid"]
    provider: str
    degraded: bool = False
    warning: str | None = None
    source: SourceInfo
    original_text: str
    summary_title: str
    summary_body: str
    facts: list[Fact]
    deadlines: list[Deadline]
    steps: list[Step]
    glossary: list[GlossaryItem]
    reply: ReplyDraft
    labels: dict[str, str]
    tts_text: str
    disclaimer: str
    generated_at: str


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class AnalyzeRequest(StrictModel):
    text: str = Field(min_length=30, max_length=50000)
    language: LanguageCode = "en"
    source_name: str = Field(default="Pasted notice", max_length=200)

    @field_validator("text")
    @classmethod
    def text_must_have_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The notice text is empty")
        return value


class TranslateRequest(StrictModel):
    text: str = Field(min_length=2, max_length=5000)
    target_language: LanguageCode
    source_language: Literal[
        "auto", "en-IN", "hi-IN", "mr-IN", "gu-IN", "ta-IN", "te-IN", "bn-IN"
    ] = "en-IN"


class TTSRequest(StrictModel):
    text: str = Field(min_length=2, max_length=2500)
    language: LanguageCode
    speaker: str | None = Field(default=None, max_length=40)
    pace: float = Field(default=1.0, ge=0.5, le=2.0)


class TranslationResponse(BaseModel):
    translated_text: str
    source_language: str
    target_language: str
    provider: str
    mode: Literal["offline", "live"]
    is_mock: bool
    degraded: bool = False
    warning: str | None = None
    truncated: bool = False


class TTSResponse(BaseModel):
    audio_base64: str
    mime_type: str
    duration_seconds: float
    transcript: str
    language: str
    speaker: str
    provider: str
    mode: Literal["offline", "live"]
    is_mock: bool
    degraded: bool = False
    warning: str | None = None


class STTResponse(BaseModel):
    transcript: str
    language_code: str
    provider: str
    mode: Literal["offline", "live"]
    is_mock: bool
    degraded: bool = False
    warning: str | None = None


# ---------------------------------------------------------------------------
# Bootstrap / health
# ---------------------------------------------------------------------------


class AppLimits(BaseModel):
    max_upload_mb: int
    max_text_chars: int
    max_tts_chars: int
    max_pdf_pages: int


class BootstrapResponse(BaseModel):
    version: str
    mode: Literal["live", "offline-demo"]
    sarvam_configured: bool
    languages: list[LanguageOption]
    notice_types: list[NoticeTypeOption]
    samples: list[SampleNotice]
    limits: AppLimits
    generated_at: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    mode: Literal["live", "offline-demo"]
    sarvam_configured: bool
    locales: list[str]
    time_ist: str


# ---------------------------------------------------------------------------
# NyayaGuide
# ---------------------------------------------------------------------------


class GuideStep(BaseModel):
    number: int
    title: str
    detail: str


class GuideTimelineItem(BaseModel):
    when: str
    action: str


class GuideResponse(BaseModel):
    notice_type: NoticeTypeId
    notice_type_label: str
    title: str
    overview: str
    native_summary: str
    steps: list[GuideStep]
    documents: list[str]
    timeline: list[GuideTimelineItem]
    mistakes: list[str]
    lawyer_flags: list[str]
    reply_points: list[str]
    disclaimer: str
    language: LanguageCode


# ---------------------------------------------------------------------------
# Legal Aid Finder
# ---------------------------------------------------------------------------


class DistrictOption(BaseModel):
    name: str
    dlsa_name: str


class StateOption(BaseModel):
    name: str
    slsa_name: str
    districts: list[DistrictOption]


class LegalAidOptionsResponse(BaseModel):
    states: list[StateOption]
    helpline: str
    website: str


class LegalAidResponse(BaseModel):
    matched: bool
    state: str
    district: str
    dlsa_name: str
    address: str
    phone: str
    helpline: str
    website: str
    hours: str
    note: str
    eligibility: list[str]
    documents: list[str]
    application_steps: list[str]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None
    request_id: str | None = None
    details: dict[str, str | int | float | bool | None] | None = None


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    error: ErrorDetail
