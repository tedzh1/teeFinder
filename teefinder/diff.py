"""Snapshot comparison: find tee times that just became available.

A slot is a *new availability* if it is available in the current snapshot but
was absent or unavailable in the previous one. The first snapshot for a club is
a baseline and yields nothing (otherwise everything would look new).
"""

from __future__ import annotations

from teefinder.models import Snapshot, TeeTime


def new_availabilities(
    previous: Snapshot | None, current: Snapshot
) -> list[TeeTime]:
    """Tee times available now that were not available before."""
    current_available = current.available()

    # No prior snapshot -> baseline, nothing is "new".
    if previous is None:
        return []

    previously_available = {t.fingerprint for t in previous.available()}
    return [t for t in current_available if t.fingerprint not in previously_available]
