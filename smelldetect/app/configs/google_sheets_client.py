from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.configs.settings import SERVICE_ACCOUNT_FILE, SCOPES


def create_sheets_client():

    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )

    service = build(
        "sheets",
        "v4",
        credentials=credentials
    )

    return service