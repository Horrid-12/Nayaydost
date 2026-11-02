"""Curated demo content: sample notices, NyayaGuide articles, and legal aid.

The JSON files live under ``server/data`` and are loaded once per process. Every
loader validates the shape it needs and degrades to a small, honest fallback
rather than crashing a request. Sample notice dates are rendered relative to
today so the demo always has a live-looking deadline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from server.config import get_settings
from server.models import (
    DistrictOption,
    GuideResponse,
    GuideStep,
    GuideTimelineItem,
    LegalAidOptionsResponse,
    LegalAidResponse,
    SampleNotice,
    StateOption,
)
from server.services.localization import LocaleStore, get_locale_store, normalize_language
from server.services.simplifier import format_indian_date, today_ist

logger = logging.getLogger(__name__)

_DATE_TOKEN = re.compile(r"\{\{\s*(today|days_ago|days_ahead)\s*(?::\s*(\d{1,5})\s*)?\}\}")
MAX_SAMPLES = 12


@dataclass(frozen=True, slots=True)
class GuideArticle:
    notice_type: str
    title: str
    overview: str
    steps: tuple[tuple[str, str], ...]
    documents: tuple[str, ...]
    timeline: tuple[tuple[str, str], ...]
    mistakes: tuple[str, ...]
    lawyer_flags: tuple[str, ...]
    reply_points: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LegalAidDirectory:
    helpline: str
    website: str
    note: str
    states: dict[str, tuple[str, ...]]


def _safe_format(template: str, values: dict[str, str]) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        result = template
        for key, value in values.items():
            result = result.replace("{" + key + "}", value)
        return result


def render_date_tokens(text: str) -> str:
    today = today_ist()

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1)
        amount = int(match.group(2) or 0)
        if kind == "days_ago":
            return format_indian_date(today - timedelta(days=amount))
        if kind == "days_ahead":
            return format_indian_date(today + timedelta(days=amount))
        return format_indian_date(today)

    return _DATE_TOKEN.sub(replace, text)


@lru_cache(maxsize=1)
def _load_samples() -> tuple[SampleNotice, ...]:
    path = get_settings().data_dir / "samples.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Could not load sample notices: %s", exc)
        return ()
    if not isinstance(raw, list):
        logger.error("samples.json must contain a list")
        return ()

    samples: list[SampleNotice] = []
    for index, item in enumerate(raw[:MAX_SAMPLES]):
        if not isinstance(item, dict):
            continue
        try:
            samples.append(
                SampleNotice(
                    id=str(item.get("id") or f"sample-{index + 1}"),
                    title=str(item.get("title") or "Sample notice"),
                    description=str(item.get("description") or ""),
                    notice_type=cast(Any, str(item.get("notice_type") or "generic")),
                    text=render_date_tokens(str(item.get("text") or "")),
                )
            )
        except Exception as exc:  # pragma: no cover - validation guard
            logger.warning("Skipping malformed sample %s: %s", index, exc)
    return tuple(samples)


def get_samples() -> list[SampleNotice]:
    return list(_load_samples())


@lru_cache(maxsize=1)
def _load_guides() -> dict[str, GuideArticle]:
    path = get_settings().data_dir / "guides.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Could not load NyayaGuide articles: %s", exc)
        return {}
    if not isinstance(raw, dict):
        logger.error("guides.json must contain an object")
        return {}

    guides: dict[str, GuideArticle] = {}
    for notice_type, item in raw.items():
        if not isinstance(item, dict):
            continue
        try:
            guides[str(notice_type)] = GuideArticle(
                notice_type=str(notice_type),
                title=str(item.get("title") or "Legal guide"),
                overview=str(item.get("overview") or ""),
                steps=tuple(
                    (str(step.get("title", "")), str(step.get("detail", "")))
                    for step in item.get("steps", [])
                    if isinstance(step, dict)
                ),
                documents=tuple(str(doc) for doc in item.get("documents", [])),
                timeline=tuple(
                    (str(point.get("when", "")), str(point.get("action", "")))
                    for point in item.get("timeline", [])
                    if isinstance(point, dict)
                ),
                mistakes=tuple(str(value) for value in item.get("mistakes", [])),
                lawyer_flags=tuple(str(value) for value in item.get("lawyer_flags", [])),
                reply_points=tuple(str(value) for value in item.get("reply_points", [])),
            )
        except Exception as exc:  # pragma: no cover - validation guard
            logger.warning("Skipping malformed guide %s: %s", notice_type, exc)
    return guides


def _fallback_guide(notice_type: str) -> GuideArticle:
    return GuideArticle(
        notice_type=notice_type,
        title="A legal notice: first steps",
        overview=(
            "A legal notice is a formal written demand sent before a case is filed. "
            "Read it carefully, note the deadline, and reply in writing."
        ),
        steps=(
            (
                "Identify the sender and the demand",
                "Write down who sent the notice, what they want, and the date.",
            ),
            (
                "Reply in writing",
                "Send a polite reply by registered post and keep proof of delivery.",
            ),
            (
                "Get free legal help",
                "Call the NALSA helpline 15100 or contact your District Legal Services Authority.",
            ),
        ),
        documents=("The notice", "The agreement or receipt referred to", "Proof of payment"),
        timeline=(("Immediately", "Note the sender, demand, and deadline."),),
        mistakes=("Ignoring the notice.", "Replying only by phone."),
        lawyer_flags=("The notice threatens criminal action.", "The amount is unclear."),
        reply_points=("Acknowledge the notice.", "Deny or clarify the claim."),
    )


def get_guide(
    notice_type: str,
    language: str,
    locales: LocaleStore | None = None,
) -> GuideResponse:
    store = locales or get_locale_store()
    code = normalize_language(language)
    guide = _load_guides().get(notice_type) or _fallback_guide(notice_type)
    notice = store.notice(code, notice_type)
    labels = store.labels(code)
    english_notice = store.english_notice(notice_type)

    native_summary = _safe_format(
        str(store.get(code).get("summary_frame", "")),
        {
            "topic": str(notice.get("topic", "")),
            "sender": str(labels.get("sender_unknown", "The sender")),
            "allegation": str(notice.get("allegation", "")),
            "date_clause": str(labels.get("date_clause_none", "")),
            "consequence": str(notice.get("consequence", "")),
        },
    )

    return GuideResponse(
        notice_type=cast(Any, notice_type),
        notice_type_label=str(notice.get("label", english_notice.get("label", "Legal Notice"))),
        title=guide.title,
        overview=guide.overview,
        native_summary=native_summary,
        steps=[
            GuideStep(number=index, title=title, detail=detail)
            for index, (title, detail) in enumerate(guide.steps, start=1)
        ],
        documents=list(guide.documents),
        timeline=[
            GuideTimelineItem(when=when, action=action)
            for when, action in guide.timeline
        ],
        mistakes=list(guide.mistakes),
        lawyer_flags=list(guide.lawyer_flags),
        reply_points=list(guide.reply_points),
        disclaimer=str(labels.get("disclaimer", "")),
        language=cast(Any, code),
    )


@lru_cache(maxsize=1)
def _load_legal_aid() -> LegalAidDirectory:
    path = get_settings().data_dir / "legal_aid.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Could not load legal aid directory: %s", exc)
        return LegalAidDirectory(
            helpline="15100",
            website="https://nalsa.gov.in",
            note="Call the free NALSA helpline 15100 for legal aid.",
            states={},
        )

    states: dict[str, tuple[str, ...]] = {}
    raw_states = raw.get("states", {}) if isinstance(raw, dict) else {}
    if isinstance(raw_states, dict):
        for state, districts in raw_states.items():
            if isinstance(districts, list):
                states[str(state)] = tuple(str(district) for district in districts)
    return LegalAidDirectory(
        helpline=str(raw.get("helpline") or "15100"),
        website=str(raw.get("website") or "https://nalsa.gov.in"),
        note=str(raw.get("note") or ""),
        states=states,
    )


def get_legal_aid_options() -> LegalAidOptionsResponse:
    directory = _load_legal_aid()
    states = [
        StateOption(
            name=state,
            slsa_name=f"{state} State Legal Services Authority",
            districts=[
                DistrictOption(
                    name=district,
                    dlsa_name=f"District Legal Services Authority, {district}",
                )
                for district in districts
            ],
        )
        for state, districts in sorted(directory.states.items())
    ]
    return LegalAidOptionsResponse(
        states=states,
        helpline=directory.helpline,
        website=directory.website,
    )


def _match_state(directory: LegalAidDirectory, state: str) -> str | None:
    target = state.strip().casefold()
    for candidate in directory.states:
        if candidate.casefold() == target:
            return candidate
    return None


def _match_district(districts: tuple[str, ...], district: str) -> str | None:
    target = district.strip().casefold()
    for candidate in districts:
        if candidate.casefold() == target:
            return candidate
    return None


_ELIGIBILITY = (
    "Women and children",
    "Members of Scheduled Castes, Scheduled Tribes, and other disadvantaged groups",
    "Persons with disabilities",
    "Victims of trafficking, disaster, violence, or abuse",
    "Industrial workmen",
    "Persons in custody or detention",
    "Persons whose annual income is below the limit set by the State Legal Services Authority",
    "Any person for whom the court or the Legal Services Authority considers legal aid necessary",
)

_DOCUMENTS = (
    "Aadhaar card, voter ID, or another identity proof",
    "Address proof",
    "Income certificate, ration card, or salary slip",
    "The legal notice, court papers, or complaint",
    "Any agreement, receipt, cheque, or other document connected to the dispute",
)

_APPLICATION_STEPS = (
    "Call 15100 or visit the front office of the District Legal Services Authority (DLSA) in your district court complex.",
    "Ask for Form A, the application for free legal aid, or download it from your State Legal Services Authority website.",
    "Attach your identity, address, income, and case documents. Keep a copy of everything.",
    "Meet the legal aid lawyer assigned to your application and explain the facts and deadline.",
    "Follow up with the DLSA office and keep the acknowledgement of your application.",
)


def find_legal_aid(state: str, district: str) -> LegalAidResponse:
    directory = _load_legal_aid()
    state_clean = state.strip()[:80] or "Your state"
    district_clean = district.strip()[:80] or "Your district"
    matched_state = _match_state(directory, state_clean)
    matched_district: str | None = None
    if matched_state is not None:
        matched_district = _match_district(
            directory.states[matched_state], district_clean
        )

    resolved_state = matched_state or state_clean
    resolved_district = matched_district or district_clean
    matched = matched_state is not None and matched_district is not None

    if matched:
        note = (
            f"Showing the indicative DLSA entry for {resolved_district}, "
            f"{resolved_state}. {directory.note}"
        )
    elif matched_state is not None:
        note = (
            f"We could not match “{district_clean}” in our demo district list for "
            f"{resolved_state}. Call {directory.helpline} and ask for the DLSA nearest "
            "to you. The application steps below still apply."
        )
    else:
        note = (
            f"We could not match “{state_clean}” in our demo directory. Call "
            f"{directory.helpline} and ask for the District Legal Services Authority "
            "nearest to you. The application steps below still apply."
        )

    return LegalAidResponse(
        matched=matched,
        state=resolved_state,
        district=resolved_district,
        dlsa_name=f"District Legal Services Authority, {resolved_district}",
        address=f"District Court Complex, {resolved_district}, {resolved_state}",
        phone=f"{directory.helpline} (free national legal aid helpline)",
        helpline=directory.helpline,
        website=directory.website,
        hours="Monday to Friday, 10:00 AM to 5:00 PM (confirm local hours before visiting)",
        note=note,
        eligibility=list(_ELIGIBILITY),
        documents=list(_DOCUMENTS),
        application_steps=list(_APPLICATION_STEPS),
    )
