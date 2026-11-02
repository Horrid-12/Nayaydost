"""Defensive PDF text extraction.

The parser never writes uploads to disk. Files are read into memory, checked,
and discarded after text extraction. Scanned PDFs (which contain images rather
than text) return a citizen-friendly error asking the user to paste the text.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from server.config import get_settings
from server.errors import DocumentError

logger = logging.getLogger(__name__)

try:  # pypdf is a required dependency, but the app should explain if it is absent.
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - exercised only in a broken install
    PdfReader = None  # type: ignore[assignment]


@dataclass(slots=True)
class ParsedDocument:
    text: str
    pages: int
    total_pages: int
    characters: int
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def sanitize_filename(filename: str | None) -> str:
    if not filename:
        return "Uploaded notice.pdf"
    name = Path(filename).name
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:180] or "Uploaded notice.pdf"


_LIST_MARKER = re.compile(r"^(?:\d{1,3}[.)]|[-*•●▪])\s+")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?$")
_HEADING = re.compile(r"^[A-Z0-9][A-Z0-9\s&.,'()/-]{6,}$")
_LAST_WORD = re.compile(r"([A-Za-z]+)$")
_COMMON_SHORT_WORDS = frozenset(
    """
    a act all also an and any are as at be been but by can day days did do
    due each fee fees for from had has have he her here him his how if in
    into is it its law less may more new no not now of old on once one only
    or our out over pay per said she so some such tax than that the their
    them then there these they this those time to under up upon use used
    was we were what when where which who whom whose why will with you your
    """.split()
)


def _looks_like_heading(line: str) -> bool:
    if len(line) > 120 or not _HEADING.match(line):
        return False
    # A line made mostly of uppercase words is a heading, not a wrapped
    # sentence. Short acronyms and dates are left alone.
    letters = [character for character in line if character.isalpha()]
    if not letters:
        return False
    uppercase = sum(1 for character in letters if character.isupper())
    return uppercase / len(letters) >= 0.8


def _join_separator(previous: str, current: str) -> str | None:
    """Return the separator to use, or None when the break is real.

    PDF generators often break a word or number at the right margin without a
    hyphen. When a long line ends in a short fragment, joining without a space
    reconstructs words such as ``amou`` / ``nt`` and numbers such as
    ``1,85,0`` / ``00``.
    """
    if not previous or not current:
        return None
    if _LIST_MARKER.match(current) or _looks_like_heading(current):
        return None
    if _looks_like_heading(previous) or _SENTENCE_END.search(previous):
        return None

    last = previous[-1]
    first = current[0]
    if last == "-" and first.islower():
        return ""
    # Numbers are often split by PDF layout, for example "1,85,0" / "00".
    if last.isdigit() and first.isdigit():
        return ""
    if last.isalnum() and first.islower():
        match = _LAST_WORD.search(previous)
        if (
            match is not None
            and len(previous) >= 55
            and len(match.group(1)) <= 4
            and match.group(1).lower() not in _COMMON_SHORT_WORDS
        ):
            return ""
        return " "
    # A comma or semicolon followed by a lowercase word is usually wrapping.
    if last in ",;" and first.islower():
        return " "
    return None


def _join_wrapped_lines(lines: list[str]) -> str:
    output: list[str] = []
    for line in lines:
        if not line:
            if output and output[-1] != "":
                output.append("")
            continue
        if not output or output[-1] == "":
            output.append(line)
            continue
        previous = output[-1]
        separator = _join_separator(previous, line)
        if separator is None:
            output.append(line)
        else:
            output[-1] = previous + separator + line
    return "\n".join(output)


def _normalize_text(text: str) -> str:
    cleaned = (
        text.replace("\x00", " ")
        .replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    cleaned = re.sub(r"[ \t\f\v]+", " ", cleaned)
    lines = [line.strip() for line in cleaned.split("\n")]
    cleaned = _join_wrapped_lines(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _truncate_at_boundary(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    boundary = max(candidate.rfind("\n\n"), candidate.rfind(". "))
    if boundary > limit * 0.6:
        return candidate[: boundary + 1].strip()
    return candidate.strip()


def parse_pdf_bytes(data: bytes, filename: str | None = None) -> ParsedDocument:
    settings = get_settings()
    display_name = sanitize_filename(filename)

    if not data:
        raise DocumentError(
            "empty_file",
            "That file appears to be empty.",
            hint="Choose the PDF again, or paste the notice text instead.",
        )
    if len(data) > settings.max_upload_bytes:
        raise DocumentError(
            "pdf_too_large",
            f"That PDF is larger than {settings.max_upload_mb} MB.",
            hint="Upload a smaller PDF, or paste only the notice text.",
        )
    if b"%PDF-" not in data[:1024]:
        raise DocumentError(
            "not_pdf",
            "That file does not look like a PDF.",
            hint="Upload a PDF file, or paste the notice text in the text tab.",
        )
    if PdfReader is None:
        raise DocumentError(
            "parser_unavailable",
            "PDF reading is not available on this server right now.",
            hint="Paste the notice text instead. The rest of NyayaDost still works.",
            status_code=503,
        )

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception as exc:  # pypdf raises several exception classes
        logger.warning("Could not open PDF %s: %s", display_name, exc)
        raise DocumentError(
            "pdf_unreadable",
            "We could not open that PDF. It may be damaged or in an unsupported format.",
            hint="Try opening it in a PDF reader and saving a fresh copy, or paste the text.",
        ) from exc

    warnings: list[str] = []
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            logger.info("Encrypted PDF could not be unlocked: %s", exc)
            unlocked = 0
        if not unlocked:
            raise DocumentError(
                "pdf_encrypted",
                "This PDF is password-protected, so we cannot read it.",
                hint="Remove the password in a PDF reader and upload it again, or paste the text.",
            )
        warnings.append("The PDF was password-protected; it was opened with an empty password.")

    try:
        total_pages = len(reader.pages)
    except Exception as exc:
        logger.warning("Could not count PDF pages: %s", exc)
        raise DocumentError(
            "pdf_unreadable",
            "We could not read the pages in that PDF.",
            hint="Try saving a fresh copy of the PDF, or paste the notice text.",
        ) from exc

    if total_pages == 0:
        raise DocumentError(
            "pdf_no_pages",
            "That PDF has no pages we can read.",
            hint="Check the file, or paste the notice text instead.",
        )

    pages_to_read = min(total_pages, settings.max_pdf_pages)
    if pages_to_read < total_pages:
        warnings.append(
            f"Only the first {pages_to_read} of {total_pages} pages were read."
        )

    page_texts: list[str] = []
    failed_pages = 0
    for index in range(pages_to_read):
        try:
            page = reader.pages[index]
            extracted = page.extract_text() or ""
            if extracted.strip():
                page_texts.append(extracted)
        except Exception as exc:
            failed_pages += 1
            logger.info("Could not extract page %s from %s: %s", index + 1, display_name, exc)

    if failed_pages:
        warnings.append(
            f"{failed_pages} page(s) could not be read and were skipped."
        )

    text = _normalize_text("\n\n".join(page_texts))
    if len(text) < 80:
        raise DocumentError(
            "pdf_scanned",
            "This PDF looks like a scanned image, so there is no selectable text to explain.",
            hint=(
                "Open the PDF, copy the notice text and paste it in the text tab. "
                "If you only have a photo, use your phone's text scanner first."
            ),
        )

    truncated = len(text) > settings.max_text_chars
    if truncated:
        text = _truncate_at_boundary(text, settings.max_text_chars)
        warnings.append(
            f"The notice was shortened to the first {settings.max_text_chars:,} characters."
        )

    return ParsedDocument(
        text=text,
        pages=pages_to_read,
        total_pages=total_pages,
        characters=len(text),
        truncated=truncated,
        warnings=warnings,
    )
