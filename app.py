"""Flask routes for Deadline. The actual logic lives in the syllabus package."""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import quote

from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

from syllabus import db, google_oauth
from syllabus.pdf_extract import PdfExtractionError, extract_text
from syllabus.gemini_client import GeminiError, extract_items
from syllabus.google_calendar import GoogleCalendarError, push_events
from syllabus.ics_generate import (
    IcsValidationError,
    generate_ics,
    parse_reviewed_items,
)

load_dotenv()

app = Flask(__name__)

# PRODUCTION=1 is set on the deploy host
PRODUCTION = os.getenv("PRODUCTION") == "1"

# signs the session cookie (OAuth state, PKCE verifier, session id).
# a real secret is required in production, the fallback is dev only
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-insecure-secret")
if PRODUCTION and not os.getenv("FLASK_SECRET_KEY"):
    raise RuntimeError("FLASK_SECRET_KEY must be set in production")

if PRODUCTION:
    # trust the hosting proxy's headers for https URLs and real client IPs
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    # Lax keeps the cookie on the redirect back from Google
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=PRODUCTION,
)

db.init_db()

# upload size cap
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

ALLOWED_EXTENSION = ".pdf"

# cap on how much text gets sent to Gemini
MAX_SYLLABUS_CHARS = 150_000

# in-memory rate limits, reset on restart
UPLOAD_LIMIT = 20         # PDF uploads per hour per IP
PARSE_LIMIT = 10          # Gemini parses per hour per IP
PARSE_GLOBAL_LIMIT = 100  # Gemini parses per day, everyone combined
HOUR = 3600
DAY = 86400

_upload_hits: dict[str, deque] = defaultdict(deque)
_parse_hits: dict[str, deque] = defaultdict(deque)
_parse_hits_global: deque = deque()


def _prune(hits: deque, window: float) -> None:
    now = time.time()
    while hits and hits[0] < now - window:
        hits.popleft()


def _rate_limited(store: dict[str, deque], ip: str, limit: int, window: float) -> bool:
    # clear out stale IP entries once the dict gets big
    if len(store) > 1000:
        for key in list(store):
            _prune(store[key], window)
            if not store[key]:
                del store[key]

    hits = store[ip]
    _prune(hits, window)
    if len(hits) >= limit:
        return True
    hits.append(time.time())
    return False


def _parse_limited(ip: str) -> bool:
    _prune(_parse_hits_global, DAY)
    if len(_parse_hits_global) >= PARSE_GLOBAL_LIMIT:
        return True
    if _rate_limited(_parse_hits, ip, PARSE_LIMIT, HOUR):
        return True
    _parse_hits_global.append(time.time())
    return False


def _sid() -> str:
    """This visitor's session id, created on first use."""
    if "sid" not in session:
        session["sid"] = secrets.token_urlsafe(32)
        session.permanent = True
    return session["sid"]


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/privacy")
def privacy():
    # Google's OAuth verification requires a public privacy policy URL.
    return render_template("privacy.html")


# the parse pipeline is two requests: /extract-text does the upload and PDF
# reading, /extract-items does the Gemini call. the frontend's progress
# steps advance between them.


@app.post("/extract-text")
def extract_text_route():
    """Validate the upload and return the PDF's raw text."""
    if _rate_limited(_upload_hits, request.remote_addr or "?", UPLOAD_LIMIT, HOUR):
        return jsonify(error="Too many uploads from this address, try again later."), 429

    if "file" not in request.files:
        return jsonify(error="No file part in the request."), 400

    upload = request.files["file"]
    if upload.filename == "":
        return jsonify(error="No file selected."), 400

    if not upload.filename.lower().endswith(ALLOWED_EXTENSION):
        return jsonify(error="Only PDF files are accepted."), 400

    try:
        text = extract_text(upload.stream)
    except PdfExtractionError as exc:
        # 422: well-formed request, unprocessable content
        return jsonify(error=str(exc)), 422

    return jsonify(text=text)


