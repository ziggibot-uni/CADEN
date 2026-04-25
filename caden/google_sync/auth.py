"""OAuth for Google Calendar + Tasks.

We use the InstalledAppFlow (local desktop OAuth) because CADEN runs locally.
The user places their Google Cloud OAuth client JSON at
`config.google_credentials_path`. Tokens cache at `config.google_token_path`.

Failure modes are loud: missing credentials file, unreadable token, refresh
failure — all raise GoogleSyncError.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from ..errors import GoogleSyncError

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


def load_credentials(credentials_path: Path, token_path: Path) -> Credentials:
    """Return valid Credentials, running the interactive flow if needed."""
    if not credentials_path.is_file():
        raise GoogleSyncError(
            f"Google OAuth client JSON not found at {credentials_path}. "
            f"Download it from Google Cloud Console and place it there."
        )

    creds: Credentials | None = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            raise GoogleSyncError(
                f"failed to load cached Google token from {token_path}: {e}"
            ) from e

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise GoogleSyncError(
                f"Google token refresh failed: {e}. Delete {token_path} and re-run to re-auth."
            ) from e
    else:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        except Exception as e:
            raise GoogleSyncError(f"Google OAuth flow failed: {e}") from e

    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    except OSError as e:
        raise GoogleSyncError(f"failed to persist Google token to {token_path}: {e}") from e

    return creds
