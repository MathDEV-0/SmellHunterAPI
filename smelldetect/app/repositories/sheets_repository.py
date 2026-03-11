import csv
import os
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.configs.settings import (
    SERVICE_ACCOUNT_FILE,
    SPREADSHEET_ID,
    SCOPES
)


class SheetsRepository:

    FILE = "sheets_smells.csv"
    SHEET_NAME = "Bad_Smell"

    COLUMNS = [
        "id",
        "timestamp_utc",
        "time_zone",
        "user_id",
        "org_id",
        "loc_id",
        "project_id",
        "type",
        "smell_type",
        "is_smell",
        "rule",
        "file_path",
        "language",
        "branch",
        "commit_sha",
        "ctx_id",
        "treatment"
    ]

    def __init__(self):

        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )

        self.client = build(
            "sheets",
            "v4",
            credentials=credentials
        )

        self.spreadsheet_id = SPREADSHEET_ID
        self.sheet_name = self.SHEET_NAME

        self.id_cache = {}

        self._load_id_cache()

    def _load_id_cache(self):

        self.id_cache = {} 

        result = self.client.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A:A"
        ).execute()

        values = result.get("values", [])

        for idx, row in enumerate(values, start=1):
            if row:
                self.id_cache[str(row[0])] = idx

        print(f"[SHEETS] cache loaded {len(self.id_cache)} smells")
    # -----------------------------
    # CSV LOCAL (backup / auditoria)
    # -----------------------------
    def save_or_update(self, payload):

        rows = []
        found = False

        if os.path.exists(self.FILE):

            with open(self.FILE, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:

                    if row["id"] == payload["id"]:
                        rows.append(self._serialize(payload))
                        found = True
                    else:
                        rows.append(row)

        if not found:
            rows.append(self._serialize(payload))

        with open(self.FILE, "w", newline="", encoding="utf-8") as f:

            writer = csv.DictWriter(
                f,
                fieldnames=self.COLUMNS
            )

            writer.writeheader()

            for r in rows:
                writer.writerow(r)

        return payload["id"]

    # -----------------------------
    # SERIALIZAÇÃO
    # -----------------------------
    def _serialize(self, payload):

        row = {c: payload.get(c, "") for c in self.COLUMNS}

        if isinstance(row["rule"], dict):
            row["rule"] = json.dumps(row["rule"])

        return row

    # -----------------------------
    # GOOGLE SHEETS
    # -----------------------------
    def append_rows(self, rows):

        body = {
            "values": rows
        }

        self.client.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=self.sheet_name,
            valueInputOption="RAW",
            body=body
        ).execute()

    def find_smell_row(self, smell_id: str):
        result = self.client.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range="Bad_Smell!A:A"
        ).execute()

        values = result.get("values", [])

        for idx, row in enumerate(values, start=1):
            if row and row[0] == smell_id:
                return idx

        return None
    
    def upsert_record(self, smell_id: str, row_data: list):

        smell_id = str(smell_id)

        row_index = self.id_cache.get(smell_id)

        # se não estiver no cache, procura na planilha
        if not row_index:
            row_index = self.find_smell_row(smell_id)

            if row_index:
                self.id_cache[smell_id] = row_index

        if row_index:

            print(f"[SHEETS] updating smell_id={smell_id} row={row_index}")

            self.client.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A{row_index}",
                valueInputOption="RAW",
                body={"values": [row_data]}
            ).execute()

        else:

            print(f"[SHEETS] inserting smell_id={smell_id}")

            self.client.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": [row_data]}
            ).execute()

            # recarrega cache real da planilha
            self._load_id_cache()
        
    def append_context_event(self, row):

        body = {
            "values": [row]
        }

        self.client.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range="Context!A1",
            valueInputOption="RAW",
            body=body
        ).execute()