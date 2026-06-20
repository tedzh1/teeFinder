"""Scraper registry and factory.

Each platform adapter registers itself by name; :func:`build_scraper` returns
the right adapter for a club based on its ``platform`` field.
"""

from __future__ import annotations

from teefinder.config import ClubConfig
from teefinder.scrapers.base import BaseScraper
from teefinder.scrapers.fixture import FixtureScraper
from teefinder.scrapers.miclub import MiClubScraper

# platform name -> scraper class
REGISTRY: dict[str, type[BaseScraper]] = {
    FixtureScraper.platform: FixtureScraper,
    MiClubScraper.platform: MiClubScraper,
}


def build_scraper(club: ClubConfig) -> BaseScraper:
    try:
        scraper_cls = REGISTRY[club.platform]
    except KeyError as exc:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        raise ValueError(
            f"Club {club.id!r} uses unknown platform {club.platform!r}. "
            f"Known platforms: {known}."
        ) from exc
    return scraper_cls(club)


__all__ = ["REGISTRY", "build_scraper", "BaseScraper"]
