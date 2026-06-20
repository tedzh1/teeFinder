"""Load and validate the YAML configuration into typed models.

Secrets (the Gmail app password) are never read from YAML — only from the
environment — so a committed/leaked config file can't expose credentials.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# Monday=0 .. Sunday=6 to match datetime.date.weekday()
WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]
_WEEKDAYS = {name.lower(): i for i, name in enumerate(WEEKDAY_NAMES)}

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: str) -> str:
    """Replace ``${VAR}`` references in a string with environment values."""

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        env = os.environ.get(name)
        if env is None:
            raise ValueError(f"Environment variable {name!r} referenced in config is not set")
        return env

    return _ENV_PATTERN.sub(repl, value)


class GlobalConfig(BaseModel):
    scrape_interval_minutes: int = Field(gt=0)
    timezone: str = "UTC"
    # How far ahead to look. MiClub-style sites expose tee times months out, so
    # this caps the scrape depth (e.g. 12 weeks) rather than chasing every day.
    lookahead_weeks: int = Field(default=12, gt=0)
    database_path: Path = Path("./data/teefinder.db")

    @property
    def lookahead_days(self) -> int:
        return self.lookahead_weeks * 7


class EmailConfig(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: str
    from_address: str
    # Pulled from env (GMAIL_APP_PASSWORD by default), not stored in YAML.
    password_env: str = "GMAIL_APP_PASSWORD"

    @property
    def password(self) -> str:
        pw = os.environ.get(self.password_env)
        if not pw:
            raise RuntimeError(
                f"Email password env var {self.password_env!r} is not set. "
                "Add it to your .env file."
            )
        return pw


class WebConfig(BaseModel):
    # Public base URL of the web app, used in email links. No trailing slash.
    base_url: str = "http://localhost:8000"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def dashboard_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/dashboard"


class ClubConfig(BaseModel):
    id: str
    name: str
    platform: str
    url: str
    options: dict = Field(default_factory=dict)


class TimeRange(BaseModel):
    start: dt.time
    end: dt.time

    @field_validator("start", "end", mode="before")
    @classmethod
    def _parse_time(cls, v: object) -> object:
        if isinstance(v, str):
            return dt.time.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def _check_order(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError(f"time_range end ({self.end}) must be after start ({self.start})")
        return self

    def contains(self, t: dt.time) -> bool:
        """Inclusive of start, exclusive of end."""
        return self.start <= t < self.end


class Preference(BaseModel):
    days: list[int]
    time_ranges: list[TimeRange]

    @field_validator("days", mode="before")
    @classmethod
    def _parse_days(cls, v: object) -> object:
        if not isinstance(v, list):
            raise ValueError("days must be a list of weekday names")
        out: list[int] = []
        for d in v:
            key = str(d).strip().lower()
            if key not in _WEEKDAYS:
                raise ValueError(
                    f"Unknown day of week: {d!r}. Use full names like 'Saturday'."
                )
            out.append(_WEEKDAYS[key])
        return out


class UserConfig(BaseModel):
    name: str
    email: str
    # Empty/omitted => subscribed to all clubs.
    clubs: list[str] = Field(default_factory=list)
    # Only alert on slots with at least this many open spots (1-4). Default 1.
    min_players: int = Field(default=1, ge=1, le=4)
    preferences: list[Preference] = Field(default_factory=list)

    def subscribed_to(self, club_id: str) -> bool:
        return not self.clubs or club_id in self.clubs


class Config(BaseModel):
    global_: GlobalConfig = Field(alias="global")
    email: EmailConfig
    web: WebConfig = Field(default_factory=WebConfig)
    clubs: list[ClubConfig]
    # Users now live in the database (managed via the web app). This is kept
    # optional only for `seed-users` (importing example users) / back-compat.
    users: list[UserConfig] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_references(self) -> "Config":
        club_ids = {c.id for c in self.clubs}
        if len(club_ids) != len(self.clubs):
            raise ValueError("Duplicate club id found in config")
        for user in self.users:
            for club_id in user.clubs:
                if club_id not in club_ids:
                    raise ValueError(
                        f"User {user.name!r} references unknown club id {club_id!r}"
                    )
        return self

    def club(self, club_id: str) -> ClubConfig:
        for c in self.clubs:
            if c.id == club_id:
                return c
        raise KeyError(f"No club with id {club_id!r}")


def load_config(path: str | Path) -> Config:
    """Read, env-expand and validate the YAML config at ``path``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config/config.example.yaml to get started."
        )
    text = _expand_env(path.read_text(encoding="utf-8"))
    data = yaml.safe_load(text) or {}
    return Config.model_validate(data)
