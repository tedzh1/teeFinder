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

Also set `TEEFINDER_SECRET_KEY` in `.env` (used to sign web sessions):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Usage

The scraper and the web frontend are **two separate processes** sharing one
SQLite database.

```bash
# Scraper
teefinder validate                 # check config, list clubs + registered users
teefinder run --dry-run            # one cycle; log emails instead of sending
teefinder run                      # one cycle; send real emails
teefinder run --club wakehurst     # scrape a single club
teefinder test-email               # send a test email to confirm SMTP works
teefinder daemon                   # run continuously on the configured interval

# Web app (registration, preferences, tee-time dashboard)
teefinder web                      # serve at web.host:web.port (default :8000)
teefinder seed-users               # optional: import any YAML `users:` into the DB
```

The same `teefinder run` command is what you point Windows Task Scheduler / cron /
a cloud scheduler at when you move off your local machine.

## Web frontend

Run `teefinder web` and open <http://localhost:8000>. Users **register** with an
email + password, then set their own configuration on the **Preferences** page
(which clubs, day-of-week + time windows, and minimum open spots). The
**Dashboard** shows every currently-available tee time matching their
preferences, taken from the latest scrape in the database. Each alert email also
links to this dashboard.

Accounts and preferences live in the **database** (managed via the web app), so
the scraper reads its user list from there — not from the YAML.

## Configuration

See [config/config.example.yaml](config/config.example.yaml). The YAML holds
**operator-managed** settings only: global options (scrape interval, lookahead
horizon, timezone, db path), the `web` block (base URL/host/port), and the list
of `clubs`. **Users are managed through the web app**, not the YAML. Secrets (the
Gmail app password, the session secret) live in `.env`, never in the YAML.

## Adding a new club / booking platform

Each booking platform has a scraper in [teefinder/scrapers/](teefinder/scrapers/)
registered by a `platform` name. If a club uses a platform that already has an
adapter (e.g. `miclub`), just add the club to `config.yaml` with that `platform`.
If it's a new platform, add a `BaseScraper` subclass that emits the common
`TeeTime` schema and register it.
