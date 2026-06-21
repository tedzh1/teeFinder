import datetime as dt
import os

import pytest
from starlette.testclient import TestClient

from teefinder.config import Config
from teefinder.models import Snapshot, TeeTime
from teefinder.storage import Storage
from teefinder.web.app import create_app

# Stable secret so session cookies are valid across the test app's lifetime.
os.environ.setdefault("TEEFINDER_SECRET_KEY", "test-secret-key")

SAT = dt.date(2026, 6, 27)  # a Saturday


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "tf.db"
    cfg = Config.model_validate(
        {
            "global": {"scrape_interval_minutes": 5, "database_path": str(db)},
            "email": {"username": "a@b.com", "from_address": "a@b.com"},
            "clubs": [{"id": "demo", "name": "Demo Club", "platform": "fixture", "url": "x"}],
        }
    )
    # Seed a snapshot with a Saturday-morning slot the dashboard can show.
    with Storage(db) as storage:
        storage.save_snapshot(Snapshot(
            club_id="demo",
            scraped_at=dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc),
            tee_times=[
                TeeTime(club_id="demo", date=SAT, time=dt.time(7, 30),
                        players_available=3, price="$45", title="18 Holes",
                        booking_url="https://book/1"),
                TeeTime(club_id="demo", date=SAT, time=dt.time(14, 0),  # afternoon, won't match
                        players_available=3),
            ],
        ))
    return TestClient(create_app(cfg))


def _register(client, email="ted@example.com", password="supersecret", name="Ted"):
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def test_register_login_logout_flow(client):
    # Register -> redirected to dashboard, logged in.
    r = _register(client)
    assert r.status_code == 200
    assert "Available tee times" in r.text

    # Logout -> dashboard now redirects to login.
    client.post("/logout")
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # Log back in.
    r = client.post("/login", data={"email": "ted@example.com", "password": "supersecret"})
    assert r.status_code == 200
    assert "Available tee times" in r.text


def test_duplicate_registration_shows_error(client):
    _register(client)
    client.post("/logout")
    r = _register(client)  # same email again
    assert r.status_code == 400
    assert "already exists" in r.text


def test_login_with_wrong_password_fails(client):
    _register(client)
    client.post("/logout")
    r = client.post("/login", data={"email": "ted@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid email or password" in r.text


def test_preferences_drive_dashboard_matches(client):
    _register(client)

    # Fresh account has no preference blocks -> nothing matches yet.
    r = client.get("/dashboard")
    assert "07:30" not in r.text

    # Set Saturday 06:00-10:00 for the demo club.
    r = client.post(
        "/preferences",
        data={
            "name": "Ted",
            "min_players": "1",
            "clubs": "demo",
            "days_0": "Saturday",
            "start_0": "06:00",
            "end_0": "10:00",
        },
    )
    assert r.status_code == 200
    assert "Preferences saved" in r.text

    # Dashboard now shows the matching 07:30 slot (but not the 14:00 one).
    r = client.get("/dashboard")
    assert "07:30" in r.text
    assert "Demo Club" in r.text
    assert "18 Holes" in r.text          # booking title is shown
    assert "14:00" not in r.text
    assert "https://book/1" in r.text


def test_min_players_filter_applies_on_dashboard(client):
    _register(client)
    # Require 4 spots; the 07:30 slot only has 3 -> excluded.
    client.post(
        "/preferences",
        data={
            "name": "Ted", "min_players": "4", "clubs": "demo",
            "days_0": "Saturday", "start_0": "06:00", "end_0": "10:00",
        },
    )
    r = client.get("/dashboard")
    assert "07:30" not in r.text


def test_date_range_filters_dashboard(client):
    # The seeded slot is on Saturday 2026-06-27.
    _register(client)
    base = {"name": "Ted", "min_players": "1", "clubs": "demo",
            "days_0": "Saturday", "start_0": "06:00", "end_0": "10:00"}

    # A July date window excludes the June slot.
    client.post("/preferences", data={**base, "start_date_0": "2026-07-01", "end_date_0": "2026-07-31"})
    assert "07:30" not in client.get("/dashboard").text

    # A window covering late June includes it again.
    client.post("/preferences", data={**base, "start_date_0": "2026-06-01", "end_date_0": "2026-06-30"})
    assert "07:30" in client.get("/dashboard").text

    # The form renders date inputs and prefills the saved window.
    form = client.get("/preferences").text
    assert 'type="date"' in form
    assert 'value="2026-06-01"' in form
    assert 'value="2026-06-30"' in form


def test_invalid_preference_shows_error(client):
    _register(client)
    # end before start -> validation error surfaced, not a crash.
    r = client.post(
        "/preferences",
        data={
            "name": "Ted", "min_players": "1", "clubs": "demo",
            "days_0": "Saturday", "start_0": "10:00", "end_0": "06:00",
        },
    )
    assert r.status_code == 400
    assert "Could not save" in r.text


def test_dashboard_requires_login(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
