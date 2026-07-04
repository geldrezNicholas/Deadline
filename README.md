# Deadline

Upload a course syllabus PDF and turn its deadlines into calendar events.

## Stack
- **Backend:** Python + Flask
- **Frontend:** HTML/CSS + Alpine.js (no build step)
- **AI:** Google Gemini (structured JSON output)
- **PDF:** pdfplumber

## Architecture

The pipeline is a straight line, with each stage isolated in `syllabus/`:

```
PDF bytes -> pdf_extract.extract_text    -> raw text         (POST /extract-text)
raw text  -> gemini_client.extract_items -> [ScheduleItem]   (POST /extract-items)
items     -> ics_generate.generate_ics   -> .ics download    (POST /generate-ics)
```

Route handlers in `app.py` stay thin: they handle HTTP and hand off to the
package, so the core logic is testable without a web server.

The parse pipeline is deliberately two HTTP requests instead of one, so the
progress indicator ("Uploading / Reading PDF / Extracting dates") advances on
real signals (upload bytes flushed, first response, second response) instead
of timers.

The `.ics` file is written by hand per RFC 5545: all-day `VALUE=DATE` events
to avoid timezone off-by-a-day bugs, exclusive `DTEND`, 75-octet line folding,
TEXT escaping. Items with unknown dates become `VTODO`s with no `DUE`.

### Google Calendar (OAuth 2.0)

The OAuth flow is hand-rolled in `syllabus/google_oauth.py`: authorization
code flow with PKCE, no Google SDK.

```
GET /auth/google/start -> mint state + PKCE verifier (session cookie),
                          redirect to Google's consent page
GET /oauth2callback    -> verify state (CSRF), exchange code + verifier
                          for tokens, persist in SQLite (app.db)
POST /push-to-google   -> validate rows, refresh access token if expired,
                          create all-day events via the Calendar API
```

Scope is `calendar.events` only (least privilege). Tokens are stored per
browser session (a random `sid` in the signed session cookie keys a row in
SQLite), so concurrent users can't see or overwrite each other's grants.
Access tokens are refreshed about 60s before expiry. Undated items are
skipped on push since the Calendar API has no dateless events, but they still
export as `VTODO`s in the `.ics`.

## Setup (Windows)

```powershell
# 1. Create the venv (one time)
python -m venv venv

# 2. Install deps
venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Add your key
copy .env.example .env   # then edit .env and paste your Gemini key

# 4. Run
venv\Scripts\python.exe app.py
# open http://localhost:5000
```

Get a free Gemini key at <https://aistudio.google.com/apikey>.

To enable the Google Calendar buttons, follow the credential steps in
`.env.example` (Google Cloud project, enable the Calendar API, create an OAuth
client with redirect URI `http://localhost:5000/oauth2callback`).

## Tests

```powershell
venv\Scripts\python.exe tests\smoke_phase1.py   # route wiring, no API key needed
venv\Scripts\python.exe tests\smoke_phase2.py   # review-screen markup
venv\Scripts\python.exe tests\test_ics.py       # ICS correctness
venv\Scripts\python.exe tests\test_oauth.py     # OAuth wiring, no credentials needed
venv\Scripts\python.exe tests\live_gemini.py    # live Gemini call (uses .env key)
```

## Deployment (Render)

1. Push this repo to GitHub (`.env` and `app.db` are gitignored, never commit them).
2. On [render.com](https://render.com): New Web Service, connect the repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
3. Add environment variables: `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, a long random `FLASK_SECRET_KEY`, and `PRODUCTION=1`
   (turns on secure cookies + proxy header handling).
4. In Google Cloud Console, add the production redirect URI to the OAuth
   client: `https://<your-app>.onrender.com/oauth2callback` (keep the
   localhost one for dev).

Free-tier caveats: the filesystem is ephemeral, so `app.db` (OAuth tokens)
resets on each deploy and users just reconnect. The parse endpoint is
rate-limited (per IP and a global daily cap) to protect the shared Gemini
free-tier quota.

### Going fully public (Google verification)

While the OAuth app is in Testing mode, only listed test users can connect.
To open it to anyone: Google Auth Platform > Audience > Publish app, then
submit for verification (required because `calendar.events` is a sensitive
scope). You'll need the app's homepage URL, the privacy policy URL
(`/privacy` is included in this repo), and a short demo of how the scope is
used. Until verification clears, users see an "unverified app" warning they
can click through under Advanced.
