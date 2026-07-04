"""Phase 3 tests: ICS generation correctness + the /generate-ics endpoint.

Run:  venv\Scripts\python.exe tests\test_ics.py
"""
import io
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syllabus.ics_generate import (  # noqa: E402
    IcsValidationError,
    ReviewedItem,
    generate_ics,
    parse_reviewed_items,
    _escape_text,
    _fold,
)

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK]   {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


# --- escaping ---------------------------------------------------------------
check("escapes ; , and newline",
      _escape_text("a;b,c\nd") == "a\\;b\\,c\\nd")
check("escapes backslash first (no double-escape)",
      _escape_text("a\\;") == "a\\\\\\;")

# --- folding ----------------------------------------------------------------
long_line = "SUMMARY:" + "x" * 200
folded = _fold(long_line)
check("long line is folded", len(folded) > 1)
check("every physical line <= 75 octets",
      all(len(l.encode("utf-8")) <= 75 for l in folded))
check("continuation lines start with a space",
      all(l.startswith(" ") for l in folded[1:]))
check("unfolding reproduces the original",
      folded[0] + "".join(l[1:] for l in folded[1:]) == long_line)

# Multi-byte safety: é is 2 octets in UTF-8; a run of them forces split points
# that would land mid-character if we counted characters instead of octets.
accented = "SUMMARY:" + "é" * 100
folded_acc = _fold(accented)
check("multi-byte content folds without mid-char splits",
      all(len(l.encode("utf-8")) <= 75 for l in folded_acc)
      and folded_acc[0] + "".join(l[1:] for l in folded_acc[1:]) == accented)

# --- calendar structure ------------------------------------------------------
ics = generate_ics([
    ReviewedItem(title="HW 1", date=date(2025, 10, 14)),
    ReviewedItem(title="Final exam", date=None),
])

check("uses CRLF line endings", "\r\n" in ics and "\n" not in ics.replace("\r\n", ""))
check("VCALENDAR wrapper", ics.startswith("BEGIN:VCALENDAR") and "END:VCALENDAR" in ics)
check("dated item -> VEVENT", "BEGIN:VEVENT" in ics)
check("all-day DTSTART uses VALUE=DATE", "DTSTART;VALUE=DATE:20251014" in ics)
check("DTEND is exclusive (next day)", "DTEND;VALUE=DATE:20251015" in ics)
check("undated item -> VTODO", "BEGIN:VTODO" in ics)
check("VTODO has no DUE", "DUE" not in ics)
check("both components have UIDs", ics.count("UID:") == 2)
check("both components have DTSTAMP", ics.count("DTSTAMP:") == 2)

# --- payload validation ------------------------------------------------------
items = parse_reviewed_items([
    {"title": "HW 1", "date": "2025-10-14", "unknownDate": False},
    {"title": "Final", "date": "", "unknownDate": True},
])
check("valid payload parses", items[0].date == date(2025, 10, 14) and items[1].date is None)

for bad, why in [
    ([], "empty list"),
    ([{"title": "", "date": "2025-10-14"}], "empty title"),
    ([{"title": "X", "date": "10/14/2025", "unknownDate": False}], "bad date format"),
]:
    try:
        parse_reviewed_items(bad)
        check(f"rejects {why}", False)
    except IcsValidationError:
        check(f"rejects {why}", True)

# --- endpoint ----------------------------------------------------------------
import app as a  # noqa: E402
client = a.app.test_client()

r = client.post("/generate-ics", json={"items": [
    {"title": "HW 1", "date": "2025-10-14", "unknownDate": False},
]})
check("endpoint returns 200", r.status_code == 200)
check("endpoint mimetype is text/calendar", r.mimetype == "text/calendar")
check("endpoint sets attachment filename",
      'attachment; filename="syllabus.ics"' in r.headers.get("Content-Disposition", ""))

r = client.post("/generate-ics", json={"items": [{"title": "", "date": None}]})
check("endpoint 400s on invalid rows", r.status_code == 400)

r = client.post("/generate-ics", data="not json", content_type="text/plain")
check("endpoint 400s on non-JSON body", r.status_code == 400)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
