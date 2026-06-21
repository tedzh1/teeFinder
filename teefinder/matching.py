"""Filter new tee times down to what each user actually wants.

A tee time matches a user when the user is subscribed to its club, has at least
the user's required minimum open spots, AND falls in one of the user's preference
blocks — i.e. on a chosen weekday, within that block's optional date window, and
inside one of its time ranges.
"""

from __future__ import annotations

from teefinder.config import UserConfig
from teefinder.models import TeeTime


def matches_user(tee: TeeTime, user: UserConfig) -> bool:
    if not user.subscribed_to(tee.club_id):
        return False
    # Too few open spots for what the user needs. If the site doesn't expose a
    # count (None), we keep the slot rather than risk hiding a real opening.
    if tee.players_available is not None and tee.players_available < user.min_players:
        return False
    for pref in user.preferences:
        if tee.weekday not in pref.days:
            continue
        if not pref.date_in_range(tee.date):
            continue
        if any(tr.contains(tee.time) for tr in pref.time_ranges):
            return True
    return False


def matches_for_user(tee_times: list[TeeTime], user: UserConfig) -> list[TeeTime]:
    """All tee times (from any club) that match a single user's preferences."""
    matched = [t for t in tee_times if matches_user(t, user)]
    matched.sort(key=lambda t: (t.date, t.time, t.club_id))
    return matched


def available_matching_for_user(config, storage, user: UserConfig) -> list[TeeTime]:
    """Currently-available tee times matching a user, from the latest snapshots.

    Unlike the alert path (which only surfaces *newly* released slots), this
    returns everything bookable right now across the user's subscribed clubs —
    powering the web dashboard. Reuses ``matches_for_user`` for the filtering.
    """
    available: list[TeeTime] = []
    for club in config.clubs:
        if not user.subscribed_to(club.id):
            continue
        snapshot = storage.latest_snapshot(club.id)
        if snapshot is not None:
            available.extend(snapshot.available())
    return matches_for_user(available, user)
