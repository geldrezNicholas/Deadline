"""OAuth wiring tests, everything that can be verified without real Google
credentials: URL construction, PKCE shape, state CSRF check, token storage,
and endpoint behavior when unconfigured/disconnected.

Run:  venv\Scripts\python.exe tests\test_oauth.py
"""
import base64
import hashlib
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# --- token store round-trip (uses the real app.db; cleans up after) ----------
from syllabus import db  # noqa: E402

SID_A, SID_B = "test-sid-a", "test-sid-b"

db.init_db()
db.delete_tokens(SID_A)
db.delete_tokens(SID_B)

db.save_tokens(SID_A, "at-1", "rt-1", expires_in=3600, scope="s")
t = db.get_tokens(SID_A)
check("tokens persist", t and t["access_token"] == "at-1" and t["refresh_token"] == "rt-1")
check("fresh token not expired", not db.access_token_expired(t))

# A refresh response usually omits refresh_token; the old one must survive.
db.save_tokens(SID_A, "at-2", None, expires_in=3600, scope="s")
t = db.get_tokens(SID_A)
check("refresh keeps old refresh_token", t["access_token"] == "at-2" and t["refresh_token"] == "rt-1")

# Multi-user isolation: user B's connect must not touch user A's tokens.
db.save_tokens(SID_B, "at-B", "rt-B", expires_in=3600, scope="s")
check("two sessions store independent tokens",
      db.get_tokens(SID_A)["access_token"] == "at-2"
      and db.get_tokens(SID_B)["access_token"] == "at-B")

db.delete_tokens(SID_B)
check("deleting one session leaves the other", db.get_tokens(SID_B) is None
      and db.get_tokens(SID_A) is not None)

db.save_tokens(SID_A, "at-3", "rt-1", expires_in=0, scope="s")
check("expiry buffer marks near-expiry token expired", db.access_token_expired(db.get_tokens(SID_A)))

db.delete_tokens(SID_A)
check("disconnect clears tokens", db.get_tokens(SID_A) is None)

# --- auth URL + PKCE ----------------------------------------------------------
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"

from syllabus import google_oauth  # noqa: E402

auth = google_oauth.build_auth_request("http://localhost:5000/oauth2callback")
q = parse_qs(urlparse(auth["url"]).query)

check("auth URL targets Google", auth["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
check("requests offline access (refresh token)", q["access_type"] == ["offline"])
check("least-privilege scope (calendar.events)", q["scope"] == ["https://www.googleapis.com/auth/calendar.events"])
check("state present and returned to caller", q["state"] == [auth["state"]])
check("PKCE method is S256", q["code_challenge_method"] == ["S256"])

expected_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(auth["code_verifier"].encode()).digest()
).rstrip(b"=").decode()
check("code_challenge = SHA256(verifier)", q["code_challenge"] == [expected_challenge])
check("client secret NOT in the browser URL", "test-secret" not in auth["url"])

# --- endpoints ----------------------------------------------------------------
import app as a  # noqa: E402
client = a.app.test_client()

r = client.get("/auth/google/status")
check("status: configured (env set), not connected",
      r.get_json() == {"configured": True, "connected": False})

r = client.get("/auth/google/start")
check("start redirects to Google consent", r.status_code == 302
      and r.headers["Location"].startswith("https://accounts.google.com"))

# Callback with a forged/mismatched state must be rejected.
r = client.get("/oauth2callback?code=fake&state=forged")
check("callback rejects mismatched state", r.status_code == 302
      and "google_error=state_mismatch" in r.headers["Location"])

# User cancelled on the consent screen.
r = client.get("/oauth2callback?error=access_denied")
check("callback surfaces user cancel", "google_error=access_denied" in r.headers["Location"])

# Push without a connection -> 401.
r = client.post("/push-to-google", json={"items": [
    {"title": "HW 1", "date": "2025-10-14", "unknownDate": False},
]})
check("push without connection -> 401", r.status_code == 401)

# A session with stored tokens reports connected; a fresh one doesn't.
with client.session_transaction() as s:
    s["sid"] = "test-sid-status"
db.save_tokens("test-sid-status", "at-x", "rt-x", expires_in=3600, scope="s")
r = client.get("/auth/google/status")
check("status: connected for session with tokens", r.get_json()["connected"] is True)

fresh = a.app.test_client()
r = fresh.get("/auth/google/status")
check("status: fresh session not connected", r.get_json()["connected"] is False)

r = client.post("/auth/google/disconnect")
check("disconnect endpoint clears this session", r.status_code == 200
      and db.get_tokens("test-sid-status") is None)

# Push with invalid rows fails validation before touching auth.
r = client.post("/push-to-google", json={"items": [{"title": "", "date": None}]})
check("push validates rows first -> 400", r.status_code == 400)

# Unconfigured server: start endpoint refuses cleanly.
del os.environ["GOOGLE_CLIENT_ID"]
del os.environ["GOOGLE_CLIENT_SECRET"]
r = client.get("/auth/google/start")
check("start -> 503 when unconfigured", r.status_code == 503)
r = client.get("/auth/google/status")
check("status reports unconfigured", r.get_json()["configured"] is False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
