import datetime as dt

from teefinder.config import Preference, UserConfig
from teefinder.matching import matches_for_user, matches_user
from teefinder.models import TeeTime

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
