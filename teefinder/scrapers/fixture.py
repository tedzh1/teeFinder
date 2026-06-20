"""Offline scraper that reads tee times from a local JSON file.

Used for development, tests and the offline end-to-end verification flow. The
club's ``url`` is treated as a path to a JSON file shaped like::

    [
      {"date": "2026-06-27", "time": "07:30", "players_available": 2,
       "price": "$45", "booking_url": "https://..."},
      ...
    ]

Editing that file between runs simulates availability changes without touching
the network.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from teefinder.models import TeeTime
from teefinder.scrapers.base import BaseScraper


class FixtureScraper(BaseScraper):
    platform = "fixture"

    def scrape(self, lookahead_days: int) -> list[TeeTime]:
        path = Path(self.club.url)
        if not path.exists():
            raise FileNotFoundError(f"Fixture file not found: {path}")
        # utf-8-sig tolerates a leading BOM (e.g. files saved by Windows tools).
        raw = json.loads(path.read_text(encoding="utf-8-sig"))

        horizon = dt.date.today() + dt.timedelta(days=lookahead_days)
        tee_times: list[TeeTime] = []
        for entry in raw:
            date = dt.date.fromisoformat(entry["date"])
            if date > horizon:
                continue
            tee_times.append(
                TeeTime(
                    club_id=self.club.id,
                    date=date,
                    time=dt.time.fromisoformat(entry["time"]),
                    players_available=entry.get("players_available"),
                    price=entry.get("price"),
                    booking_url=entry.get("booking_url"),
                )
            )
        return tee_times
