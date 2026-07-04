"""Builds a .ics (iCalendar) file per RFC 5545.

Dated items become all-day VEVENTs (VALUE=DATE, with an exclusive DTEND).
Items with no date become VTODOs with no DUE. Lines are folded at 75 octets
and joined with CRLF, both required by the spec.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


class IcsValidationError(Exception):
    """The submitted items can't produce a valid calendar."""


@dataclass
class ReviewedItem:
    """One row from the review screen, after the user's edits."""

    title: str
    date: date | None  # None means "I don't know the date" -> VTODO


# ---- low-level helpers ----


def _escape_text(value: str) -> str:
    """Escape a TEXT value (RFC 5545 3.3.11). Backslash has to go first."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Fold one content line to 75 octets max per physical line.

    Measured in UTF-8 bytes. The cut point backs off until the prefix
    decodes cleanly, so multi-byte characters never get split in half.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]

    lines: list[str] = []
    # continuation lines start with a space, which costs one octet
    limit = 75
    while encoded:
        cut = min(limit, len(encoded))
        while cut > 0:
            try:
                chunk = encoded[:cut].decode("utf-8")
                break
            except UnicodeDecodeError:
                cut -= 1
        lines.append(chunk)
        encoded = encoded[cut:]
        limit = 74

    return [lines[0]] + [" " + rest for rest in lines[1:]]


def _fmt_date(d: date) -> str:
    """RFC 5545 DATE format: YYYYMMDD, no dashes."""
    return d.strftime("%Y%m%d")


# ---- component builders ----


def _vevent(item: ReviewedItem, dtstamp: str) -> list[str]:
    """All-day VEVENT for a dated deadline."""
    assert item.date is not None
    return [
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@syllabus-to-calendar",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{_fmt_date(item.date)}",
        # exclusive end: next day means a single-day event
        f"DTEND;VALUE=DATE:{_fmt_date(item.date + timedelta(days=1))}",
        f"SUMMARY:{_escape_text(item.title)}",
        "END:VEVENT",
    ]


def _vtodo(item: ReviewedItem, dtstamp: str) -> list[str]:
    """VTODO with no DUE, for items where the date is unknown."""
    return [
        "BEGIN:VTODO",
        f"UID:{uuid.uuid4()}@syllabus-to-calendar",
        f"DTSTAMP:{dtstamp}",
        f"SUMMARY:{_escape_text(item.title)}",
        "END:VTODO",
    ]


# ---- public API ----


def generate_ics(items: list[ReviewedItem], calendar_name: str = "Syllabus") -> str:
    """Build the .ics text, CRLF line endings, ready to send as text/calendar."""
    if not items:
        raise IcsValidationError("No items to export.")

    # one DTSTAMP shared by every component in the file
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Syllabus to Calendar//EN",
        # display name for the calendar
        f"X-WR-CALNAME:{_escape_text(calendar_name)}",
    ]

    for item in items:
        builder = _vevent if item.date is not None else _vtodo
        lines.extend(builder(item, dtstamp))

    lines.append("END:VCALENDAR")

    physical: list[str] = []
    for line in lines:
        physical.extend(_fold(line))
    return "\r\n".join(physical) + "\r\n"


def parse_reviewed_items(payload: list[dict]) -> list[ReviewedItem]:
    """Validate the JSON rows from the review screen into ReviewedItems."""
    if not isinstance(payload, list) or not payload:
        raise IcsValidationError("Expected a non-empty list of items.")

    items: list[ReviewedItem] = []
    for i, row in enumerate(payload, start=1):
        title = str(row.get("title", "")).strip()
        if not title:
            raise IcsValidationError(f"Item {i} has an empty title.")

        raw_date = row.get("date")
        unknown = bool(row.get("unknownDate"))

        if unknown or not raw_date:
            parsed = None
        else:
            try:
                parsed = date.fromisoformat(raw_date)
            except (TypeError, ValueError):
                raise IcsValidationError(
                    f"Item {i} ('{title}') has an invalid date: {raw_date!r}."
                )

        items.append(ReviewedItem(title=title, date=parsed))

    return items
