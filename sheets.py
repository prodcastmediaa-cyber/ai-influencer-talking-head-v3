import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle
from config import SHEET_ID, SHEET_NAME

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TOKEN_FILE = "token.pickle"
CREDS_FILE = "credentials.json"


def get_client():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return gspread.authorize(creds)


def get_sheet():
    client = get_client()
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


def setup_headers():
    sheet = get_sheet()
    headers = [
        "Sr No",
        "Influencer Name",
        "Google Drive Link (Original Video)",
        "Frame Image Link",
        "Status",
    ]
    sheet.update("A1:E1", [headers])
    # Bold the header row
    sheet.format("A1:E1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
    })
    print(f"Headers set. Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}")


def get_pending_rows():
    sheet = get_sheet()
    rows = sheet.get_all_records()
    return [
        (i + 2, row)  # +2 because row 1 is header, list is 0-indexed
        for i, row in enumerate(rows)
        if row.get("Google Drive Link (Original Video)") and not row.get("Status")
    ]


def update_row(row_num, col, value):
    sheet = get_sheet()
    sheet.update_cell(row_num, col, value)
