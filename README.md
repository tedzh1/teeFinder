# teeFinder

Watches the online booking pages of golf clubs and emails you when **new** tee-time
availability is released that matches your interests (day of week + time of day).

## How it works

On a schedule, teeFinder:

1. **Scrapes** each configured club's booking page via a platform-specific adapter.
2. **Snapshots** the currently-bookable tee times into a common schema (SQLite).
3. **Diffs** against the previous snapshot to find slots that just became available.
4. **Matches** those new slots against each user's day-of-week / time-range preferences.
5. **Emails** a digest to each matching user (Gmail SMTP). Each slot is only ever
   alerted once per user.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -e .                  # or: pip install -e ".[dev]"

cp .env.example .env              # then add your Gmail app password
cp config/config.example.yaml config/config.yaml   # then edit clubs/users
```

Generate a Gmail **App Password** (requires 2FA) at
<https://myaccount.google.com/apppasswords> and put it in `.env` as `GMAIL_APP_PASSWORD`.

## Usage

```bash
teefinder validate                 # check config, list clubs/users
teefinder run --dry-run            # one cycle; log emails instead of sending
teefinder run                      # one cycle; send real emails
teefinder run --club club-a        # scrape a single club
teefinder test-email               # send a test email to confirm SMTP works
teefinder daemon                   # run continuously on the configured interval
```

The same `teefinder run` command is what you point Windows Task Scheduler / cron /
a cloud scheduler at when you move off your local machine.

## Configuration

See [config/config.example.yaml](config/config.example.yaml). Global settings
(scrape interval, lookahead horizon, timezone, db path), the list of `clubs`, and
the list of `users` (each with their own email + day/time preferences) all live there.
Secrets (the Gmail app password) live in `.env`, never in the YAML.

## Adding a new club / booking platform

Each booking platform has a scraper in [teefinder/scrapers/](teefinder/scrapers/)
registered by a `platform` name. If a club uses a platform that already has an
adapter (e.g. `miclub`), just add the club to `config.yaml` with that `platform`.
If it's a new platform, add a `BaseScraper` subclass that emits the common
`TeeTime` schema and register it.
