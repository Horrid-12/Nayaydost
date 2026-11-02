"""Typed application errors and citizen-friendly messages."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """An expected error that is safe to show to a citizen.

    ``message`` is deliberately written in plain language. ``hint`` gives the
    next practical step. Internal details stay in the server log.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.hint = hint
        self.details = details or {}


class DocumentError(AppError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(code, message, status_code=status_code, hint=hint)


class RateLimitError(AppError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "rate_limited",
            "Too many requests came in at once. Please wait a moment and try again.",
            status_code=429,
            hint=f"Try again in about {retry_after} seconds.",
            details={"retry_after": retry_after},
        )


def validation_message(errors: list[dict[str, Any]]) -> tuple[str, str | None]:
    """Turn Pydantic validation errors into a short, human sentence."""

    if not errors:
        return (
            "Some details in the form are missing or invalid.",
            "Check the highlighted fields and try again.",
        )
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    raw_message = str(first.get("msg", "Invalid value"))
    friendly_fields = {
        "text": "the notice text",
        "language": "the selected language",
        "target_language": "the selected language",
        "source_language": "the source language",
        "pace": "the audio speed",
        "filename": "the file",
    }
    field = friendly_fields.get(location, location.replace("_", " ") or "the form")
    return (
        f"Please check {field}. {raw_message}.",
        "Nothing was sent to Sarvam. Correct the form and try again.",
    )