@app.post("/extract-items")
def extract_items_route():
    """Send syllabus text to Gemini, return structured items."""
    if _parse_limited(request.remote_addr or "?"):
        return jsonify(error="Too many parses, try again in an hour."), 429

    data = request.get_json(silent=True)
    text = (data or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Expected JSON with a non-empty 'text' field."), 400

    try:
        items = extract_items(text[:MAX_SYLLABUS_CHARS])
    except GeminiError as exc:
        # 502: upstream service failed, not us
        return jsonify(error=str(exc)), 502

    return jsonify(items=[item.to_dict() for item in items])


@app.post("/generate-ics")
def generate_ics_route():
    """Turn the reviewed rows into a downloadable .ics file."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(error="Expected a JSON body."), 400

    try:
        items = parse_reviewed_items(data.get("items", []))
        ics_text = generate_ics(items)
    except IcsValidationError as exc:
        return jsonify(error=str(exc)), 400

    return Response(
        ics_text,
        mimetype="text/calendar",
        headers={
            # attachment makes the browser download instead of navigating
            "Content-Disposition": 'attachment; filename="syllabus.ics"',
        },
    )


# ---- Google Calendar OAuth ----


@app.get("/auth/google/status")
def google_status():
    """Tells the frontend which button to show (connect vs push)."""
    sid = session.get("sid")  # read-only, doesn't create a session
    return jsonify(
        configured=google_oauth.is_configured(),
        connected=bool(sid and google_oauth.is_connected(sid)),
    )


@app.get("/auth/google/start")
def google_start():
    """Send the user off to Google's consent page."""
    if not google_oauth.is_configured():
        return jsonify(error="Google OAuth is not configured (see .env.example)."), 503

    _sid()  # make sure this browser has a session id before we leave

    auth = google_oauth.build_auth_request(
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    # saved for the callback to verify
    session["oauth_state"] = auth["state"]
    session["oauth_code_verifier"] = auth["code_verifier"]
    return redirect(auth["url"])


@app.get("/oauth2callback")
def oauth2callback():
    """Google redirects here with ?code=...&state=..."""
    if request.args.get("error"):
        # e.g. the user hit Cancel on the consent screen
        return redirect("/?google_error=" + quote(request.args["error"]))

    # the state Google echoes back has to match the one we minted
    expected_state = session.pop("oauth_state", None)
    code_verifier = session.pop("oauth_code_verifier", None)
    if not expected_state or request.args.get("state") != expected_state:
        return redirect("/?google_error=state_mismatch")

    try:
        google_oauth.exchange_code(
            sid=_sid(),
            code=request.args.get("code", ""),
            redirect_uri=url_for("oauth2callback", _external=True),
            code_verifier=code_verifier,
        )
    except google_oauth.GoogleAuthError as exc:
        return redirect("/?google_error=" + quote(str(exc)))

    return redirect("/?google=connected")


@app.post("/auth/google/disconnect")
def google_disconnect():
    sid = session.get("sid")
    if sid:
        google_oauth.disconnect(sid)
    return jsonify(ok=True)


@app.post("/push-to-google")
def push_to_google():
    """Create the reviewed items as all-day events on the user's calendar."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(error="Expected a JSON body."), 400

    try:
        items = parse_reviewed_items(data.get("items", []))
    except IcsValidationError as exc:
        return jsonify(error=str(exc)), 400

    sid = session.get("sid")
    if not sid:
        return jsonify(error="Google Calendar is not connected."), 401

    try:
        token = google_oauth.get_valid_access_token(sid)
    except google_oauth.GoogleAuthError as exc:
        return jsonify(error=str(exc)), 401

    try:
        created, skipped = push_events(items, token)
    except GoogleCalendarError as exc:
        return jsonify(error=str(exc)), 502

    return jsonify(created=created, skipped=skipped)


if __name__ == "__main__":
    # dev server only, deploys run gunicorn instead
    app.run(debug=True, port=5000)
