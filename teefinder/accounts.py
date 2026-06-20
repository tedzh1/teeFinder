"""User accounts: persistence and authentication.

Users (and their preferences) live in the database so they can self-register
and manage their own configuration via the web frontend. Each DB row is loaded
back into the existing :class:`~teefinder.config.UserConfig` shape, so the
scraper, matching and email code consume users exactly as before — only the
*source* of the user list changes (DB instead of YAML).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import bcrypt

from teefinder.config import Preference, UserConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT NOT NULL UNIQUE,
    password_hash     TEXT NOT NULL,
    name              TEXT NOT NULL,
    min_players       INTEGER NOT NULL DEFAULT 1,
    clubs_json        TEXT NOT NULL DEFAULT '[]',
    preferences_json  TEXT NOT NULL DEFAULT '[]',
    is_active         INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL
);
"""


class DuplicateEmailError(ValueError):
    """Raised when registering an email that already exists."""


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _row_to_userconfig(row: sqlite3.Row) -> UserConfig:
    """Build a UserConfig from a DB row, reusing pydantic validation.

    ``preferences_json`` is stored with weekday names (as the YAML used), so it
    round-trips through the same validators in ``config.py``.
    """
    return UserConfig.model_validate(
        {
            "name": row["name"],
            "email": row["email"],
            "clubs": json.loads(row["clubs_json"]),
            "min_players": row["min_players"],
            "preferences": json.loads(row["preferences_json"]),
        }
    )


def _preferences_to_json(preferences: list[Preference]) -> str:
    """Serialise preferences back to the name-based JSON we store."""
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    out = []
    for pref in preferences:
        out.append(
            {
                "days": [day_names[d] for d in pref.days],
                "time_ranges": [
                    {"start": tr.start.strftime("%H:%M"), "end": tr.end.strftime("%H:%M")}
                    for tr in pref.time_ranges
                ],
            }
        )
    return json.dumps(out)


class UserStore:
    """SQLite-backed store for user accounts on the shared teeFinder DB."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI may create a sync dependency in a
        # worker thread and use it in the event-loop thread within one request.
        # Each request uses its own connection sequentially, so this is safe.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL lets the web process and the scraper share the DB concurrently.
        self.conn.execute("PRAGMA journal_mode = WAL")
        # Wait up to 5s for a lock instead of erroring (web + scraper share the file).
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "UserStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- creation / auth ---------------------------------------------------

    def create_user(self, email: str, password: str, name: str) -> UserConfig:
        email = email.strip().lower()
        if self.get_row_by_email(email) is not None:
            raise DuplicateEmailError(f"An account with email {email!r} already exists.")
        self.conn.execute(
            """
            INSERT INTO users (email, password_hash, name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, _hash_password(password), name, dt.datetime.now(dt.timezone.utc).isoformat()),
        )
        self.conn.commit()
        return _row_to_userconfig(self.get_row_by_email(email))

    def authenticate(self, email: str, password: str) -> UserConfig | None:
        row = self.get_row_by_email(email.strip().lower())
        if row is None or not row["is_active"]:
            return None
        if not _verify_password(password, row["password_hash"]):
            return None
        return _row_to_userconfig(row)

    # -- lookups -----------------------------------------------------------

    def get_row_by_email(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()

    def get_by_email(self, email: str) -> UserConfig | None:
        row = self.get_row_by_email(email)
        return _row_to_userconfig(row) if row else None

    def get_by_id(self, user_id: int) -> UserConfig | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_userconfig(row) if row else None

    def id_for_email(self, email: str) -> int | None:
        row = self.get_row_by_email(email)
        return int(row["id"]) if row else None

    def list_active(self) -> list[UserConfig]:
        rows = self.conn.execute(
            "SELECT * FROM users WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        return [_row_to_userconfig(r) for r in rows]

    # -- updates -----------------------------------------------------------

    def update_profile(
        self,
        user_id: int,
        *,
        name: str,
        min_players: int,
        clubs: list[str],
        preferences: list[dict],
    ) -> UserConfig:
        """Update a user's editable config.

        ``preferences`` are name-based dicts (``{"days": ["Saturday"],
        "time_ranges": [{"start": "06:00", "end": "10:00"}]}``) — the same shape
        the YAML used. Everything is validated through ``UserConfig`` so invalid
        days / time-range ordering / min_players raise before we write.
        """
        current = self.get_by_id(user_id)
        if current is None:
            raise KeyError(f"No user with id {user_id}")
        validated = UserConfig.model_validate(
            {
                "name": name,
                "email": current.email,  # email is immutable here
                "clubs": clubs,
                "min_players": min_players,
                "preferences": preferences,
            }
        )
        self.conn.execute(
            """
            UPDATE users
               SET name = ?, min_players = ?, clubs_json = ?, preferences_json = ?
             WHERE id = ?
            """,
            (
                validated.name,
                validated.min_players,
                json.dumps(validated.clubs),
                _preferences_to_json(validated.preferences),
                user_id,
            ),
        )
        self.conn.commit()
        return self.get_by_id(user_id)
