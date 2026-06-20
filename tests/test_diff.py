import datetime as dt

from teefinder.diff import new_availabilities
from teefinder.models import Snapshot, TeeTime


def _tee(time_str, spots=2, club="c", date=dt.date(2026, 6, 27)):
    return TeeTime(club_id=club, date=date, time=dt.time.fromisoformat(time_str), players_available=spots)


def _snap(tees, club="c"):
    return Snapshot(club_id=club, scraped_at=dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc), tee_times=tees)


def test_first_snapshot_is_baseline_no_alerts():
    current = _snap([_tee("07:30"), _tee("08:10")])
    assert new_availabilities(None, current) == []


def test_newly_released_slot_is_detected():
    previous = _snap([_tee("07:30")])
    current = _snap([_tee("07:30"), _tee("08:10")])
    new = new_availabilities(previous, current)
    assert [t.time.strftime("%H:%M") for t in new] == ["08:10"]


def test_persisting_slot_is_not_realerted():
    previous = _snap([_tee("07:30")])
    current = _snap([_tee("07:30")])
    assert new_availabilities(previous, current) == []


def test_unavailable_to_available_transition_is_new():
    previous = _snap([_tee("07:30", spots=0)])  # was full
    current = _snap([_tee("07:30", spots=2)])   # now open
    new = new_availabilities(previous, current)
    assert [t.time.strftime("%H:%M") for t in new] == ["07:30"]


def test_removed_slot_does_not_alert():
    previous = _snap([_tee("07:30"), _tee("08:10")])
    current = _snap([_tee("07:30")])
    assert new_availabilities(previous, current) == []
