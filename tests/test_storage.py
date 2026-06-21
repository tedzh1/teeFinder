import datetime as dt
import sqlite3

from teefinder.models import Snapshot, TeeTime
from teefinder.storage import Storage

SAT = dt.date(2026, 6, 27)


def _snap(tees):
    return Snapshot(club_id="demo", scraped_at=dt.datetime(2026, 6, 20, tzinfo=dt.timezone.utc), tee_times=tees)


def test_title_round_trips(tmp_path):
    db = tmp_path / "tf.db"
    with Storage(db) as storage:
        storage.save_snapshot(_snap([
            TeeTime(club_id="demo", date=SAT, time=dt.time(7, 30), players_available=2,
                    price="$45", title="18 Holes + Cart"),
        ]))
    with Storage(db) as storage:
        snap = storage.latest_snapshot("demo")
    assert snap.tee_times[0].title == "18 Holes + Cart"


def test_migration_adds_title_column_to_legacy_db(tmp_path):
    db = tmp_path / "legacy.db"
    # Hand-build a pre-title tee_times table and insert a row.
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, club_id TEXT, scraped_at TEXT);
        CREATE TABLE tee_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id INTEGER, club_id TEXT,
            date TEXT, time TEXT, players_available INTEGER, price TEXT, booking_url TEXT,
            fingerprint TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO snapshots (club_id, scraped_at) VALUES ('demo','2026-06-20T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO tee_times (snapshot_id, club_id, date, time, players_available, price, booking_url, fingerprint)"
        " VALUES (1,'demo','2026-06-27','07:30',2,'$45',NULL,'fp1')"
    )
    conn.commit()
    conn.close()

    # Opening via Storage runs the migration; the legacy row reads back with title=None.
    with Storage(db) as storage:
        snap = storage.latest_snapshot("demo")
    assert snap.tee_times[0].title is None
    assert snap.tee_times[0].players_available == 2
