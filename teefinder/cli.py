"""Command-line interface for teeFinder."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from dotenv import load_dotenv

from teefinder.config import load_config
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
    """Load and validate the config, listing clubs and users."""
    cfg = _setup(config)
    typer.echo(
        f"Config OK. Interval={cfg.global_.scrape_interval_minutes}min, "
        f"lookahead={cfg.global_.lookahead_days}d, tz={cfg.global_.timezone}"
    )
    typer.echo(f"\nClubs ({len(cfg.clubs)}):")
    for c in cfg.clubs:
        typer.echo(f"  - {c.id}: {c.name} [{c.platform}]")
    typer.echo(f"\nUsers ({len(cfg.users)}):")
    for u in cfg.users:
        clubs = ", ".join(u.clubs) if u.clubs else "all clubs"
        typer.echo(f"  - {u.name} <{u.email}> -> {clubs}, {len(u.preferences)} preference block(s)")


@app.command()
def test_email(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c", help="Path to config YAML."),
    to: str = typer.Option(None, "--to", help="Recipient; defaults to first user's email."),
):
    """Send a test email to confirm Gmail SMTP works."""
    cfg = _setup(config)
    recipient = to or (cfg.users[0].email if cfg.users else None)
    if not recipient:
        raise typer.BadParameter("No recipient: pass --to or add a user to the config.")
    notifier = EmailNotifier(cfg.email, dry_run=False)
    notifier.send_test(recipient)
    typer.echo(f"Test email sent to {recipient}.")


if __name__ == "__main__":
    app()
