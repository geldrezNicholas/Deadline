"""Phase 1/4 smoke test: exercises the route wiring without hitting Gemini.

The parse pipeline is two endpoints (split in Phase 4 so the progress
indicator reflects real state): /extract-text (upload -> text) and
/extract-items (text -> Gemini items).

Run:  venv\Scripts\python.exe tests\smoke_phase1.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as a  # noqa: E402

client = a.app.test_client()


def show(label, resp, expect):
    print(f"{label:<30} -> {resp.status_code}  {resp.get_json()}  (expect {expect})")


# 1. index page renders
r = client.get("/")
print(f"{'GET /':<30} -> {r.status_code}  (expect 200)")

# 2. missing file part
show("POST /extract-text (no file)", client.post("/extract-text", data={}), 400)

# 3. wrong extension
show(
    "POST /extract-text (.txt)",
    client.post(
        "/extract-text",
        data={"file": (io.BytesIO(b"x"), "notes.txt")},
        content_type="multipart/form-data",
    ),
    400,
)

# 4. malformed PDF -> 422 from pdf_extract
show(
    "POST /extract-text (bad pdf)",
    client.post(
        "/extract-text",
        data={"file": (io.BytesIO(b"not a real pdf"), "syllabus.pdf")},
        content_type="multipart/form-data",
    ),
    422,
)

# 5. /extract-items rejects empty/missing text without calling Gemini
show("POST /extract-items (no text)", client.post("/extract-items", json={}), 400)
show(
    "POST /extract-items (blank)",
    client.post("/extract-items", json={"text": "   "}),
    400,
)

print("\nSmoke test complete.")
