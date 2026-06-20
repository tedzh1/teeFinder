import datetime as dt

from teefinder.config import Config, Preference, UserConfig
from teefinder.matching import available_matching_for_user, matches_for_user, matches_user
from teefinder.models import Snapshot, TeeTime
from teefinder.storage import Storage

# 2026-06-27 is a Saturday; 2026-06-24 is a Wednesday; 2026-06-29 is a Monday.
SAT = dt.date(2026, 6, 27)
WED = dt.date(2026, 6, 24)
MON = dt.date(2026, 6, 29)


def _user(clubs=None, min_players=1):
    return UserConfig(
        name="Ted",
        email="ted@example.com",
        clubs=clubs or [],
        min_players=min_players,
        preferences=[
            Preference.model_validate(
                {"days": ["Saturday", "Sunday"], "time_ranges": [{"start": "06:00", "end": "10:00"}]}
            ),
            Preference.model_validate(
                {"days": ["Wednesday"], "time_ranges": [{"start": "15:00", "end": "18:00"}]}
            ),
        ],
    )


def _tee(date, time_str, club="club-a", players_available=None):
    return TeeTime(
        club_id=club,
        date=date,
        time=dt.time.fromisoformat(time_str),
        players_available=players_available,
    )


def test_matches_within_day_and_time_window():
    assert matches_user(_tee(SAT, "07:30"), _user()) is True


def test_rejects_time_outside_window():
    assert matches_user(_tee(SAT, "11:00"), _user()) is False


def test_rejects_wrong_day():
    assert matches_user(_tee(MON, "07:30"), _user()) is False


def test_second_preference_block_applies():
    assert matches_user(_tee(WED, "16:00"), _user()) is True
    assert matches_user(_tee(WED, "07:30"), _user()) is False  # wrong window for Wed


def test_time_range_is_start_inclusive_end_exclusive():
    assert matches_user(_tee(SAT, "06:00"), _user()) is True
    assert matches_user(_tee(SAT, "10:00"), _user()) is False


def test_club_subscription_filters():
    user = _user(clubs=["club-b"])
    assert matches_user(_tee(SAT, "07:30", club="club-a"), user) is False
    assert matches_user(_tee(SAT, "07:30", club="club-b"), user) is True


def test_matches_for_user_sorts_results():
    user = _user()
    tees = [_tee(SAT, "09:00"), _tee(SAT, "06:30"), _tee(WED, "16:00")]
    result = matches_for_user(tees, user)
    assert [t.time.strftime("%H:%M") for t in result] == ["16:00", "06:30", "09:00"]


def test_min_players_omits_slots_with_too_few_spots():
    user = _user(min_players=3)
    assert matches_user(_tee(SAT, "07:30", players_available=2), user) is False
    assert matches_user(_tee(SAT, "07:30", players_available=3), user) is True
    assert matches_user(_tee(SAT, "07:30", players_available=4), user) is True


def test_min_players_default_one_allows_single_spot():
    user = _user()  # min_players defaults to 1
    assert matches_user(_tee(SAT, "07:30", players_available=1), user) is True


def test_min_players_keeps_slot_when_spot_count_unknown():
    # players_available=None (site didn't expose a count) -> don't hide it.
    user = _user(min_players=4)
    assert matches_user(_tee(SAT, "07:30", players_available=None), user) is True


def test_min_players_validated_between_one_and_four():
    import pytest

    with pytest.raises(Exception):
        _user(min_players=0)
    with pytest.raises(Exception):
        _user(min_players=5)


def test_available_matching_for_user_uses_latest_snapshots(tmp_path):
    cfg = Config.model_validate(
        {
            "global": {"scrape_interval_minutes": 5, "database_path": str(tmp_path / "tf.db")},
            "email": {"username": "a@b.com", "from_address": "a@b.com"},
            "clubs": [
                {"id": "club-a", "name": "A", "platform": "fixture", "url": "x"},
                {"id": "club-b", "name": "B", "platform": "fixture", "url": "y"},
            ],
        }
    )
    user = _user(clubs=["club-a"])  # subscribed only to club-a, Sat 06-10 / Wed 15-18

    with Storage(tmp_path / "tf.db") as storage:
        # club-a: one matching (Sat 07:30) + one not (Sat 12:00) + one full (Sat 08:00, 0 spots)
        storage.save_snapshot(Snapshot(
            club_id="club-a",
            scraped_at=dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc),
            tee_times=[
                _tee(SAT, "07:30", club="club-a", players_available=2),
                _tee(SAT, "12:00", club="club-a", players_available=2),
                _tee(SAT, "08:00", club="club-a", players_available=0),
            ],
        ))
        # club-b would match on time/day but the user isn't subscribed to it.
        storage.save_snapshot(Snapshot(
            club_id="club-b",
            scraped_at=dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc),
            tee_times=[_tee(SAT, "07:30", club="club-b", players_available=2)],
        ))

        result = available_matching_for_user(cfg, storage, user)

    assert [(t.club_id, t.time.strftime("%H:%M")) for t in result] == [("club-a", "07:30")]
