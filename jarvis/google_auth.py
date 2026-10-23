"""Google OAuth for Gmail and Calendar.

One-time setup: `python -m jarvis setup-google` opens a browser consent
screen and stores a refresh token at GOOGLE_TOKEN_PATH. After that, tool
calls refresh the token silently.
"""
from . import config


def run_setup():
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not config.GOOGLE_CREDENTIALS_PATH.exists():
        raise SystemExit(
            "OAuth client file not found at {}.\n"
            "Download it from Google Cloud Console (APIs & Services > "
            "Credentials > OAuth client ID > Desktop app) and save it there, "
            "or point GOOGLE_CREDENTIALS_PATH in .env at it.".format(
                config.GOOGLE_CREDENTIALS_PATH
            )
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.GOOGLE_CREDENTIALS_PATH), config.GOOGLE_SCOPES
    )
    creds = flow.run_local_server(port=0)
    config.GOOGLE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print("Google account connected. Token saved to {}".format(config.GOOGLE_TOKEN_PATH))


def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not config.GOOGLE_TOKEN_PATH.exists():
        raise RuntimeError(
            "Google account not connected yet. Run: python -m jarvis setup-google"
        )
    creds = Credentials.from_authorized_user_file(
        str(config.GOOGLE_TOKEN_PATH), config.GOOGLE_SCOPES
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        config.GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds
