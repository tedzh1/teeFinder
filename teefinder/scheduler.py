"""Internal scheduler (daemon mode) wrapping the run cycle.

Uses APScheduler's blocking scheduler so `teefinder daemon` keeps running and
fires a cycle every ``scrape_interval_minutes``. For cloud, you'd instead point
an external scheduler at `teefinder run`; this module is the local-first option.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from teefinder.config import Config
from teefinder.notifier import EmailNotifier
from teefinder.runner import run_cycle
from teefinder.storage import Storage

logger = logging.getLogger(__name__)


def run_daemon(config: Config, dry_run: bool = False) -> None:
    interval = config.global_.scrape_interval_minutes
    scheduler = BlockingScheduler(timezone="UTC")

    def job() -> None:
        # Open a fresh Storage per cycle so the long-lived process doesn't hold
        # a single connection across the daemon's whole lifetime.
        with Storage(config.global_.database_path) as storage:
            notifier = EmailNotifier(config.email, dry_run=dry_run)
            try:
                run_cycle(config, storage, notifier)
            except Exception:
                logger.exception("Cycle failed")

    scheduler.add_job(job, "interval", minutes=interval, next_run_time=_now_utc())
    logger.info("Daemon started: scraping every %d minute(s). Ctrl-C to stop.", interval)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Daemon stopped.")


def _now_utc():
    # Imported here so module import doesn't bind datetime.now at import time.
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc)
