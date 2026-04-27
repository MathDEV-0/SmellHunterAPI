import csv
import os
import json
import pandas as pd
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

    WAREHOUSE_COLUMNS = [
            "ctx_id",
            "timestamp",
            "project_id",
            "user_id",
            "file_path",
            "smell_type",
            "is_smell",
            "hour_of_day",
            "day_of_week",
            "is_weekend",
            "time_since_last_smell",
            "time_since_last_commit",
            "time_since_last_analysis",
            "user_total_commits",
            "user_smell_rate",
            "user_recent_activity",
            "smell_count_24h",
            "smell_trend",
            "file_change_frequency",
            "file_smell_history",
            "file_last_modified_delta",
            "project_age_days",
            "team_size",
            "commit_velocity",
            "smell_debt_impact"
            ]


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
    # LOCAL CSV (backup / audit)
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
    # SERIALIZATION
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

        # if not in cache, try to find in sheet and update cache 
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

            # reload cache after insert
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

    def get_smell_by_id(self, smell_id):
        """
        Search for a smell by its ID in the Google Sheet and return its data as a dictionary.
        Uses the existing id_cache to find the row and then fetches the full row data.
        """
        try:
            smell_id = str(smell_id)
            print(f"[SHEETS] Getting smell by ID: {smell_id}")
          
            row_index = self.id_cache.get(smell_id)
            
        
            if not row_index:
                print(f"[SHEETS] ID {smell_id} not in cache, searching in sheet...")
                row_index = self.find_smell_row(smell_id)
                
                if row_index:
                    self.id_cache[smell_id] = row_index
                    print(f"[SHEETS] Found ID {smell_id} at row {row_index}, cache updated")
            

            if row_index:
                range_name = f"{self.sheet_name}!A{row_index}:Q{row_index}"
                
                result = self.client.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name
                ).execute()
                
                values = result.get("values", [])
                
                if values and len(values) > 0:
                    row_data = values[0]
                    
                    smell_dict = {}
                    for i, col in enumerate(self.COLUMNS):
                        if i < len(row_data):
                            smell_dict[col] = row_data[i]
                        else:
                            smell_dict[col] = ""
                    
                    if smell_dict.get("rule") and isinstance(smell_dict["rule"], str):
                        try:
                            smell_dict["rule"] = json.loads(smell_dict["rule"])
                        except:
                            pass
                    
                    print(f"[SHEETS] Successfully retrieved smell {smell_id}")
                    return smell_dict
                
            else:
                print(f"[SHEETS] Smell ID {smell_id} not found in sheet")
                return None
            
        except Exception as e:
            print(f"[SHEETS] Error getting smell by id {smell_id}: {e}")
            import traceback
            traceback.print_exc()
            return None    
    
    def get_bad_smell_records(self, project_id: str = None) -> pd.DataFrame:
        """
        Retorna todos os registros da aba 'Bad_Smell' da planilha como DataFrame.
        Se project_id for informado, filtra apenas esse projeto.
        """
        try:
            # Lê explicitamente a aba 'Bad_Smell'
            result = self.client.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="Bad_Smell!A1:Q10000"  # range explícito
            ).execute()
            values = result.get("values", [])

            if not values or len(values) < 2:
                return pd.DataFrame(columns=self.COLUMNS)

            # Constrói DataFrame ignorando a primeira linha (header da planilha)
            df = pd.DataFrame(values[1:], columns=self.COLUMNS)

            # Filtra pelo projeto, se fornecido
            if project_id:
                df = df[df['project_id'] == str(project_id)]

            return df

        except Exception as e:
            print(f"[SHEETS] Error getting smell records: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame(columns=self.COLUMNS)


    def get_event_records(self, project_id: str = None) -> pd.DataFrame:
        """
        Retorna todos os registros da aba 'Context' da planilha como DataFrame.
        Se project_id for informado, filtra apenas esse projeto.
        """
        try:
            context_columns = [
                "ctx_id", "user_id", "org_id", "loc_id",
                "timestamp", "event_type"
            ]

            # Lê explicitamente a aba 'Context'
            result = self.client.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="Context!A1:F10000"  # range explícito
            ).execute()
            values = result.get("values", [])

            if not values or len(values) < 2:
                return pd.DataFrame(columns=context_columns)

            df = pd.DataFrame(values[1:], columns=context_columns)

            # Filtra pelo projeto se houver coluna project_id
            if project_id and "project_id" in df.columns:
                df = df[df['project_id'] == str(project_id)]

            return df

        except Exception as e:
            print(f"[SHEETS] Error getting context records: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame(columns=context_columns)
        
    def get_unified_context(self, project_id: str = None) -> pd.DataFrame:
        df_smell = self.get_bad_smell_records(project_id)
        df_ctx = self.get_event_records(project_id)

        # join por ctx_id (LEFT JOIN smells -> context)
        df = df_smell.merge(
            df_ctx,
            on="ctx_id",
            how="left",
            suffixes=("", "_ctx")
        )

        df['timestamp'] = pd.to_datetime(df['timestamp_utc'])

        df['is_weekend'] = df['timestamp'].dt.weekday >= 5
        df['day_of_week'] = df['timestamp'].dt.weekday
        df['hour'] = df['timestamp'].dt.hour

        # target
        df['target'] = (df['is_smell'] == 'YES').astype(int)

        return df
    #DATA WAREHOUSE FUNCTIONS   
    def append_warehouse_rows(self, rows: list):
        
        def normalize(value):
            
            import numpy as np
            import pandas as pd

            if pd.isna(value):
                return ""

            if isinstance(value, (np.integer,)):
                return int(value)

            if isinstance(value, (np.floating,)):
                return float(value)

            if isinstance(value, (np.bool_,)):
                return bool(value)

            if isinstance(value, (pd.Timestamp,)):
                return value.isoformat()

            return value

        try:
            clean_rows = [
                [normalize(row.get(col)) for col in self.WAREHOUSE_COLUMNS]
                for row in rows
            ]

            body = {
                "values": clean_rows
            }

            self.client.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="Data_Warehouse!A1",
                valueInputOption="RAW",
                body=body
            ).execute()

            print(f"[SHEETS][DW] inserted {len(clean_rows)} rows")

        except Exception as e:
            print(f"[SHEETS][DW] error inserting rows: {e}")
            import traceback
            traceback.print_exc()

    def clear_warehouse(self):
        """Remove all data from the Data_Warehouse sheet except the header."""
        try:
            # Obtém a última linha com dados
            sheet_metadata = self.client.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheets = sheet_metadata.get('sheets', '')
            for sheet in sheets:
                if sheet['properties']['title'] == 'Data_Warehouse':
                    sheet_id = sheet['properties']['sheetId']
                    result = self.client.spreadsheets().values().get(
                        spreadsheetId=self.spreadsheet_id,
                        range='Data_Warehouse!A:A'
                    ).execute()
                    values = result.get('values', [])
                    if len(values) > 1:
                        requests = [{
                            "deleteRange": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 1,  # mantém linha 0 (cabeçalho)
                                    "endRowIndex": len(values)
                                },
                                "shiftDimension": "ROWS"
                            }
                        }]
                        self.client.spreadsheets().batchUpdate(
                            spreadsheetId=self.spreadsheet_id,
                            body={"requests": requests}
                        ).execute()
                        print(f"[SHEETS][DW] Cleanup completed: {len(values)-1} rows removed")
                    else:
                        print("[SHEETS][DW] No data to clean")
                    return
        except Exception as e:
            print(f"[SHEETS][DW] Error during cleanup: {e}")
            raise

    def get_warehouse_data(self, project_id=None):
        """Load all data from the Data_Warehouse sheet as a DataFrame.
        If project_id is provided, filter by it."""
        try:
            result = self.client.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="Data_Warehouse!A:Z"
            ).execute()
            values = result.get('values', [])
            if not values:
                return pd.DataFrame()
            headers = values[0]
            data = values[1:]
            df = pd.DataFrame(data, columns=headers)
            numeric_cols = ['target', 'hour_of_day', 'day_of_week', 'time_since_last_smell',
                            'smell_count_24h', 'file_smell_history', 'smell_debt_impact']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'],format="mixed",errors="coerce",utc=True)
            if project_id:
                df = df[df['project_id'] == str(project_id)]
            return df
        except Exception as e:
            print(f"[SHEETS][DW] Error reading data: {e}")
            return pd.DataFrame()