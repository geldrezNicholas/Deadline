"""List events on the connected Google Calendar for early 2025 (verification)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import requests
from syllabus.google_oauth import get_valid_access_token

token = get_valid_access_token()
resp = requests.get(
    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
    headers={"Authorization": f"Bearer {token}"},
    params={
        "timeMin": "2025-01-01T00:00:00Z",
        "timeMax": "2025-05-01T00:00:00Z",
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "50",
    },
    timeout=30,
)
resp.raise_for_status()
events = resp.json().get("items", [])

print(f"{len(events)} event(s) on the PRIMARY Google calendar, Jan-Apr 2025:\n")
for e in events:
    start = e.get("start", {}).get("date") or e.get("start", {}).get("dateTime")
    print(f"  {start}  {e.get('summary')}")
