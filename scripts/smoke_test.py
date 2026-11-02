#!/usr/bin/env python3
"""End-to-end smoke test for NyayaDost.

By default the script starts a temporary Uvicorn server on a free localhost
port, runs the checks, and shuts the server down. To test an already-running
instance instead:

    ./venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8000

The test is deliberately dependency-light: it uses ``requests``, which is part
of the runtime requirements, and the standard library. A non-zero exit code
means at least one check failed.
"""

from __future__ import annotations

import argparse
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import requests

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PDF = ROOT / "tests" / "fixtures" / "sample_notice.pdf"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def temporary_server() -> Iterator[str]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "test",
            "APP_DEBUG": "false",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "RATE_LIMIT_ANALYZE": "1000",
            "RATE_LIMIT_VOICE": "1000",
            "PYTHONUNBUFFERED": "1",
        }
    )
    log = tempfile.NamedTemporaryFile(
        mode="w+", prefix="nyayadost-smoke-", suffix=".log", delete=False
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 25
        last_error: Exception | None = None
        while time.time() < deadline:
            if process.poll() is not None:
                break
            try:
                response = requests.get(f"{base_url}/api/health", timeout=1)
                if response.status_code == 200:
                    break
            except requests.RequestException as exc:
                last_error = exc
            time.sleep(0.2)
        else:
            raise RuntimeError("The temporary server did not become ready in time.")
        if process.poll() is not None:
            log.flush()
            log.seek(0)
            output = log.read()
            raise RuntimeError(
                "The temporary server exited before becoming ready.\n" + output
            )
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        try:
            os.unlink(log.name)
        except OSError:
            pass


class Checker:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.failures: list[str] = []
        self.passed = 0

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.session.get(self.base_url + path, timeout=30, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.session.post(self.base_url + path, timeout=60, **kwargs)

    def check(self, name: str, function: Any) -> None:
        try:
            function()
        except Exception as exc:
            self.failures.append(f"{name}: {exc}")
            print(f"FAIL  {name}\n      {exc}")
        else:
            self.passed += 1
            print(f"PASS  {name}")

    def json(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AssertionError(
                f"expected JSON, got {response.status_code} {response.text[:160]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise AssertionError(f"expected a JSON object, got {type(payload).__name__}")
        return payload


def assert_status(response: requests.Response, status: int) -> None:
    if response.status_code != status:
        raise AssertionError(
            f"expected HTTP {status}, got {response.status_code}: {response.text[:240]}"
        )


def assert_header(response: requests.Response, name: str, contains: str) -> None:
    value = response.headers.get(name, "")
    if contains not in value:
        raise AssertionError(f"{name} does not contain {contains!r}: {value!r}")


def run_checks(base_url: str) -> int:
    checker = Checker(base_url)

    def home_page() -> None:
        response = checker.get("/")
        assert_status(response, 200)
        assert_header(response, "Content-Type", "text/html")
        assert_header(response, "X-Content-Type-Options", "nosniff")
        assert_header(response, "X-Frame-Options", "DENY")
        assert_header(response, "Content-Security-Policy", "default-src 'self'")
        assert_header(response, "Content-Security-Policy", "frame-src 'self' blob:")
        if "NyayaDost" not in response.text:
            raise AssertionError("home page does not contain the NyayaDost brand")
        if not response.headers.get("X-Request-ID", "").startswith("req_"):
            raise AssertionError("home page is missing a request ID")

    def static_assets() -> None:
        css = checker.get("/static/css/styles.css")
        assert_status(css, 200)
        if "--stamp" not in css.text:
            raise AssertionError("CSS design tokens are missing")
        script = checker.get("/static/js/app.js")
        assert_status(script, 200)
        if "function analyzeNotice" not in script.text:
            raise AssertionError("frontend analysis function is missing")

    def health() -> None:
        response = checker.get("/api/health")
        assert_status(response, 200)
        payload = checker.json(response)
        if payload.get("status") != "ok":
            raise AssertionError(f"unexpected health status: {payload.get('status')}")
        if set(payload.get("locales", [])) != {"en", "hi", "mr", "gu", "ta", "te", "bn"}:
            raise AssertionError(f"unexpected locales: {payload.get('locales')}")
        assert_header(response, "Cache-Control", "no-store")

    def bootstrap() -> None:
        response = checker.get("/api/bootstrap", params={"language": "mr"})
        assert_status(response, 200)
        payload = checker.json(response)
        if len(payload.get("languages", [])) != 7:
            raise AssertionError("expected seven language options")
        if len(payload.get("samples", [])) < 9:
            raise AssertionError("expected at least nine sample notices")
        if len(payload.get("notice_types", [])) != 9:
            raise AssertionError("expected nine notice types")
        if payload.get("mode") != "offline-demo":
            raise AssertionError(f"expected offline-demo mode, got {payload.get('mode')}")
        if not payload.get("limits", {}).get("max_upload_mb"):
            raise AssertionError("upload limits are missing from bootstrap")

    def analyze_marathi() -> None:
        payload = checker.json(checker.get("/api/bootstrap"))
        sample = payload["samples"][0]
        response = checker.post(
            "/api/analyze",
            json={
                "text": sample["text"],
                "language": "mr",
                "source_name": sample["title"],
            },
        )
        assert_status(response, 200)
        result = checker.json(response)
        if result.get("notice_type") != "cheque_bounce":
            raise AssertionError(f"unexpected notice type: {result.get('notice_type')}")
        if result.get("language") != "mr":
            raise AssertionError("response language is not Marathi")
        if result.get("mode") != "offline":
            raise AssertionError("offline analysis should report offline mode")
        if len(result.get("steps", [])) < 5:
            raise AssertionError("expected at least five next steps")
        if not result.get("deadlines"):
            raise AssertionError("expected at least one deadline")
        if "धनादेश" not in result.get("summary_body", ""):
            raise AssertionError("Marathi summary does not contain the localized term")
        if not result.get("tts_text") or not result.get("reply", {}).get("template"):
            raise AssertionError("TTS text or reply draft is missing")

    def analyze_validation_error() -> None:
        response = checker.post(
            "/api/analyze", json={"text": "too short", "language": "en"}
        )
        assert_status(response, 422)
        payload = checker.json(response)
        if payload.get("ok") is not False:
            raise AssertionError("error response should include ok=false")
        error = payload.get("error", {})
        if error.get("code") != "validation_error":
            raise AssertionError(f"unexpected error code: {error.get('code')}")
        if not error.get("request_id"):
            raise AssertionError("error response is missing a request ID")

    def unsupported_language() -> None:
        response = checker.get("/api/bootstrap", params={"language": "xx"})
        assert_status(response, 422)
        payload = checker.json(response)
        if payload.get("error", {}).get("code") != "unsupported_language":
            raise AssertionError(f"unexpected error: {payload}")

    def analyze_pdf() -> None:
        if not FIXTURE_PDF.exists():
            raise AssertionError(f"missing fixture: {FIXTURE_PDF}")
        response = checker.post(
            "/api/analyze/upload",
            files={
                "file": (
                    "sample_notice.pdf",
                    FIXTURE_PDF.read_bytes(),
                    "application/pdf",
                )
            },
            data={"language": "en"},
        )
        assert_status(response, 200)
        result = checker.json(response)
        if result.get("source", {}).get("kind") != "pdf":
            raise AssertionError("PDF source metadata is missing")
        if result.get("notice_type") != "cheque_bounce":
            raise AssertionError("PDF notice was not recognized as a cheque bounce")
        amount = next(
            (fact["value"] for fact in result.get("facts", []) if fact["label"] == "Amount mentioned"),
            "",
        )
        if amount != "₹1,85,000":
            raise AssertionError(f"unexpected amount extracted from PDF: {amount!r}")

    def reject_non_pdf_upload() -> None:
        response = checker.post(
            "/api/analyze/upload",
            files={"file": ("notice.pdf", b"not a PDF", "application/pdf")},
            data={"language": "en"},
        )
        assert_status(response, 422)
        payload = checker.json(response)
        if payload.get("error", {}).get("code") != "not_pdf":
            raise AssertionError(f"unexpected error: {payload}")

    def reject_unsupported_upload_type() -> None:
        response = checker.post(
            "/api/analyze/upload",
            files={"file": ("notice.txt", b"plain text", "text/plain")},
            data={"language": "en"},
        )
        assert_status(response, 422)
        payload = checker.json(response)
        if payload.get("error", {}).get("code") != "unsupported_file":
            raise AssertionError(f"unexpected error: {payload}")

    def guide() -> None:
        response = checker.get(
            "/api/guide/cheque_bounce", params={"language": "ta"}
        )
        assert_status(response, 200)
        payload = checker.json(response)
        if payload.get("language") != "ta":
            raise AssertionError("guide language is not Tamil")
        if not payload.get("native_summary") or not payload.get("steps"):
            raise AssertionError("guide content is incomplete")
        missing = checker.get("/api/guide/not_a_notice", params={"language": "en"})
        assert_status(missing, 404)
        if checker.json(missing).get("error", {}).get("code") != "guide_not_found":
            raise AssertionError("unknown guide did not return guide_not_found")

    def legal_aid() -> None:
        options = checker.get("/api/legal-aid/options")
        assert_status(options, 200)
        payload = checker.json(options)
        if len(payload.get("states", [])) < 30:
            raise AssertionError("legal-aid directory is unexpectedly small")
        matched = checker.get(
            "/api/legal-aid",
            params={"state": "Maharashtra", "district": "Pune"},
        )
        assert_status(matched, 200)
        if not checker.json(matched).get("matched"):
            raise AssertionError("Pune should match the demo DLSA directory")
        approximate = checker.get(
            "/api/legal-aid",
            params={"state": "Maharashtra", "district": "A Made Up District"},
        )
        assert_status(approximate, 200)
        if checker.json(approximate).get("matched"):
            raise AssertionError("unknown district should not be reported as matched")

    def translate() -> None:
        response = checker.post(
            "/api/translate",
            json={
                "text": "This is a legal notice about an unpaid cheque. Reply within 15 days.",
                "target_language": "mr",
            },
        )
        assert_status(response, 200)
        payload = checker.json(response)
        if payload.get("mode") != "offline" or not payload.get("is_mock"):
            raise AssertionError("expected the offline translation fallback")
        if not payload.get("translated_text") or not payload.get("warning"):
            raise AssertionError("translation fallback is missing text or warning")

    def tts() -> None:
        response = checker.post(
            "/api/tts",
            json={
                "text": "ही नोटिस धनादेशाबद्दल आहे. पंधरा दिवसांत उत्तर द्या.",
                "language": "mr",
            },
        )
        assert_status(response, 200)
        payload = checker.json(response)
        audio = base64.b64decode(payload.get("audio_base64", ""))
        if not audio.startswith(b"RIFF"):
            raise AssertionError("TTS fallback did not return a WAV file")
        if payload.get("mime_type") != "audio/wav" or payload.get("duration_seconds", 0) <= 0:
            raise AssertionError("TTS metadata is incomplete")
        if not payload.get("is_mock"):
            raise AssertionError("offline TTS should be labelled as mock")

    def stt() -> None:
        response = checker.post(
            "/api/stt",
            files={"file": ("dictation.webm", b"fake-webm-bytes", "audio/webm")},
            data={"language": "hi"},
        )
        assert_status(response, 200)
        payload = checker.json(response)
        if payload.get("mode") != "offline" or not payload.get("is_mock"):
            raise AssertionError("expected the offline STT fallback")
        if not payload.get("transcript") or not payload.get("warning"):
            raise AssertionError("STT fallback is missing a transcript or warning")

    def error_pages() -> None:
        page = checker.get("/definitely-not-a-page")
        assert_status(page, 404)
        assert_header(page, "Content-Type", "text/html")
        if "could not find" not in page.text.lower():
            raise AssertionError("HTML 404 page is not citizen-friendly")
        api = checker.get("/api/definitely-not-a-page")
        assert_status(api, 404)
        payload = checker.json(api)
        if payload.get("error", {}).get("code") != "not_found":
            raise AssertionError("API 404 did not return not_found")

    checks = [
        ("home page and security headers", home_page),
        ("static CSS and JavaScript", static_assets),
        ("health endpoint", health),
        ("bootstrap data", bootstrap),
        ("Marathi notice analysis", analyze_marathi),
        ("analyze validation error", analyze_validation_error),
        ("unsupported language", unsupported_language),
        ("PDF upload and extraction", analyze_pdf),
        ("non-PDF upload rejection", reject_non_pdf_upload),
        ("unsupported upload type", reject_unsupported_upload_type),
        ("NyayaGuide", guide),
        ("Legal Aid Finder", legal_aid),
        ("offline translation", translate),
        ("offline text-to-speech", tts),
        ("offline speech-to-text", stt),
        ("HTML and JSON error pages", error_pages),
    ]

    print(f"NyayaDost smoke test against {base_url}")
    print("-" * 64)
    for name, function in checks:
        checker.check(name, function)
    print("-" * 64)
    print(f"{checker.passed} passed, {len(checker.failures)} failed")
    if checker.failures:
        print("\nFailures:")
        for failure in checker.failures:
            print(f"  - {failure}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NyayaDost end-to-end checks.")
    parser.add_argument(
        "--base-url",
        help="Test an already-running server instead of starting a temporary one.",
    )
    args = parser.parse_args()

    if args.base_url:
        return run_checks(args.base_url)
    with temporary_server() as base_url:
        return run_checks(base_url)


if __name__ == "__main__":
    raise SystemExit(main())
