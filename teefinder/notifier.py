"""Email delivery via Gmail SMTP, plus digest formatting.

One digest email per user per cycle, grouped by club. In ``dry_run`` mode the
message is logged instead of sent, so the whole pipeline can be exercised
without credentials or network.
"""

from __future__ import annotations

import datetime as dt
import logging
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from teefinder.config import EmailConfig, UserConfig
from teefinder.models import TeeTime

logger = logging.getLogger(__name__)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _club_name_lookup(club_names: dict[str, str], club_id: str) -> str:
    return club_names.get(club_id, club_id)


def _format_slot(tee: TeeTime) -> str:
    day = _DAY_NAMES[tee.weekday]
    parts = [f"{day} {tee.date.isoformat()} at {tee.time.strftime('%H:%M')}"]
    if tee.players_available is not None:
        parts.append(f"{tee.players_available} spot(s)")
    if tee.price:
        parts.append(tee.price)
    line = " — ".join(parts)
    if tee.booking_url:
        line += f"\n    Book: {tee.booking_url}"
    return line


def build_digest(
    user: UserConfig,
    tee_times: list[TeeTime],
    club_names: dict[str, str],
    dashboard_url: str | None = None,
) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for a user's matched tee times.

    When ``dashboard_url`` is given, a link to the web view of all matching
    tee times is appended to both bodies.
    """
    by_club: dict[str, list[TeeTime]] = defaultdict(list)
    for t in tee_times:
        by_club[t.club_id].append(t)

    count = len(tee_times)
    subject = f"teeFinder: {count} new tee time{'s' if count != 1 else ''} available"

    text_lines = [f"Hi {user.name},", "", f"{count} new tee time(s) matched your preferences:", ""]
    html_parts = [
        f"<p>Hi {user.name},</p>",
        f"<p><b>{count}</b> new tee time(s) matched your preferences:</p>",
    ]
    for club_id, slots in by_club.items():
        club_label = _club_name_lookup(club_names, club_id)
        text_lines.append(f"== {club_label} ==")
        html_parts.append(f"<h3>{club_label}</h3><ul>")
        for tee in sorted(slots, key=lambda t: (t.date, t.time)):
            text_lines.append(f"  - {_format_slot(tee)}")
            html_parts.append(f"<li>{_html_slot(tee)}</li>")
        text_lines.append("")
        html_parts.append("</ul>")

    if dashboard_url:
        text_lines.append(f"See all your matching tee times: {dashboard_url}")
        html_parts.append(
            f'<p><a href="{dashboard_url}">See all your matching tee times</a></p>'
        )

    text_lines.append("— teeFinder")
    html_parts.append("<p>— teeFinder</p>")

    return subject, "\n".join(text_lines), "\n".join(html_parts)


def _html_slot(tee: TeeTime) -> str:
    day = _DAY_NAMES[tee.weekday]
    bits = [f"<b>{day} {tee.date.isoformat()}</b> at <b>{tee.time.strftime('%H:%M')}</b>"]
    if tee.players_available is not None:
        bits.append(f"{tee.players_available} spot(s)")
    if tee.price:
        bits.append(tee.price)
    text = " — ".join(bits)
    if tee.booking_url:
        text += f' — <a href="{tee.booking_url}">Book</a>'
    return text


class EmailNotifier:
    def __init__(self, config: EmailConfig, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run

    def send(self, to_address: str, subject: str, text_body: str, html_body: str) -> None:
        if self.dry_run:
            logger.info(
                "[dry-run] would email %s\nSubject: %s\n%s",
                to_address,
                subject,
                text_body,
            )
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.from_address
        msg["To"] = to_address
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
            server.starttls()
            server.login(self.config.username, self.config.password)
            server.send_message(msg)
        logger.info("Sent email to %s (%s)", to_address, subject)

    def send_test(self, to_address: str) -> None:
        now = dt.datetime.now().isoformat(timespec="seconds")
        self.send(
            to_address,
            "teeFinder test email",
            f"This is a teeFinder test email sent at {now}. SMTP is working.",
            f"<p>This is a teeFinder test email sent at {now}.</p>"
            "<p>SMTP is working. ⛳</p>",
        )
