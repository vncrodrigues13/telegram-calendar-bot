"""Google OAuth for a desktop app: token.json, refreshed or freshly granted."""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Narrower than full calendar access: we only ever create events.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def load_credentials(credentials_path: Path, token_path: Path) -> Credentials:
    """Return usable credentials, opening a browser only when necessary."""
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"{credentials_path} não encontrado. Baixe o OAuth client ID "
                "(tipo 'Desktop app') do Google Cloud Console — veja o README."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path), SCOPES
        )
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds
