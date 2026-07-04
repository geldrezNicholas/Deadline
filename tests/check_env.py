"""Verify .env has the expected keys without printing the secrets."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import dotenv_values

v = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

for key in ("GEMINI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FLASK_SECRET_KEY"):
    val = v.get(key)
    print(f"  {key:<22} {'set (' + str(len(val)) + ' chars)' if val else 'MISSING'}")

cid = v.get("GOOGLE_CLIENT_ID") or ""
sec = v.get("GOOGLE_CLIENT_SECRET") or ""
print(f"  client id format OK:   {cid.endswith('.apps.googleusercontent.com')}")
print(f"  client secret format:  {'OK' if sec.startswith('GOCSPX-') else 'unexpected (usually starts with GOCSPX-)'}")
