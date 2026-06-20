"""SQLite persistence: snapshots, tee times, and sent-alert de-duplication.

The database is a single portable file, so moving from local to cloud is just
copying the ``.db``. All timestamps are stored as UTC ISO-8601 strings.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from teefinder.models import Snapshot, TeeTime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id     TEXT NOT NULL,
    scraped_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_club ON snapshots(club_id, id);

CREATE TABLE IF NOT EXISTS tee_times (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id        INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    club_id            TEXT NOT NULL,
    date               TEXT NOT NULL,   -- ISO date
    time               TEXT NOT NULL,   -- HH:MM
    players_available  INTEGER,
    price              TEXT,
    booking_url        TEXT,
    fingerprint        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tee_times_snapshot ON tee_times(snapshot_id);

CREATE TABLE IF NOT EXISTS sent_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email   TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    club_id      TEXT NOT NULL,
    date         TEXT NOT NULL,
    time         TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    UNIQUE(user_email, fingerprint)
);
"""


def _row_to_teetime(row: sqlite3.Row) -> TeeTime:
    return TeeTime(
        club_id=row["club_id"],
        date=dt.date.fromisoformat(row["date"]),
        time=dt.time.fromisoformat(row["time"]),
        players_available=row["players_available"],
        price=row["price"],
        booking_url=row["booking_url"],
        fingerprint=row["fingerprint"],
    )


class Storage:
    """Thin wrapper over a SQLite connection holding all teeFinder state."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- snapshots ---------------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> int:
        """Persist a snapshot and its tee times; returns the new snapshot id."""
        cur = self.conn.execute(
            "INSERT INTO snapshots (club_id, scraped_at) VALUES (?, ?)",
            (snapshot.club_id, snapshot.scraped_at.isoformat()),
        )
        snapshot_id = int(cur.lastrowid)
        self.conn.executemany(
            """
            INSERT INTO tee_times
                (snapshot_id, club_id, date, time, players_available,
                 price, booking_url, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    t.club_id,
                    t.date.isoformat(),
                    t.time.strftime("%H:%M"),
                    t.players_available,
                    t.price,
                    t.booking_url,
                    t.fingerprint,
                )
                for t in snapshot.tee_times
            ],
        )
        self.conn.commit()
        return snapshot_id

    def latest_snapshot(self, club_id: str, before_id: int | None = None) -> Snapshot | None:
        """Most recent snapshot for a club, optionally before a given id.

        Pass the just-saved snapshot's id as ``before_id`` to fetch the
        *previous* snapshot to diff against.
        """
        if before_id is None:
            row = self.conn.execute(
                "SELECT * FROM snapshots WHERE club_id = ? ORDER BY id DESC LIMIT 1",
                (club_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM snapshots WHERE club_id = ? AND id < ? "
                "ORDER BY id DESC LIMIT 1",
                (club_id, before_id),
            ).fetchone()
        if row is None:
            return None
        tee_rows = self.conn.execute(
            "SELECT * FROM tee_times WHERE snapshot_id = ?", (row["id"],)
        ).fetchall()
        return Snapshot(
            club_id=row["club_id"],
            scraped_at=dt.datetime.fromisoformat(row["scraped_at"]),
            tee_times=[_row_to_teetime(r) for r in tee_rows],
        )

    # -- sent-alert dedup --------------------------------------------------

    def already_alerted(self, user_email: str, fingerprint: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sent_alerts WHERE user_email = ? AND fingerprint = ?",
            (user_email, fingerprint),
        ).fetchone()
        return row is not None

    def record_alert(self, user_email: str, tee: TeeTime, sent_at: dt.datetime) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO sent_alerts
                (user_email, fingerprint, club_id, date, time, sent_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_email,
                tee.fingerprint,
                tee.club_id,
                tee.date.isoformat(),
                tee.time.strftime("%H:%M"),
                sent_at.isoformat(),
            ),
        )
        self.conn.commit()
