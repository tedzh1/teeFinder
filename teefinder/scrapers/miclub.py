"""MiClub booking-platform adapter (calendar + timesheet, two-phase).

MiClub powers many Australian golf clubs (e.g. Wakehurst). Availability is
served by two server-rendered pages:

* ``ViewPublicCalendar.msp`` — shows ~6 days per page (paged a week at a time via
  ``selectedDate=YYYY-MM-DD``). Each day/fee-group cell is either "Not Available"
  or clickable with ``redirectToTimesheet('<feeGroupId>','<YYYY-MM-DD>')`` and a
  price. This is the cheap index of *which* days have anything open.
* ``ViewPublicTimesheet.msp?...&selectedDate=YYYY-MM-DD&feeGroupId=<id>`` — the
  tee sheet for one day. Each ``div.row-time`` holds a time and four player cells;
  the number of ``cell-available`` cells is the spots open.

Phase 1 pages the calendar across the lookahead horizon and collects available
``(date, feeGroupId)`` cells. Phase 2 fetches a timesheet only for those days, so
unreleased future days (which the calendar marks "Not Available") cost nothing
beyond the calendar paging — keeping a 12-week horizon cheap.

This single adapter works for any MiClub club; the club's ``url`` is its public
calendar URL and ``options.booking_resource_id`` identifies the course/resource.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import requests
from bs4 import BeautifulSoup

from teefinder.models import TeeTime
from teefinder.scrapers.base import BaseScraper, build_session

logger = logging.getLogger(__name__)

# "10:46 am" / "12:06 pm" / "07:30"
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?")
# onclick="javascript:redirectToTimesheet('1510657214','2026-06-22');"
_REDIRECT_RE = re.compile(r"redirectToTimesheet\('(\d+)','(\d{4}-\d{2}-\d{2})'\)")


def _parse_time(text: str) -> dt.time | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    meridiem = (m.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return dt.time(hour, minute)


class MiClubScraper(BaseScraper):
    platform = "miclub"
    CALENDAR_DAYS = 6  # days shown per calendar page

    def scrape(self, lookahead_days: int) -> list[TeeTime]:
        session = build_session()
        resource_id = self._resource_id()
        base = self._base_url()
        calendar_url = f"{base}/guests/bookings/ViewPublicCalendar.msp"
        timesheet_url = f"{base}/guests/bookings/ViewPublicTimesheet.msp"
        fee_filter = {str(x) for x in self.club.options.get("fee_group_ids", [])}

        today = dt.date.today()
        horizon = today + dt.timedelta(days=lookahead_days)

        # Phase 1: page the calendar -> available (date, feeGroup) cells + price.
        available: dict[tuple[dt.date, str], str | None] = {}
        cursor = today
        # +2 pages of slack so the horizon's final partial week is covered.
        for _ in range((lookahead_days // self.CALENDAR_DAYS) + 2):
            if cursor > horizon:
                break
            html = self._get(session, calendar_url, {
                "bookingResourceId": resource_id,
                "selectedDate": cursor.isoformat(),
            })
            if html is not None:
                for date, fee_group_id, price in self.parse_calendar(html):
                    if today <= date <= horizon and (not fee_filter or fee_group_id in fee_filter):
                        available[(date, fee_group_id)] = price
            cursor += dt.timedelta(days=self.CALENDAR_DAYS)

        logger.info(
            "%s: calendar shows %d available day/fee-group cell(s) within %d weeks",
            self.club.id, len(available), lookahead_days // 7,
        )

        # Phase 2: fetch the timesheet for each available day; parse open slots.
        tee_by_fp: dict[str, TeeTime] = {}
        for (date, fee_group_id), price in sorted(available.items()):
            html = self._get(session, timesheet_url, {
                "bookingResourceId": resource_id,
                "selectedDate": date.isoformat(),
                "feeGroupId": fee_group_id,
            })
            if html is None:
                continue
            booking_url = (
                f"{timesheet_url}?bookingResourceId={resource_id}"
                f"&selectedDate={date.isoformat()}&feeGroupId={fee_group_id}"
            )
            for tee in self.parse_timesheet(html, date, booking_url, price):
                # The same time can appear under multiple fee groups; keep the
                # one reporting the most open spots.
                existing = tee_by_fp.get(tee.fingerprint)
                if existing is None or (tee.players_available or 0) > (existing.players_available or 0):
                    tee_by_fp[tee.fingerprint] = tee

        return list(tee_by_fp.values())

    # -- parsing (network-free, unit-tested against saved fixtures) ---------

    def parse_calendar(self, html: str) -> list[tuple[dt.date, str, str | None]]:
        """Available ``(date, feeGroupId, price)`` cells from a calendar page.

        "Not Available" cells have no ``redirectToTimesheet`` onclick and are
        therefore skipped.
        """
        soup = BeautifulSoup(html, "lxml")
        out: list[tuple[dt.date, str, str | None]] = []
        for cell in soup.select("div.cell[onclick]"):
            m = _REDIRECT_RE.search(cell.get("onclick", ""))
            if not m:
                continue
            fee_group_id, date_str = m.group(1), m.group(2)
            price_el = cell.select_one(".price")
            price = price_el.get_text(strip=True) if price_el else None
            out.append((dt.date.fromisoformat(date_str), fee_group_id, price))
        return out

    def parse_timesheet(
        self, html: str, date: dt.date, booking_url: str | None, price: str | None
    ) -> list[TeeTime]:
        """Open tee times from one day's timesheet.

        Spots open = number of ``cell-available`` cells in the time's row.
        """
        soup = BeautifulSoup(html, "lxml")
        results: list[TeeTime] = []
        for row in soup.select("div.row-time"):
            heading = row.select_one(".time-wrapper h3")
            if heading is None:
                continue
            time = _parse_time(heading.get_text(strip=True))
            if time is None:
                continue
            spots = len(row.select("div.cell.cell-available"))
            if spots <= 0:
                continue
            results.append(
                TeeTime(
                    club_id=self.club.id,
                    date=date,
                    time=time,
                    players_available=spots,
                    price=price,
                    booking_url=booking_url,
                )
            )
        return results

    # -- helpers -----------------------------------------------------------

    def _get(self, session: requests.Session, url: str, params: dict) -> str | None:
        resp = session.get(url, params=params)
        if resp.status_code != 200:
            logger.warning("%s: %s %s -> HTTP %s", self.club.id, url, params, resp.status_code)
            return None
        return resp.text

    def _resource_id(self) -> str:
        rid = self.club.options.get("booking_resource_id")
        if rid:
            return str(rid)
        m = re.search(r"[?&](?:booking_resource_id|bookingResourceId)=(\d+)", self.club.url)
        if m:
            return m.group(1)
        raise ValueError(
            f"Club {self.club.id!r}: set options.booking_resource_id "
            "(or include it in the club url)."
        )

    def _base_url(self) -> str:
        m = re.match(r"(https?://[^/]+)", self.club.url)
        if not m:
            raise ValueError(f"Club {self.club.id!r}: url must be an absolute http(s) URL.")
        return m.group(1)
