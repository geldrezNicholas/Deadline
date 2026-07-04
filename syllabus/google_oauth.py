"""Google OAuth 2.0, authorization code flow with PKCE.

The flow:
    1. redirect the user to Google's consent page   (build_auth_request)
    2. Google redirects back with ?code=...          (the /oauth2callback route)
    3. exchange the code for tokens, server to server (exchange_code)
    later: trade the refresh_token for new access tokens as they expire
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode

import requests

from . import db

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# create/edit events only
SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleAuthError(Exception):
    pass


def is_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def is_connected(sid: str) -> bool:
    return db.get_tokens(sid) is not None


def _b64url(raw: bytes) -> str:
    # PKCE wants base64url without padding
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_auth_request(redirect_uri: str) -> dict:
    """Build the consent page URL plus what the callback needs to verify it.

    Returns {url, state, code_verifier}. state and code_verifier get stored
    in the user's session, the URL only carries the hash of the verifier.
    """
    state = secrets.token_urlsafe(32)
    code_verifier = _b64url(os.urandom(32))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())

    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # offline gets us a refresh_token, prompt=consent makes Google
        # reissue one on repeat connects
        "access_type": "offline",
        "prompt": "consent",
    }
    return {
        "url": f"{AUTH_ENDPOINT}?{urlencode(params)}",
        "state": state,
        "code_verifier": code_verifier,
    }


def _token_request(data: dict) -> dict:
    try:
        resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=30)
    except requests.RequestException as exc:
        raise GoogleAuthError(f"Token endpoint unreachable: {exc}") from exc
    payload = resp.json() if resp.content else {}
    if resp.status_code != 200:
        detail = payload.get("error_description") or payload.get("error") or resp.text
        raise GoogleAuthError(f"Token request failed: {detail}")
    return payload


def exchange_code(sid: str, code: str, redirect_uri: str, code_verifier: str) -> None:
    """Trade the one-time authorization code for tokens and store them."""
    payload = _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "code_verifier": code_verifier,
    })
    db.save_tokens(
        sid=sid,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_in=payload.get("expires_in", 3600),
        scope=payload.get("scope"),
    )


def refresh_access_token(sid: str, refresh_token: str) -> None:
    payload = _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
    })
    db.save_tokens(
        sid=sid,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),  # usually absent on refresh
        expires_in=payload.get("expires_in", 3600),
        scope=payload.get("scope"),
    )


def get_valid_access_token(sid: str) -> str:
    """Return a non-expired access token, refreshing it first if needed."""
    tokens = db.get_tokens(sid)
    if tokens is None:
        raise GoogleAuthError("Google Calendar is not connected.")

    if db.access_token_expired(tokens):
        if not tokens.get("refresh_token"):
            db.delete_tokens(sid)
            raise GoogleAuthError("Session expired and no refresh token; please reconnect.")
        refresh_access_token(sid, tokens["refresh_token"])
        tokens = db.get_tokens(sid)

    return tokens["access_token"]


def disconnect(sid: str) -> None:
    """Revoke the grant at Google (best effort) and forget the local tokens."""
    tokens = db.get_tokens(sid)
    if tokens:
        token = tokens.get("refresh_token") or tokens["access_token"]
        try:
            requests.post(REVOKE_ENDPOINT, params={"token": token}, timeout=15)
        except requests.RequestException:
            pass  # revocation is best effort
    db.delete_tokens(sid)
