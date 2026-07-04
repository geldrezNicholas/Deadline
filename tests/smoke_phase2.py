"""Phase 2 smoke test: the review markup renders and static assets are served."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as a  # noqa: E402

client = a.app.test_client()

html = client.get("/").get_data(as_text=True)
checks = {
    "review section present": 'class="review"' in html,
    "editable row template": 'x-for="row in rows"' in html,
    "amber class binding": "row--unsure" in html,
    "no-date toggle": "onUnknownToggle(row)" in html,
    "add-row button": "Add item manually" in html,
    "delete-row button": "deleteRow(row.id)" in html,
}
for name, ok in checks.items():
    print(f"  [{'OK' if ok else 'FAIL'}] {name}")

# Static assets resolve (200).
for path in ("/static/js/app.js", "/static/css/style.css"):
    r = client.get(path)
    print(f"  [{'OK' if r.status_code == 200 else 'FAIL'}] GET {path} -> {r.status_code}")

print("\nPhase 2 markup smoke test complete.")
