"""Orchestrates one full cycle: scrape -> snapshot -> diff -> match -> alert.

This is the heart of teeFinder, invoked both by the one-shot ``run`` command
and by the scheduler daemon.
"""

from __future__ import annotations

import datetime as dt
import logging

from teefinder.accounts import UserStore
from teefinder.config import Config, UserConfig
from teefinder.diff import new_availabilities
from teefinder.matching import matches_for_user
from teefinder.models import Snapshot, TeeTime
from teefinder.notifier import EmailNotifier, build_digest
from teefinder.scrapers import build_scraper
from teefinder.storage import Storage

logger = logging.getLogger(__name__)


def run_cycle(
    config: Config,
    storage: Storage,
    notifier: EmailNotifier,
    only_club: str | None = None,
    users: list[UserConfig] | None = None,
) -> dict[str, int]:
    """Run one full cycle. Returns a small summary dict for logging/CLI.

    ``users`` defaults to the active accounts in the database (the source of
    truth now that registration is web-based); pass an explicit list to override
    (e.g. in tests).
    """
    clubs = config.clubs
    if only_club is not None:
        clubs = [config.club(only_club)]

    if users is None:
        with UserStore(config.global_.database_path) as user_store:
            users = user_store.list_active()

    all_new: list[TeeTime] = []
    for club in clubs:
        try:
            new_for_club = _process_club(config, storage, club.id)
        except Exception:  # one bad club shouldn't kill the whole cycle
            logger.exception("Failed to scrape club %s", club.id)
            continue
        all_new.extend(new_for_club)

    emails_sent = _alert_users(config, storage, notifier, all_new, users)

    summary = {
        "clubs_scraped": len(clubs),
        "new_availabilities": len(all_new),
        "emails_sent": emails_sent,
    }
    logger.info("Cycle complete: %s", summary)
    return summary


def _process_club(config: Config, storage: Storage, club_id: str) -> list[TeeTime]:
    club = config.club(club_id)
    scraper = build_scraper(club)
    logger.info("Scraping %s (%s)...", club.name, club.platform)

    tee_times = scraper.scrape(config.global_.lookahead_days)
    snapshot = Snapshot(
        club_id=club.id,
        scraped_at=dt.datetime.now(dt.timezone.utc),
        tee_times=tee_times,
    )
    snapshot_id = storage.save_snapshot(snapshot)
    previous = storage.latest_snapshot(club.id, before_id=snapshot_id)

    new = new_availabilities(previous, snapshot)
    logger.info(
        "%s: %d slots scraped, %d newly available%s",
        club.name,
        len(tee_times),
        len(new),
        " (baseline run)" if previous is None else "",
    )
    return new


def _alert_users(
    config: Config,
    storage: Storage,
    notifier: EmailNotifier,
    new_tee_times: list[TeeTime],
    users: list[UserConfig],
) -> int:
    if not new_tee_times:
        return 0

    club_names = {c.id: c.name for c in config.clubs}
    dashboard_url = config.web.dashboard_url
    now = dt.datetime.now(dt.timezone.utc)
    emails_sent = 0

    for user in users:
        matched = matches_for_user(new_tee_times, user)
        # Belt-and-suspenders dedup: never re-alert a slot already sent.
        fresh = [t for t in matched if not storage.already_alerted(user.email, t.fingerprint)]
        if not fresh:
            continue

        subject, text_body, html_body = build_digest(user, fresh, club_names, dashboard_url)
        notifier.send(user.email, subject, text_body, html_body)
        for tee in fresh:
            storage.record_alert(user.email, tee, now)
        emails_sent += 1
        logger.info("Alerted %s about %d slot(s)", user.email, len(fresh))

    return emails_sent
