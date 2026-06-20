import datetime as dt

import pytest

from teefinder.config import Config, load_config

VALID = """
global:
  scrape_interval_minutes: 15
  timezone: Australia/Sydney
  lookahead_weeks: 12
  database_path: ./data/teefinder.db
email:
  username: you@gmail.com
  from_address: you@gmail.com
clubs:
  - id: club-a
    name: Club A
    platform: fixture
    url: ./x.json
users:
  - name: Ted
    email: ted@example.com
    clubs: [club-a]
    preferences:
      - days: [Saturday, Sunday]
        time_ranges:
          - {start: "06:00", end: "10:00"}
"""


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_valid_config(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.global_.scrape_interval_minutes == 15
    assert cfg.global_.lookahead_weeks == 12
    assert cfg.global_.lookahead_days == 84  # 12 weeks
    assert cfg.clubs[0].id == "club-a"
    # Saturday=5, Sunday=6
    assert cfg.users[0].preferences[0].days == [5, 6]
    assert cfg.users[0].preferences[0].time_ranges[0].start == dt.time(6, 0)


def test_unknown_day_rejected(tmp_path):
    bad = VALID.replace("[Saturday, Sunday]", "[Funday]")
    with pytest.raises(Exception):
        load_config(_write(tmp_path, bad))


def test_user_referencing_unknown_club_rejected(tmp_path):
    bad = VALID.replace("clubs: [club-a]\n    preferences", "clubs: [club-z]\n    preferences")
    with pytest.raises(Exception):
        load_config(_write(tmp_path, bad))


def test_time_range_end_must_be_after_start(tmp_path):
    bad = VALID.replace('{start: "06:00", end: "10:00"}', '{start: "10:00", end: "06:00"}')
    with pytest.raises(Exception):
        load_config(_write(tmp_path, bad))


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("CLUB_URL", "./from-env.json")
    text = VALID.replace("url: ./x.json", "url: ${CLUB_URL}")
    cfg = load_config(_write(tmp_path, text))
    assert cfg.clubs[0].url == "./from-env.json"


def test_missing_env_var_raises(tmp_path):
    text = VALID.replace("url: ./x.json", "url: ${DEFINITELY_NOT_SET_VAR}")
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, text))


def test_subscribed_to_defaults_to_all_clubs():
    cfg = Config.model_validate(
        {
            "global": {"scrape_interval_minutes": 5},
            "email": {"username": "a@b.com", "from_address": "a@b.com"},
            "clubs": [{"id": "c1", "name": "C1", "platform": "fixture", "url": "x"}],
            "users": [{"name": "U", "email": "u@x.com", "preferences": []}],
        }
    )
    assert cfg.users[0].subscribed_to("c1") is True
    assert cfg.users[0].subscribed_to("anything") is True
