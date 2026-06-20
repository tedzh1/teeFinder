"""Command-line interface for teeFinder."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

import typer
from dotenv import load_dotenv

from teefinder.accounts import DuplicateEmailError, UserStore
from teefinder.config import Config, load_config
from teefinder.notifier import EmailNotifier
from teefinder.runner import run_cycle
from teefinder.scheduler import run_daemon
from teefinder.storage import Storage

app = typer.Typer(
    add_completion=False,
    help="Alerts you when new tee times become available at your golf clubs.",
)

DEFAULT_CONFIG = Path("config/config.yaml")


def _setup(config_path: Path):
    load_dotenv()  # pull GMAIL_APP_PASSWORD etc. from .env if present
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return load_config(config_path)


@app.command()
def run(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
    club: str = typer.Option(None, "--club", help="Only scrape this club id."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Log emails instead of sending."),
):
    """Run one full scrape -> diff -> alert cycle."""
    cfg = _setup(config)
    with Storage(cfg.global_.database_path) as storage:
        notifier = EmailNotifier(cfg.email, dry_run=dry_run)
        summary = run_cycle(cfg, storage, notifier, only_club=club)
    typer.echo(
        f"Done. Scraped {summary['clubs_scraped']} club(s), "
        f"{summary['new_availabilities']} new slot(s), "
        f"{summary['emails_sent']} email(s) sent."
    )


@app.command()
def daemon(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Log emails instead of sending."),
):
    """Run continuously, scraping on the configured interval."""
    cfg = _setup(config)
    run_daemon(cfg, dry_run=dry_run)


@app.command()
def validate(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
):
    """Load and validate the config, listing clubs and (DB) users."""
    cfg = _setup(config)
    typer.echo(
        f"Config OK. Interval={cfg.global_.scrape_interval_minutes}min, "
        f"lookahead={cfg.global_.lookahead_days}d, tz={cfg.global_.timezone}"
    )
    typer.echo(f"\nClubs ({len(cfg.clubs)}):")
    for c in cfg.clubs:
        typer.echo(f"  - {c.id}: {c.name} [{c.platform}]")

    users = _db_users(cfg)
    typer.echo(f"\nRegistered users ({len(users)}):")
    for u in users:
        clubs = ", ".join(u.clubs) if u.clubs else "all clubs"
        typer.echo(f"  - {u.name} <{u.email}> -> {clubs}, {len(u.preferences)} preference block(s)")


@app.command()
def test_email(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
    to: str = typer.Option(None, "--to", help="Recipient; defaults to first registered user."),
):
    """Send a test email to confirm Gmail SMTP works."""
    cfg = _setup(config)
    users = _db_users(cfg)
    recipient = to or (users[0].email if users else None)
    if not recipient:
        raise typer.BadParameter("No recipient: pass --to or register a user via the web app.")
    notifier = EmailNotifier(cfg.email, dry_run=False)
    notifier.send_test(recipient)
    typer.echo(f"Test email sent to {recipient}.")


@app.command()
def web(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
    host: str = typer.Option(None, "--host", help="Override web.host from config."),
    port: int = typer.Option(None, "--port", help="Override web.port from config."),
):
    """Run the web frontend (registration, preferences, tee-time dashboard)."""
    import uvicorn

    from teefinder.web.app import create_app

    cfg = _setup(config)
    app_instance = create_app(cfg)
    uvicorn.run(app_instance, host=host or cfg.web.host, port=port or cfg.web.port)


@app.command()
def seed_users(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
):
    """Import any `users:` defined in the YAML into the database (one-off).

    Each imported account gets a random temporary password, printed below, since
    YAML has no passwords. Users can register/log in normally afterwards.
    """
    cfg = _setup(config)
    if not cfg.users:
        typer.echo("No `users:` in the YAML to import.")
        return
    with UserStore(cfg.global_.database_path) as store:
        for u in cfg.users:
            temp_pw = secrets.token_urlsafe(9)
            try:
                store.create_user(u.email, temp_pw, u.name)
            except DuplicateEmailError:
                typer.echo(f"  skip {u.email} (already exists)")
                continue
            store.update_profile(
                store.id_for_email(u.email),
                name=u.name,
                min_players=u.min_players,
                clubs=u.clubs,
                preferences=_userconfig_prefs_to_dicts(u),
            )
            typer.echo(f"  created {u.email}  temp password: {temp_pw}")


def _db_users(cfg: Config):
    with UserStore(cfg.global_.database_path) as store:
        return store.list_active()


def _userconfig_prefs_to_dicts(user) -> list[dict]:
    from teefinder.config import WEEKDAY_NAMES

    return [
        {
            "days": [WEEKDAY_NAMES[d] for d in pref.days],
            "time_ranges": [
                {"start": tr.start.strftime("%H:%M"), "end": tr.end.strftime("%H:%M")}
                for tr in pref.time_ranges
            ],
        }
        for pref in user.preferences
    ]


if __name__ == "__main__":
    app()
