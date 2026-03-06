import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(BASE_DIR, "configs", "service_account.json")
)

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "182yT9A_gnif3p6rrUiPLSbXAQDRRJ7mlkkKbSvryGYs"
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]