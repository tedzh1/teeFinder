import json

from teefinder.accounts import UserStore
from teefinder.config import Config, UserConfig
from teefinder.notifier import EmailNotifier
from teefinder.runner import run_cycle
from teefinder.storage import Storage


class RecordingNotifier(EmailNotifier):
    """An EmailNotifier that records sends instead of hitting SMTP."""

    def __init__(self):
        self.sent = []

    def send(self, to_address, subject, text_body, html_body):
        self.sent.append((to_address, subject, text_body))


def _config(fixture_path, db_path):
    return Config.model_validate(
        {
            "global": {"scrape_interval_minutes": 5, "lookahead_weeks": 520, "database_path": str(db_path)},
            "email": {"username": "a@b.com", "from_address": "a@b.com"},
            "web": {"base_url": "https://tee.example.com"},
            "clubs": [{"id": "demo", "name": "Demo", "platform": "fixture", "url": str(fixture_path)}],
        }
    )


def _users():
    # 2026-06-27 is a Saturday -> matches this user's Saturday-morning window.
    return [
        UserConfig.model_validate(
            {
                "name": "Ted",
                "email": "ted@example.com",
                "clubs": ["demo"],
                "preferences": [
                    {"days": ["Saturday"], "time_ranges": [{"start": "06:00", "end": "10:00"}]}
                ],
            }
        )
    ]


def _write_slots(path, slots):
    path.write_text(json.dumps(slots), encoding="utf-8")


def test_full_pipeline_baseline_then_new_then_dedup(tmp_path):
    fixture = tmp_path / "slots.json"
    db = tmp_path / "tf.db"
    cfg = _config(fixture, db)
    users = _users()

    # 1) Baseline run: one slot exists, but first run never alerts.
    _write_slots(fixture, [{"date": "2026-06-27", "time": "07:30", "players_available": 2}])
    notifier = RecordingNotifier()
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, notifier, users=users)
    assert summary["emails_sent"] == 0
    assert notifier.sent == []

    # 2) A new Saturday-morning slot is released -> user is alerted.
    _write_slots(
        fixture,
        [
            {"date": "2026-06-27", "time": "07:30", "players_available": 2},
            {"date": "2026-06-27", "time": "08:10", "players_available": 4},
        ],
    )
    notifier = RecordingNotifier()
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, notifier, users=users)
    assert summary["new_availabilities"] == 1
    assert summary["emails_sent"] == 1
    assert "08:10" in notifier.sent[0][2]
    # The digest links to the dashboard.
    assert "https://tee.example.com/dashboard" in notifier.sent[0][2]

    # 3) Nothing changes -> no re-alert (snapshot diff + sent_alerts dedup).
    notifier = RecordingNotifier()
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, notifier, users=users)
    assert summary["emails_sent"] == 0


def test_slot_outside_user_window_does_not_alert(tmp_path):
    fixture = tmp_path / "slots.json"
    db = tmp_path / "tf.db"
    cfg = _config(fixture, db)
    users = _users()

    _write_slots(fixture, [{"date": "2026-06-27", "time": "07:30", "players_available": 2}])
    with Storage(db) as storage:
        run_cycle(cfg, storage, RecordingNotifier(), users=users)  # baseline

    # New slot at 14:00 Saturday — outside the 06:00-10:00 window.
    _write_slots(
        fixture,
        [
            {"date": "2026-06-27", "time": "07:30", "players_available": 2},
            {"date": "2026-06-27", "time": "14:00", "players_available": 2},
        ],
    )
    notifier = RecordingNotifier()
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, notifier, users=users)
    assert summary["new_availabilities"] == 1  # detected at club level
    assert summary["emails_sent"] == 0          # but no user wanted it


def test_run_cycle_reads_users_from_database(tmp_path):
    """With no explicit users, the runner alerts accounts stored in the DB."""
    fixture = tmp_path / "slots.json"
    db = tmp_path / "tf.db"
    cfg = _config(fixture, db)

    # Register a DB user (source of truth) subscribed to demo, Saturday mornings.
    store = UserStore(db)
    store.create_user("dbuser@example.com", "pw12345678", "DB User")
    uid = store.id_for_email("dbuser@example.com")
    store.update_profile(
        uid,
        name="DB User",
        min_players=1,
        clubs=["demo"],
        preferences=[{"days": ["Saturday"], "time_ranges": [{"start": "06:00", "end": "10:00"}]}],
    )
    store.close()

    _write_slots(fixture, [{"date": "2026-06-27", "time": "07:30", "players_available": 2}])
    with Storage(db) as storage:
        run_cycle(cfg, storage, RecordingNotifier())  # baseline, users from DB

    _write_slots(
        fixture,
        [
            {"date": "2026-06-27", "time": "07:30", "players_available": 2},
            {"date": "2026-06-27", "time": "08:10", "players_available": 4},
        ],
    )
    notifier = RecordingNotifier()
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, notifier)  # users loaded from DB
    assert summary["emails_sent"] == 1
    assert notifier.sent[0][0] == "dbuser@example.com"


def test_multiple_clubs_scraped_concurrently(tmp_path):
    """All clubs are scraped (in parallel) and diffed independently."""
    db = tmp_path / "tf.db"
    fa, fb, fc = (tmp_path / f"{c}.json" for c in "abc")
    cfg = Config.model_validate(
        {
            "global": {
                "scrape_interval_minutes": 5,
                "lookahead_weeks": 520,
                "scrape_concurrency": 3,
                "database_path": str(db),
            },
            "email": {"username": "a@b.com", "from_address": "a@b.com"},
            "clubs": [
                {"id": "a", "name": "A", "platform": "fixture", "url": str(fa)},
                {"id": "b", "name": "B", "platform": "fixture", "url": str(fb)},
                {"id": "c", "name": "C", "platform": "fixture", "url": str(fc)},
            ],
        }
    )
    user = UserConfig.model_validate({
        "name": "Ted", "email": "ted@example.com",
        "preferences": [{"days": ["Saturday"], "time_ranges": [{"start": "06:00", "end": "10:00"}]}],
    })  # subscribed to all clubs

    # Baseline for all three clubs.
    for f in (fa, fb, fc):
        _write_slots(f, [{"date": "2026-06-27", "time": "07:30", "players_available": 2}])
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, RecordingNotifier(), users=[user])
    assert summary["clubs_scraped"] == 3
    assert summary["new_availabilities"] == 0  # baseline

    # A new slot opens at clubs A and C only.
    for f in (fa, fc):
        _write_slots(f, [
            {"date": "2026-06-27", "time": "07:30", "players_available": 2},
            {"date": "2026-06-27", "time": "08:10", "players_available": 4},
        ])
    notifier = RecordingNotifier()
    with Storage(db) as storage:
        summary = run_cycle(cfg, storage, notifier, users=[user])
    assert summary["new_availabilities"] == 2  # one new slot at A, one at C
    assert summary["emails_sent"] == 1          # single digest covering both
    body = notifier.sent[0][2]
    assert body.count("08:10") == 2             # both clubs' new slots in the email
