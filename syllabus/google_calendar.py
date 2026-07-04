"""Push reviewed items to the user's primary Google Calendar."""

from __future__ import annotations

from datetime import timedelta

import requests

from .ics_generate import ReviewedItem

EVENTS_ENDPOINT = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleCalendarError(Exception):
    pass


def push_events(items: list[ReviewedItem], access_token: str) -> tuple[int, int]:
    """Create one all-day event per dated item. Returns (created, skipped).

    Items with no date get skipped and counted.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    created = 0
    skipped = 0

    for item in items:
        if item.date is None:
            skipped += 1
            continue

        body = {
            "summary": item.title,
            "start": {"date": item.date.isoformat()},
            "end": {"date": (item.date + timedelta(days=1)).isoformat()},
        }
        try:
            resp = requests.post(EVENTS_ENDPOINT, json=body, headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise GoogleCalendarError(f"Calendar API unreachable: {exc}") from exc

        if resp.status_code not in (200, 201):
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                pass
            raise GoogleCalendarError(
                f"Failed to create '{item.title}' ({resp.status_code}): {detail}"
            )
        created += 1

    return created, skipped
