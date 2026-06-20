"""Scraper interface and shared HTTP helpers.

Every booking platform gets a ``BaseScraper`` subclass that turns a club's
booking page into a list of ``TeeTime`` objects in the common schema. Because
the contract is platform-agnostic, one adapter (e.g. MiClub) is reused across
every club on that platform — clubs differ only by URL/options in config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from teefinder.config import ClubConfig
from teefinder.models import TeeTime

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 teeFinder/0.1"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
}


def build_session(total_retries: int = 3, timeout: float = 20.0) -> requests.Session:
    """A requests session with sane retries, headers and a default timeout."""
    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)
    retry = Retry(
        total=total_retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = _TimeoutHTTPAdapter(timeout=timeout, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class _TimeoutHTTPAdapter(HTTPAdapter):
    """Applies a default timeout to every request unless one is given."""

    def __init__(self, timeout: float, *args: object, **kwargs: object) -> None:
        self._timeout = timeout
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):  # type: ignore[override]
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self._timeout
        return super().send(request, **kwargs)


class BaseScraper(ABC):
    """Base class for all platform adapters.

    Subclasses set ``platform`` (the name used in config) and implement
    :meth:`scrape`.
    """

    platform: str = ""

    def __init__(self, club: ClubConfig) -> None:
        self.club = club

    @abstractmethod
    def scrape(self, lookahead_days: int) -> list[TeeTime]:
        """Return all currently-bookable tee times within the horizon."""
        raise NotImplementedError
