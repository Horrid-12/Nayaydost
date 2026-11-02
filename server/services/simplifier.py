"""Deterministic legal-notice analysis.

NyayaDost deliberately does not use a generative model for the core explanation.
A rulebook is easier to audit, works with no network, and never invents a
statute. The engine below:

1. detects the most likely notice type from statutory and plain-language markers,
2. extracts the sender, notice date, amount, and response deadline,
3. fills the curated vernacular catalog with those facts, and
4. produces a conservative reply draft and a spoken-word script.

Every extraction is best-effort. When a fact is not present, the response omits
it or clearly marks the deadline as estimated rather than guessing silently.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from server.config import get_settings
from server.models import (
    AnalysisResponse,
    Deadline,
    Fact,
    GlossaryItem,
    ReplyDraft,
    SourceInfo,
    Step,
)
from server.services.localization import (
    LocaleStore,
    get_locale_store,
    normalize_language,
)

# ---------------------------------------------------------------------------
# Notice detection
# ---------------------------------------------------------------------------

# Each rule is (regex, weight, human-readable signal). Patterns are intentionally
# forgiving: legal notices are typed by clerks, scanned, and re-typed, so exact
# punctuation cannot be relied on.
Rule = tuple[str, float, str]

NOTICE_RULES: dict[str, tuple[Rule, ...]] = {
    "cheque_bounce": (
        (r"section\s*138", 5.0, "Section 138"),
        (r"negotiable\s+instruments", 4.0, "Negotiable Instruments Act"),
        (r"cheque", 3.0, "cheque"),
        (r"dishonou?r", 3.0, "dishonour"),
        (r"return\s+memo", 3.0, "bank return memo"),
        (r"stop\s+payment", 2.0, "stop payment"),
        (r"insufficient\s+funds", 2.0, "insufficient funds"),
        (r"138", 1.5, "Section 138 reference"),
    ),
    "rent_eviction": (
        (r"evict", 4.0, "eviction"),
        (r"vacate", 3.0, "vacate"),
        (r"tenan", 3.0, "tenancy"),
        (r"landlord", 3.0, "landlord"),
        (r"rent\s+control", 3.0, "rent control law"),
        (r"security\s+deposit", 2.5, "security deposit"),
        (r"arrears", 2.0, "arrears"),
        (r"lease", 2.0, "lease"),
        (r"premises", 2.0, "premises"),
        (r"rent", 2.0, "rent"),
    ),
    "loan_recovery": (
        (r"sarfaesi", 5.0, "SARFAESI"),
        (r"recovery\s+agent", 3.0, "recovery agent"),
        (r"loan", 3.0, "loan"),
        (r"e\.?m\.?i", 3.0, "EMI"),
        (r"outstanding", 2.0, "outstanding amount"),
        (r"credit\s+card", 2.0, "credit card"),
        (r"arbitration", 2.0, "arbitration"),
        (r"instal?lment", 2.0, "instalment"),
        (r"default", 2.0, "default"),
        (r"demand\s+notice", 2.0, "demand notice"),
        (r"bank", 1.0, "bank"),
    ),
    "consumer": (
        (r"e-?daakhil", 4.0, "e-Daakhil"),
        (r"consumer", 4.0, "consumer"),
        (r"defective", 3.0, "defective product"),
        (r"deficien", 3.0, "deficient service"),
        (r"district\s+consumer", 3.0, "District Consumer Commission"),
        (r"warranty", 2.0, "warranty"),
        (r"refund", 2.0, "refund"),
        (r"product", 1.0, "product"),
        (r"service", 1.0, "service"),
        (r"invoice", 1.0, "invoice"),
    ),
    "maintenance": (
        (r"section\s*144", 3.0, "Section 144 BNSS"),
        (r"bnss", 3.0, "BNSS"),
        (r"crpc\s*125|section\s*125", 4.0, "maintenance provision"),
        (r"maintenance", 4.0, "maintenance"),
        (r"alimony", 3.0, "alimony"),
        (r"family\s+court", 3.0, "family court"),
        (r"monthly\s+support", 3.0, "monthly support"),
        (r"wife", 2.0, "spouse"),
        (r"children", 2.0, "children"),
        (r"child", 1.5, "child"),
    ),
    "property": (
        (r"encroach", 4.0, "encroachment"),
        (r"possession", 3.0, "possession"),
        (r"title\s+deed", 3.0, "title deed"),
        (r"sale\s+deed", 3.0, "sale deed"),
        (r"specific\s+relief", 3.0, "Specific Relief Act"),
        (r"injunction", 3.0, "injunction"),
        (r"boundary", 2.0, "boundary dispute"),
        (r"mutation", 2.0, "mutation record"),
        (r"property", 2.0, "property"),
        (r"plot", 1.5, "plot"),
        (r"land", 1.5, "land"),
    ),
    "employment": (
        (r"labour\s+commissioner", 4.0, "Labour Commissioner"),
        (r"industrial\s+dispute", 4.0, "industrial dispute"),
        (r"termination", 4.0, "termination"),
        (r"salary", 3.0, "salary"),
        (r"wages", 3.0, "wages"),
        (r"notice\s+period", 3.0, "notice period"),
        (r"gratuity", 3.0, "gratuity"),
        (r"employ", 3.0, "employment"),
        (r"resignation", 2.0, "resignation"),
        (r"provident\s+fund|\bpf\b", 1.5, "provident fund"),
    ),
    "tax": (
        (r"income\s*-?\s*tax", 4.0, "Income-tax Act"),
        (r"\bgst\b", 4.0, "GST"),
        (r"assessment\s+year", 4.0, "assessment year"),
        (r"e-?filing", 3.0, "e-filing portal"),
        (r"\bitr\b", 3.0, "income-tax return"),
        (r"section\s*143", 3.0, "Section 143"),
        (r"\btds\b", 2.0, "TDS"),
        (r"tax", 2.0, "tax"),
        (r"penalty", 2.0, "penalty"),
        (r"demand", 2.0, "demand"),
    ),
}

_COMPILED_RULES: dict[str, tuple[tuple[re.Pattern[str], float, str], ...]] = {
    notice_id: tuple(
        (re.compile(pattern, re.IGNORECASE), weight, signal)
        for pattern, weight, signal in rules
    )
    for notice_id, rules in NOTICE_RULES.items()
}

DEFAULT_NOTICE = "generic"
DETECTION_THRESHOLD = 2.5

# ---------------------------------------------------------------------------
# Date and money extraction
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?"
)

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})\s*[\/\-.]\s*(\d{1,2})\s*[\/\-.]\s*(\d{2,4})\b"),
    re.compile(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})[,\s]+(\d{{4}})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?[,\s]+(\d{{4}})\b",
        re.IGNORECASE,
    ),
)

_NOTICE_DATE_KEYWORDS = re.compile(
    r"(?:dated|date\s*of\s*(?:this\s*)?notice|notice\s*date|issued\s+on|"
    r"date\s*[:\-])\s*[:\-]?\s*",
    re.IGNORECASE,
)
_DEADLINE_KEYWORDS = re.compile(
    r"(?:on\s+or\s+before|latest\s+by|pay\s+by|reply\s+by|respond\s+by|"
    r"due\s+on|due\s+date|last\s+date|before|by)\s*[:\-]?\s*",
    re.IGNORECASE,
)
_RELATIVE_DEADLINE = re.compile(
    r"(?:within|in)\s+(\d{1,3})\s*(day|days|week|weeks|month|months)\b"
    r"|(\d{1,3})\s*(day|days|week|weeks|month|months)\s+"
    r"(?:from|of)\s+(?:the\s+)?(?:date\s+of\s+(?:this\s+)?notice|receipt|notice)",
    re.IGNORECASE,
)

_AMOUNT_PATTERN = re.compile(
    r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.\d{1,2})?)"
    r"(?:\s*(?:lakh|lac|crore|thousand))?",
    re.IGNORECASE,
)
_AMOUNT_CONTINUATION = re.compile(r"\s+([0-9]{1,3})\b")
_AMOUNT_WORDS = re.compile(
    r"(?:rupees|rs\.?)\s+([a-z\s]{3,40}?)\s*(?:only)?\b", re.IGNORECASE
)

_SENDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:on\s+behalf\s+of|under\s+instructions\s+from|issued\s+by|"
        r"notice\s+from|sent\s+by)\s+([A-Z][A-Za-z0-9&.,'()\- ]{2,90}?)"
        r"(?:,|\s+through|\s+advocate|\s+and\s+others|\n|\.)",
    ),
    re.compile(
        r"(?:i\s+am|we\s+are)\s+(?:the\s+)?(?:authorised\s+)?(?:advocate|attorney)"
        r"\s+(?:for|of)\s+([A-Z][A-Za-z0-9&.,'()\- ]{2,90}?)"
        r"(?:,|\n|\.)",
    ),
    re.compile(
        r"\b([A-Z][A-Za-z0-9&.'()\- ]{2,70}"
        r"(?:Bank|Bank\s+Ltd\.?|Limited|Ltd\.?|LLP|Private\s+Limited|"
        r"Finance|Housing|Department|Authority|Corporation|Company|"
        r"Associates|Advocates?))\b"
    ),
)
_SIGNATURE_COMPANY = re.compile(
    r"^([A-Z][A-Za-z0-9&.'()\- ]{2,80}?"
    r"(?:Bank|Limited|Ltd\.?|LLP|Private\s+Limited|Finance|Housing|"
    r"Department|Authority|Corporation|Company|Associates|Advocates?))"
    r"\s*$",
    re.MULTILINE,
)

def _tz_available() -> bool:
    try:
        ZoneInfo("Asia/Kolkata")
        return True
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover - platform edge
        return False


_IST = ZoneInfo("Asia/Kolkata") if _tz_available() else None


def today_ist() -> date:
    if _IST is not None:
        return datetime.now(_IST).date()
    return datetime.now().date()


def now_ist_iso() -> str:
    if _IST is not None:
        return datetime.now(_IST).isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class DateHit:
    value: date
    start: int
    end: int
    raw: str


@dataclass(frozen=True, slots=True)
class DetectionResult:
    notice_type: str
    score: float
    confidence: float
    signals: list[str]


@dataclass(frozen=True, slots=True)
class DeadlineResult:
    deadline: date
    source: Literal["stated", "estimated", "statutory"]
    note: str | None
    stated: bool


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze_notice(
    text: str,
    language: str = "en",
    source_name: str = "Pasted notice",
    source_kind: Literal["pdf", "text"] = "text",
    pages: int | None = None,
    truncated: bool = False,
    warnings: Iterable[str] | None = None,
    locales: LocaleStore | None = None,
) -> AnalysisResponse:
    """Analyse a notice and return a fully localized citizen explanation."""

    store = locales or get_locale_store()
    settings = get_settings()
    code = normalize_language(language)
    locale = store.get(code)
    labels = store.labels(code)
    today = today_ist()

    cleaned = text.strip()
    detection = detect_notice_type(cleaned)
    notice = store.notice(code, detection.notice_type)
    english_notice = store.english_notice(detection.notice_type)

    dates = find_dates(cleaned)
    notice_date = extract_notice_date(cleaned, dates)
    amount = extract_amount(cleaned)
    sender = extract_sender(cleaned)
    primary = extract_deadline(
        cleaned,
        dates,
        notice_date=notice_date,
        default_days=int(notice.get("default_days", 15) or 15),
        today=today,
    )

    sender_display = sender or str(labels.get("sender_unknown", "The sender"))
    date_clause = (
        str(labels.get("date_clause", "Reply by {date}.")).format(
            date=format_indian_date(primary.deadline)
        )
        if primary.stated
        else str(labels.get("date_clause_none", "No clear reply date is given."))
    )

    summary_body = _safe_format(
        str(locale.get("summary_frame", "")),
        {
            "topic": str(notice.get("topic", "")),
            "sender": sender_display,
            "allegation": str(notice.get("allegation", "")),
            "date_clause": date_clause,
            "consequence": str(notice.get("consequence", "")),
        },
    )
    summary_title = str(notice.get("label", english_notice.get("label", "Legal Notice")))

    deadlines = _build_deadlines(
        primary,
        notice=notice,
        labels=labels,
        today=today,
        base_severity=str(notice.get("severity", "warning")),
    )
    steps = _build_steps(notice, locale, labels)
    glossary = _build_glossary(store, code, notice)
    facts = _build_facts(
        labels=labels,
        sender=sender_display,
        notice_date=notice_date,
        amount=amount,
        primary=primary,
        statute=str(notice.get("statute", "")),
    )
    reply = _build_reply(
        notice_type=detection.notice_type,
        labels=labels,
        notice=notice,
        english_notice=english_notice,
        sender=sender,
        notice_date=notice_date,
        primary=primary,
    )
    disclaimer = str(labels.get("disclaimer", ""))
    tts_text = _build_tts_text(
        summary_title=summary_title,
        summary_body=summary_body,
        labels=labels,
        primary=primary,
        steps=steps,
        disclaimer=disclaimer,
        limit=settings.max_tts_chars + 300,
    )

    warning: str | None = None
    if detection.notice_type == DEFAULT_NOTICE and detection.score < DETECTION_THRESHOLD:
        warning = (
            "This notice did not match a common template, so the explanation is "
            "general. Read every paragraph and confirm the demand with an advocate."
        )
    elif detection.confidence < 0.55:
        warning = (
            "The notice matched more than one category. The explanation below may "
            "be partly general; check the legal basis printed in the notice."
        )

    source = SourceInfo(
        name=source_name.strip()[:200] or "Pasted notice",
        kind=source_kind,
        pages=pages,
        characters=len(cleaned),
        truncated=truncated,
        warnings=list(warnings or []),
    )

    return AnalysisResponse(
        analysis_id=f"nd_{uuid.uuid4().hex[:16]}",
        notice_type=cast(Any, detection.notice_type),
        notice_type_label=summary_title,
        notice_type_label_en=str(english_notice.get("label", "Legal Notice")),
        statute=str(notice.get("statute", "")),
        confidence=round(detection.confidence, 2),
        signals=detection.signals,
        language=cast(Any, code),
        mode="offline",
        provider="nyayadost-rulebook",
        degraded=False,
        warning=warning,
        source=source,
        original_text=cleaned,
        summary_title=summary_title,
        summary_body=summary_body,
        facts=facts,
        deadlines=deadlines,
        steps=steps,
        glossary=glossary,
        reply=reply,
        labels=labels,
        tts_text=tts_text,
        disclaimer=disclaimer,
        generated_at=now_ist_iso(),
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_notice_type(text: str) -> DetectionResult:
    lowered = text.lower()
    scores: dict[str, float] = {}
    signals: dict[str, list[str]] = {}

    for notice_id, rules in _COMPILED_RULES.items():
        score = 0.0
        matched: list[str] = []
        for pattern, weight, signal in rules:
            hits = 0
            for _ in pattern.finditer(lowered):
                hits += 1
                if hits >= 2:
                    break
            if hits:
                score += weight * hits
                matched.append(signal)
        scores[notice_id] = score
        signals[notice_id] = matched

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_id, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score < DETECTION_THRESHOLD:
        return DetectionResult(
            notice_type=DEFAULT_NOTICE,
            score=top_score,
            confidence=round(min(0.44, 0.28 + top_score * 0.05), 2),
            signals=["No specific statutory marker found"],
        )

    margin = max(0.0, top_score - second_score)
    confidence = min(0.97, 0.46 + top_score * 0.045 + margin * 0.025)
    if margin < 1.0 and top_score < 6.0:
        confidence -= 0.08
    confidence = max(0.4, min(0.97, confidence))

    return DetectionResult(
        notice_type=top_id,
        score=top_score,
        confidence=round(confidence, 2),
        signals=signals[top_id][:6] or ["General legal language"],
    )


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def find_dates(text: str) -> list[DateHit]:
    hits: list[DateHit] = []
    seen: set[tuple[int, int]] = set()
    current_year = today_ist().year

    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            if (match.start(), match.end()) in seen:
                continue
            parsed = _parse_date_match(match, current_year)
            if parsed is None:
                continue
            seen.add((match.start(), match.end()))
            hits.append(
                DateHit(
                    value=parsed,
                    start=match.start(),
                    end=match.end(),
                    raw=match.group(0),
                )
            )

    hits.sort(key=lambda hit: hit.start)
    return hits


def _parse_date_match(match: re.Match[str], current_year: int) -> date | None:
    raw_groups = match.groups()
    if not raw_groups:
        return None
    try:
        if raw_groups[0] and len(raw_groups[0]) == 4 and raw_groups[0].isdigit():
            year, month, day = int(raw_groups[0]), int(raw_groups[1]), int(raw_groups[2])
        elif raw_groups[0].isdigit() and raw_groups[1].isdigit():
            first, second = int(raw_groups[0]), int(raw_groups[1])
            third = raw_groups[2]
            if first > 12:
                day, month = first, second
            elif second > 12:
                month, day = first, second
            else:
                day, month = first, second
            year = _expand_year(str(third), current_year)
        else:
            first = str(raw_groups[0]).lower()
            if first in _MONTHS:
                month = _MONTHS[first]
                day = int(raw_groups[1])
                year = _expand_year(str(raw_groups[2]), current_year)
            else:
                day = int(raw_groups[0])
                month = _MONTHS.get(str(raw_groups[1]).lower(), 0)
                year = _expand_year(str(raw_groups[2]), current_year)
    except (TypeError, ValueError, IndexError):
        return None

    if not (1990 <= year <= current_year + 6):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _expand_year(raw: str, current_year: int) -> int:
    value = int(raw)
    if value < 100:
        return 2000 + value if value < 70 else 1900 + value
    return value


def _date_after_keyword(
    text: str, keyword: re.Pattern[str], dates: list[DateHit], window: int = 48
) -> DateHit | None:
    for match in keyword.finditer(text):
        for hit in dates:
            if match.end() <= hit.start <= match.end() + window:
                return hit
    return None


def extract_notice_date(text: str, dates: list[DateHit]) -> date | None:
    hit = _date_after_keyword(text, _NOTICE_DATE_KEYWORDS, dates)
    if hit is not None:
        return hit.value
    # Most Indian notices print the issue date near the top. Use the first date
    # only if it appears early enough to be a heading rather than an event date.
    if dates and dates[0].start < max(320, int(len(text) * 0.25)):
        return dates[0].value
    return None


def extract_deadline(
    text: str,
    dates: list[DateHit],
    *,
    notice_date: date | None,
    default_days: int,
    today: date,
) -> DeadlineResult:
    """Return the most defensible deadline for the notice."""

    explicit = _date_after_keyword(text, _DEADLINE_KEYWORDS, dates, window=56)
    plausible: list[DateHit] = []
    if explicit is not None:
        if explicit.value >= (notice_date or today) - timedelta(days=2):
            plausible.append(explicit)
    if not plausible:
        # A date printed later in the notice, after the demand paragraph, is
        # often the payment/reply date even without a "by" keyword.
        for hit in dates:
            if notice_date is not None and hit.value <= notice_date:
                continue
            if hit.value < today - timedelta(days=1):
                continue
            if hit.value > today + timedelta(days=550):
                continue
            plausible.append(hit)
            break

    if plausible:
        chosen = plausible[0]
        return DeadlineResult(
            deadline=chosen.value,
            source="stated",
            note="Date printed in the notice.",
            stated=True,
        )

    relative = _RELATIVE_DEADLINE.search(text)
    if relative is not None:
        groups = relative.groups()
        raw_number = groups[0] or groups[2]
        unit = (groups[1] or groups[3] or "days").lower()
        days = _relative_to_days(int(raw_number), unit)
        base = notice_date or today
        return DeadlineResult(
            deadline=base + timedelta(days=days),
            source="stated",
            note=(
                "Counted from the notice date."
                if notice_date is not None
                else "Counted from today because no notice date was found."
            ),
            stated=True,
        )

    base = notice_date or today
    return DeadlineResult(
        deadline=base + timedelta(days=max(1, default_days)),
        source="estimated",
        note="Estimated using the usual response period for this notice type.",
        stated=False,
    )


def _relative_to_days(number: int, unit: str) -> int:
    if unit.startswith("week"):
        return number * 7
    if unit.startswith("month"):
        return number * 30
    return number


def extract_amount(text: str) -> str | None:
    match = _AMOUNT_PATTERN.search(text)
    if match is not None:
        raw = re.sub(r"[\s,]", "", match.group(1))
        # A PDF may wrap a long amount after a short comma group, as in
        # "1,85,0" / "00". Complete Indian-grouped numbers end in three
        # digits, so only look for a continuation when the last group is short.
        last_group = match.group(1).rsplit(",", 1)[-1]
        if "," in match.group(1) and len(last_group) < 3:
            continuation = _AMOUNT_CONTINUATION.match(text, match.end())
            if continuation is not None:
                raw += continuation.group(1)
        try:
            value = float(raw)
        except ValueError:
            return None
        if value <= 0:
            return None
        decimals = 0 if value.is_integer() else 2
        return f"₹{_indian_grouping(value, decimals)}"

    words = _AMOUNT_WORDS.search(text)
    if words is not None:
        phrase = " ".join(words.group(1).split())
        if phrase:
            return f"₹{phrase} (as written)"
    return None


def _indian_grouping(value: float, decimals: int) -> str:
    formatted = f"{value:.{decimals}f}"
    whole, _, fraction = formatted.partition(".")
    if len(whole) <= 3:
        grouped = whole
    else:
        last_three = whole[-3:]
        rest = whole[:-3]
        parts: list[str] = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts + [last_three])
    return f"{grouped}.{fraction}" if fraction else grouped


def extract_sender(text: str) -> str | None:
    for pattern in _SENDER_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        candidate = _clean_sender(match.group(1))
        if candidate:
            return candidate

    match = _SIGNATURE_COMPANY.search(text)
    if match is not None:
        candidate = _clean_sender(match.group(1))
        if candidate:
            return candidate
    return None


def _clean_sender(raw: str) -> str | None:
    candidate = re.sub(r"\s+", " ", raw).strip(" .,:;-\n\t")
    candidate = re.sub(
        r"^(?:the|m/s\.?|messrs\.?)\s+", "", candidate, flags=re.IGNORECASE
    )
    if len(candidate) < 3 or len(candidate) > 90:
        return None
    if candidate.lower() in {"you", "your", "sir", "madam", "advocate"}:
        return None
    # Avoid returning a date-like or amount-like fragment.
    if re.fullmatch(r"[\d\s,./-]+", candidate):
        return None
    return candidate


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_deadlines(
    primary: DeadlineResult,
    *,
    notice: dict[str, Any],
    labels: dict[str, str],
    today: date,
    base_severity: str,
) -> list[Deadline]:
    days_remaining = (primary.deadline - today).days
    severity = _deadline_severity(days_remaining, base_severity)
    source_label = {
        "stated": labels.get("stated", "Stated in the notice"),
        "estimated": labels.get("estimated", "Estimated from receipt"),
        "statutory": labels.get("statutory_deadline", "Related legal window"),
    }[primary.source]

    items = [
        Deadline(
            label=str(
                notice.get(
                    "deadline_label",
                    labels.get("response_deadline", "Your response deadline"),
                )
            ),
            date=primary.deadline.isoformat(),
            date_display=format_indian_date(primary.deadline),
            days_remaining=days_remaining,
            source=primary.source,
            source_label=source_label,
            severity=cast(Any, severity),
            note=primary.note,
        )
    ]

    secondary_label = notice.get("secondary_label")
    offset = notice.get("secondary_offset_days")
    if secondary_label and isinstance(offset, (int, float)) and offset > 0:
        secondary_date = primary.deadline + timedelta(days=int(offset))
        secondary_days = (secondary_date - today).days
        items.append(
            Deadline(
                label=str(secondary_label),
                date=secondary_date.isoformat(),
                date_display=format_indian_date(secondary_date),
                days_remaining=secondary_days,
                source="statutory",
                source_label=labels.get(
                    "statutory_deadline", "Related legal window"
                ),
                severity=cast(
                    Any, _deadline_severity(secondary_days, "warning")
                ),
                note="Calculated from the response deadline printed in the notice.",
            )
        )
    return items


def _deadline_severity(days_remaining: int, base: str) -> str:
    if days_remaining < 0:
        return "critical"
    if days_remaining <= 3:
        return "critical"
    if days_remaining <= 10 or base == "critical":
        return "critical" if base == "critical" else "warning"
    return base if base in {"critical", "warning", "normal"} else "warning"


def _build_steps(
    notice: dict[str, Any], locale: dict[str, Any], labels: dict[str, str]
) -> list[Step]:
    steps: list[Step] = []
    extra_title = str(notice.get("extra_step_title", "")).strip()
    extra_detail = str(notice.get("extra_step_detail", "")).strip()
    if extra_title:
        steps.append(
            Step(
                id="notice_specific",
                title=extra_title,
                detail=extra_detail or extra_title,
                priority=1,
            )
        )

    raw_steps = locale.get("common_steps", [])
    if isinstance(raw_steps, list):
        for index, raw in enumerate(raw_steps, start=1):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            detail = str(raw.get("detail", "")).strip()
            if not title:
                continue
            steps.append(
                Step(
                    id=f"common_{index}",
                    title=title,
                    detail=detail or title,
                    priority=len(steps) + 1,
                )
            )

    if not steps:
        steps.append(
            Step(
                id="common_1",
                title=labels.get("steps", "Immediate Next Steps"),
                detail="Read the notice carefully and reply in writing.",
                priority=1,
            )
        )
    return steps


def _build_glossary(
    store: LocaleStore, code: str, notice: dict[str, Any]
) -> list[GlossaryItem]:
    glossary = store.glossary(code)
    keys = notice.get("glossary_keys", [])
    ordered: list[str] = []
    if isinstance(keys, list):
        ordered.extend(str(key) for key in keys)
    for fallback in ("legal_notice", "statutory_notice", "registered_post"):
        if fallback not in ordered:
            ordered.append(fallback)

    items: list[GlossaryItem] = []
    for key in ordered:
        entry = glossary.get(key)
        if entry is None:
            continue
        items.append(
            GlossaryItem(
                key=key,
                term=entry.get("term", key),
                meaning=entry.get("meaning", ""),
            )
        )
        if len(items) >= 4:
            break
    return items


def _build_facts(
    *,
    labels: dict[str, str],
    sender: str,
    notice_date: date | None,
    amount: str | None,
    primary: DeadlineResult,
    statute: str,
) -> list[Fact]:
    facts = [Fact(label=labels.get("sender", "Sender"), value=sender)]
    if notice_date is not None:
        facts.append(
            Fact(
                label=labels.get("notice_date", "Notice date"),
                value=format_indian_date(notice_date),
            )
        )
    if amount:
        facts.append(Fact(label=labels.get("amount", "Amount mentioned"), value=amount))
    facts.append(
        Fact(
            label=labels.get("response_deadline", "Your response deadline"),
            value=format_indian_date(primary.deadline),
        )
    )
    if statute:
        facts.append(Fact(label=labels.get("legal_basis", "Legal basis"), value=statute))
    return facts


_REPLY_SPECIFIC: dict[str, str] = {
    "cheque_bounce": (
        "I have asked my bank for the cheque return memo and will verify the "
        "reason for dishonour before responding further."
    ),
    "rent_eviction": (
        "I dispute the notice period and the arrears claimed. Please provide the "
        "rent ledger, a copy of the lease, and details of every payment received."
    ),
    "loan_recovery": (
        "Please provide a complete statement of account showing the principal, "
        "interest, penalties, and every payment credited, along with the written "
        "authorisation of any recovery agent who contacts me."
    ),
    "consumer": (
        "I have preserved the invoice, warranty, and complaint records. Please "
        "provide your written resolution proposal or confirm that the complaint "
        "remains unresolved."
    ),
    "maintenance": (
        "I dispute the amount claimed and request the income, expense, and family "
        "details relied on. I am willing to respond through the proper legal forum."
    ),
    "property": (
        "I dispute the claim to title and possession. Please provide the title "
        "chain, survey records, and the legal basis for the boundary or possession "
        "claim."
    ),
    "employment": (
        "Please provide the appointment letter, salary ledger, attendance record, "
        "and the clause relied on for the termination or notice-period claim."
    ),
    "tax": (
        "I will verify the demand on the official e-filing portal and respond with "
        "the supporting returns and reconciliation. Please treat this as my "
        "request for the complete annexures relied on."
    ),
    "generic": (
        "I neither admit nor accept the claims made in the notice. Please provide "
        "the documents and calculations relied on so that I can respond properly."
    ),
}


def _build_reply(
    *,
    notice_type: str,
    labels: dict[str, str],
    notice: dict[str, Any],
    english_notice: dict[str, Any],
    sender: str | None,
    notice_date: date | None,
    primary: DeadlineResult,
) -> ReplyDraft:
    sender_line = sender or "[Sender name and address]"
    date_line = format_indian_date(notice_date) if notice_date else "[notice date]"
    subject = (
        f"Reply to your legal notice dated {date_line} regarding "
        f"{english_notice.get('topic', 'the demand made')}"
    )
    specific = _REPLY_SPECIFIC.get(notice_type, _REPLY_SPECIFIC["generic"])
    template = (
        f"To,\n{sender_line}\n[Address]\n\n"
        f"Subject: {subject}\n\n"
        "Sir / Madam,\n\n"
        f"I refer to your notice dated {date_line}. I am taking legal advice on the "
        "claims made in it.\n\n"
        f"Without admitting any liability, {specific}\n\n"
        "I request that all further communication be sent to me in writing at the "
        "address below. I reserve my right to respond in detail after reviewing the "
        "documents.\n\n"
        "Yours sincerely,\n"
        "[Your full name]\n"
        "[Your address]\n"
        "[Your phone number]\n"
        f"[Date: {format_indian_date(primary.deadline)}]\n\n"
        "Enclosures: [copies of receipts / agreement / bank memo / identity proof]\n"
        "Sent by: Registered post / Speed post — Receipt No. [_________]"
    )
    return ReplyDraft(
        note=str(labels.get("reply_note", "This is a starting draft, not legal advice.")),
        subject=subject,
        template=template,
    )


def _build_tts_text(
    *,
    summary_title: str,
    summary_body: str,
    labels: dict[str, str],
    primary: DeadlineResult,
    steps: list[Step],
    disclaimer: str,
    limit: int,
) -> str:
    step_titles = " ".join(step.title for step in steps[:3])
    deadline_line = (
        f"{labels.get('response_deadline', 'Your response deadline')}: "
        f"{format_indian_date(primary.deadline)}."
    )
    text = (
        f"{summary_title}. {summary_body} {deadline_line} "
        f"{labels.get('steps', 'Immediate Next Steps')}: {step_titles}. "
        f"{disclaimer}"
    )
    return _cut_at_sentence(text, max(400, limit))


def _cut_at_sentence(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    boundary = max(
        candidate.rfind(". "),
        candidate.rfind("। "),
        candidate.rfind("? "),
        candidate.rfind("! "),
    )
    if boundary > limit * 0.5:
        return candidate[: boundary + 1].strip()
    return candidate.strip()


def _safe_format(template: str, values: dict[str, str]) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        result = template
        for key, value in values.items():
            result = result.replace("{" + key + "}", value)
        return result


# ---------------------------------------------------------------------------
# Small public utilities used by the API layer
# ---------------------------------------------------------------------------


def format_indian_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
