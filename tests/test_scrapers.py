import datetime as dt
from pathlib import Path

from teefinder.config import ClubConfig
from teefinder.scrapers import build_scraper
from teefinder.scrapers.fixture import FixtureScraper
from teefinder.scrapers.miclub import MiClubScraper

FIXTURES = Path(__file__).parent / "fixtures"


def test_registry_builds_correct_scraper():
    club = ClubConfig(id="demo", name="Demo", platform="fixture", url="x")
    assert isinstance(build_scraper(club), FixtureScraper)


def test_unknown_platform_raises():
    club = ClubConfig(id="x", name="X", platform="nope", url="x")
    try:
        build_scraper(club)
    except ValueError as e:
        assert "unknown platform" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_fixture_scraper_reads_slots():
    club = ClubConfig(
        id="demo", name="Demo", platform="fixture", url=str(FIXTURES / "demo_slots.json")
    )
    # Large lookahead so the fixed fixture dates are within the horizon.
    tees = FixtureScraper(club).scrape(lookahead_days=100000)
    assert len(tees) == 3
    assert tees[0].time == dt.time(7, 30)
    assert tees[0].players_available == 2
    assert all(t.club_id == "demo" for t in tees)


# Real saved Wakehurst (MiClub) pages. The calendar fixture's week starts at
# 2026-06-20; 18-hole (feeGroupId 1510657214) is Not Available on 20/21 June and
# available from 22 June. The timesheet fixture is Mon 2026-06-22, 18 holes.
_MICLUB_CLUB = ClubConfig(
    id="wakehurst",
    name="Wakehurst",
    platform="miclub",
    url="https://www.wakehurstgolf.com.au/guests/bookings/ViewPublicCalendar.msp?booking_resource_id=3000000",
    options={"booking_resource_id": "3000000"},
)


def test_miclub_resource_id_parsed_from_url_when_not_in_options():
    club = ClubConfig(
        id="w", name="W", platform="miclub",
        url="https://x.com/guests/bookings/ViewPublicCalendar.msp?booking_resource_id=3000000",
    )
    assert MiClubScraper(club)._resource_id() == "3000000"
    assert MiClubScraper(club)._base_url() == "https://x.com"


def test_miclub_parse_calendar_finds_available_days_and_skips_not_available():
    html = (FIXTURES / "miclub_calendar.html").read_text(encoding="utf-8")
    cells = MiClubScraper(_MICLUB_CLUB).parse_calendar(html)
    pairs = {(d, fg) for d, fg, _price in cells}

    # 18-hole Monday 22 June is open, at $70.00.
    assert (dt.date(2026, 6, 22), "1510657214") in pairs
    price = next(p for d, fg, p in cells if d == dt.date(2026, 6, 22) and fg == "1510657214")
    assert price == "$70.00"
    # 18-hole today/Sunday were "Not Available" -> not returned.
    assert (dt.date(2026, 6, 20), "1510657214") not in pairs


def test_miclub_parse_timesheet_counts_available_cells():
    html = (FIXTURES / "miclub_timesheet.html").read_text(encoding="utf-8")
    date = dt.date(2026, 6, 22)
    tees = MiClubScraper(_MICLUB_CLUB).parse_timesheet(
        html, date, booking_url="https://book", price="$70.00"
    )
    by_time = {t.time.strftime("%H:%M"): t for t in tees}

    # 10:46 has 2 of 4 cells available; 11:26 is wide open (4).
    assert by_time["10:46"].players_available == 2
    assert by_time["11:26"].players_available == 4
    # Every returned slot has at least one open spot, capped at the 4 player cells.
    assert tees and all(1 <= t.players_available <= 4 for t in tees)
    assert by_time["10:46"].price == "$70.00"
    assert by_time["10:46"].booking_url == "https://book"
    assert by_time["10:46"].date == date


def _calendar_html(date_str, fee_groups):
    cells = "".join(
        f'<div class="cell" onclick="redirectToTimesheet(\'{fg}\',\'{date_str}\');">'
        f'<p class="price">{price}</p></div>'
        for fg, price in fee_groups
    )
    return f"<html><body>{cells}</body></html>"


def _timesheet_html(rows):
    # rows: list of (time_label, n_available, n_taken)
    body = []
    for label, n_avail, n_taken in rows:
        cells = '<div class="cell cell-available"></div>' * n_avail
        cells += '<div class="cell cell-taken"></div>' * n_taken
        body.append(
            f'<div class="row row-time"><div class="time-wrapper"><h3>{label}</h3></div>{cells}</div>'
        )
    return f"<html><body>{''.join(body)}</body></html>"


def test_miclub_merges_sessions_across_fee_groups(monkeypatch):
    """Eastlake-style layout: one day split across several 18-hole fee groups
    (sessions/pricing tiers). The scraper must fetch every fee group and merge
    them by tee time, keeping the most open spots when a time repeats."""
    club = ClubConfig(
        id="eastlake", name="Eastlake", platform="miclub",
        url="https://eastlake.example.com/guests/bookings/ViewPublicCalendar.msp",
        options={"booking_resource_id": "3000000"},
    )
    scraper = MiClubScraper(club)
    target = (dt.date.today() + dt.timedelta(days=3)).isoformat()

    # Fee group A: morning session. Fee group B: a later session that ALSO lists
    # the same 09:00 time but with more spots open.
    timesheets = {
        "111": _timesheet_html([("09:00 am", 1, 3)]),                 # 09:00 -> 1 spot
        "222": _timesheet_html([("09:00 am", 3, 1), ("01:30 pm", 2, 2)]),  # 09:00 -> 3, 13:30 -> 2
    }

    def fake_get(self, session, url, params):
        if "feeGroupId" in params:
            assert params["selectedDate"] == target
            return timesheets[params["feeGroupId"]]
        return _calendar_html(target, [("111", "$50.00"), ("222", "$80.00")])

    monkeypatch.setattr(MiClubScraper, "_get", fake_get)
    tees = {t.time.strftime("%H:%M"): t for t in scraper.scrape(lookahead_days=14)}

    assert set(tees) == {"09:00", "13:30"}      # both sessions merged
    assert tees["09:00"].players_available == 3  # max spots across fee groups wins
    assert tees["13:30"].players_available == 2
