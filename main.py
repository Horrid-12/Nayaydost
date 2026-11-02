"""Convenience launcher and ASGI entry point for NyayaDost.

    python main.py
    uvicorn main:app --reload

``main:app`` is re-exported so both launch paths use exactly the same FastAPI
application, middleware, routes, and lifespan hooks.
"""

from __future__ import annotations

import sys

from server.config import get_settings
from server.main import app

__all__ = ["app", "main"]


def main() -> int:
    settings = get_settings()
    try:
        import uvicorn
    except ImportError:
        print(
            "Uvicorn is not installed. Run:\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    print("=" * 64)
    print("  NyayaDost (न्यायदोस्त) — legal notices in plain language")
    print("=" * 64)
    print(f"  Mode      : {settings.mode}")
    print(f"  Address   : http://{settings.host}:{settings.port}")
    print(f"  API docs  : http://{settings.host}:{settings.port}/api/docs")
    if not settings.sarvam_configured:
        print("  Sarvam    : not configured — using labelled offline fallbacks")
    print("  Stop      : press Ctrl+C")
    print("=" * 64)

    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
