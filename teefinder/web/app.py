"""FastAPI application factory for the teeFinder web frontend."""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from teefinder.config import Config
from teefinder.web import auth_routes, views
from teefinder.web.deps import RequireLogin

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent


def _session_secret() -> str:
    secret = os.environ.get("TEEFINDER_SECRET_KEY")
    if secret:
        return secret
    logger.warning(
        "TEEFINDER_SECRET_KEY not set; using a random ephemeral key. "
        "Sessions will not survive a restart. Set it in .env for production."
    )
    return secrets.token_hex(32)


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="teeFinder")
    app.state.config = config
    app.state.templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(),
        same_site="lax",
        https_only=config.web.secure_cookies,
    )

    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    # Unauthenticated access to a protected page -> send to login.
    @app.exception_handler(RequireLogin)
    async def _redirect_to_login(request: Request, exc: RequireLogin):
        return RedirectResponse("/login", status_code=303)

    app.include_router(auth_routes.router)
    app.include_router(views.router)
    return app
