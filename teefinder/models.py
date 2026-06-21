"""Common snapshot schema shared by every scraper, plus fingerprinting.

Every scraper, regardless of booking platform, must emit ``TeeTime`` objects.
This keeps storage, diffing and matching completely platform-agnostic.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field


def make_fingerprint(club_id: str, date: dt.date, time: dt.time) -> str:
    """Stable identity for a tee slot: hash of (club, date, time).

    The fingerprint is what diff/dedup compare on, so it must NOT depend on
    volatile fields like price or spots-available.
    """
    raw = f"{club_id}|{date.isoformat()}|{time.strftime('%H:%M')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TeeTime:
    """A single bookable tee slot at a point in time."""

    club_id: str
    date: dt.date
    time: dt.time
    players_available: int | None = None
    price: str | None = None
    booking_url: str | None = None
    # What the booking is, supplied per-connector (e.g. MiClub fee-group name:
    # "18 Holes", "9 Holes", "18 Holes + Cart"). Descriptive only — NOT part of
    # the fingerprint, so changing its wording never re-triggers alerts.
    title: str | None = None
    fingerprint: str = field(default="")

    def __post_init__(self) -> None:
        # Allow callers to omit the fingerprint; derive it deterministically.
        if not self.fingerprint:
            object.__setattr__(
                self,
                "fingerprint",
                make_fingerprint(self.club_id, self.date, self.time),
            )

    @property
    def is_available(self) -> bool:
        """A slot counts as available if it's listed with spots open.

        Sites that don't expose a spot count report ``None`` — we treat the
        mere presence of the slot in the scrape as availability.
        """
        return self.players_available is None or self.players_available > 0

    @property
    def weekday(self) -> int:
        """Monday=0 .. Sunday=6, matching ``date.weekday()``."""
        return self.date.weekday()


@dataclass
class Snapshot:
    """The full set of tee times scraped from one club at one moment."""

    club_id: str
    scraped_at: dt.datetime
    tee_times: list[TeeTime] = field(default_factory=list)

    def available(self) -> list[TeeTime]:
        return [t for t in self.tee_times if t.is_available]
