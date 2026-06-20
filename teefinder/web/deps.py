"""Shared web dependencies: config/db access, templates, current user."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from fastapi.templating import Jinja2Templates

from teefinder.accounts import UserStore
from teefinder.config import Config, UserConfig
from teefinder.storage import Storage


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def get_user_store(request: Request) -> Iterator[UserStore]:
    store = UserStore(request.app.state.config.global_.database_path)
    try:
        yield store
    finally:
        store.close()


def get_storage(request: Request) -> Iterator[Storage]:
    storage = Storage(request.app.state.config.global_.database_path)
    try:
        yield storage
    finally:
        storage.close()


def get_current_user(request: Request) -> UserConfig | None:
    """The logged-in user (from the session), or None."""
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    store = UserStore(request.app.state.config.global_.database_path)
    try:
        return store.get_by_id(user_id)
    finally:
        store.close()


class RequireLogin(Exception):
    """Raised by ``require_user`` when no one is logged in; redirects to /login."""


def require_user(request: Request) -> UserConfig:
    """Like ``get_current_user`` but redirects to /login when not authenticated."""
    user = get_current_user(request)
    if user is None:
        raise RequireLogin()
    return user
