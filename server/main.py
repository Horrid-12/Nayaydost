"""NyayaDost application entry point.

Run either of these from the project root::

    python main.py
    uvicorn main:app --reload

The server renders one static HTML shell and serves a JSON API. Keeping the
frontend independent of server-side templating means the same build works when
the API is deployed separately and keeps the dependency list small.
"""

from __future__ import annotations

import html
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from server.config import get_settings
from server.errors import AppError, validation_message
from server.models import ErrorDetail, ErrorResponse
from server.routers.api import router as api_router
from server.services.content import get_legal_aid_options, get_guide, get_samples
from server.services.localization import get_locale_store
from server.services.sarvam_service import get_sarvam_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
)
logger = logging.getLogger("nyayadost")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Warm the catalogs so the first citizen request is fast and any malformed
    # data file is reported at startup instead of mid-demo.
    store = get_locale_store()
    samples = get_samples()
    get_legal_aid_options()
    get_guide("generic", "en")
    logger.info(
        "NyayaDost %s started in %s mode with %s locales and %s samples",
        settings.version,
        settings.mode,
        len(store.locales),
        len(samples),
    )
    if not settings.sarvam_configured:
        logger.info(
            "SARVAM_API_KEY is not set: translation, voice, and dictation will use "
            "clearly labelled offline fallbacks."
        )
    app.state.started_at = time.time()
    try:
        yield
    finally:
        if get_sarvam_service.cache_info().currsize:
            get_sarvam_service().close()
        logger.info("NyayaDost stopped")


app = FastAPI(
    title="NyayaDost API",
    description=(
        "Plain-language explanations of Indian legal notices, with vernacular "
        "summaries, deadline tracking, reply drafts, and Sarvam voice support."
    ),
    version=settings.version,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def request_context_and_security(request: Request, call_next: Any) -> Response:
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled error on %s %s [%s]",
            request.method,
            request.url.path,
            request_id,
        )
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "microphone=(self), camera=(), geolocation=(), payment=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "media-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if settings.is_production and request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    logger.info(
        "%s %s -> %s in %.1f ms [%s]",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


app.include_router(api_router)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
@app.get("/guide", include_in_schema=False)
@app.get("/legal-aid", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(
        settings.templates_dir / "index.html",
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/robots.txt", include_in_schema=False)
def robots() -> PlainTextResponse:
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nDisallow: /api/\n",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/healthz", include_in_schema=False)
def health_redirect() -> RedirectResponse:
    return RedirectResponse("/api/health", status_code=307)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def _wants_json(request: Request) -> bool:
    path = request.url.path
    if path.startswith("/api/"):
        return True
    accept = request.headers.get("accept", "").lower()
    return "application/json" in accept and "text/html" not in accept


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> Response:
    request_id = getattr(request.state, "request_id", None)
    if _wants_json(request):
        safe_details = _safe_details(details)
        payload = ErrorResponse(
            error=ErrorDetail(
                code=code,
                message=message,
                hint=hint,
                request_id=request_id,
                details=safe_details,
            )
        )
        return JSONResponse(
            status_code=status_code,
            content=payload.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    return _error_page(
        status_code=status_code,
        message=message,
        hint=hint,
        request_id=request_id,
    )


def _safe_details(
    details: dict[str, Any] | None,
) -> dict[str, str | int | float | bool | None] | None:
    if not details:
        return None
    cleaned: dict[str, str | int | float | bool | None] = {}
    for key, value in details.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            cleaned[str(key)] = value
        else:
            cleaned[str(key)] = str(value)
    return cleaned or None


def _error_page(
    *,
    status_code: int,
    message: str,
    hint: str | None,
    request_id: str | None,
) -> HTMLResponse:
    title = {
        400: "That request needs a small correction",
        404: "That page could not be found",
        413: "That file is too large",
        422: "Some details need attention",
        429: "Please wait a moment",
        500: "Something went wrong on our side",
        503: "The service is taking a short break",
    }.get(status_code, "Something needs attention")

    template_path = settings.templates_dir / "error.html"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError:
        template = (
            "<!doctype html><html><body><h1>{{TITLE}}</h1>"
            "<p>{{MESSAGE}}</p><p>{{HINT}}</p><p>{{REQUEST_ID}}</p>"
            "<a href='/'>Return to NyayaDost</a></body></html>"
        )
    replacements = {
        "{{STATUS}}": str(status_code),
        "{{TITLE}}": html.escape(title),
        "{{MESSAGE}}": html.escape(message),
        "{{HINT}}": html.escape(hint or ""),
        "{{REQUEST_ID}}": html.escape(request_id or ""),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return HTMLResponse(
        template,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> Response:
    logger.info(
        "Expected error %s on %s [%s]: %s",
        exc.code,
        request.url.path,
        getattr(request.state, "request_id", "-"),
        exc.message,
    )
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        hint=exc.hint,
        details=exc.details,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:
    message, hint = validation_message(exc.errors())
    return _error_response(
        request,
        status_code=422,
        code="validation_error",
        message=message,
        hint=hint,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(
    request: Request, exc: StarletteHTTPException
) -> Response:
    status_code = exc.status_code
    if status_code == 404:
        message = "We could not find that page."
        hint = "Return to the home page and try again."
        code = "not_found"
    elif status_code == 405:
        message = "That action is not allowed here."
        hint = "Use the buttons in the app, or return to the home page."
        code = "method_not_allowed"
    elif status_code == 413:
        message = "That upload is too large."
        hint = "Choose a smaller file, or paste the text instead."
        code = "payload_too_large"
    else:
        message = str(exc.detail) if exc.detail else "The request could not be completed."
        hint = "Please try again. If it keeps happening, use the contact details in the footer."
        code = "http_error"
    return _error_response(
        request,
        status_code=status_code,
        code=code,
        message=message,
        hint=hint,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
    logger.exception(
        "Unhandled exception on %s %s [%s]",
        request.method,
        request.url.path,
        getattr(request.state, "request_id", "-"),
    )
    return _error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Something went wrong while preparing your explanation.",
        hint=(
            "Your document was not saved. Please try again. If the problem "
            "continues, paste the notice text instead of uploading a PDF."
        ),
    )


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
