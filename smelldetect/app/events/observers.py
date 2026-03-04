import csv
import os
import json

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


class LogObserver:

    def notify(self, event_type: str, data: dict):
        cod_ctx = data.get("ctx_id")
        log_file = os.path.join(LOG_DIR, f"{cod_ctx}.txt")

        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=4))


class ConsoleAuditObserver:

    def notify(self, event_type: str, data: dict):
        print(f"[EVENT RECEIVED] {event_type} -> {data.get('ctx_id')}")

class ValidationLoggerObserver:

    def notify(self, event_type: str, data: dict):
        if event_type != "VALIDATION_COMPLETED":
            return

        print(f"[VALIDATION] ctx={data.get('ctx_id')} valid={data.get('validation').get('valid')}")

class CsvSheetsObserver:

    CSV_FILE = "sheets_smells.csv"

    SHEET_COLUMNS = [
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

    def notify(self, event_type: str, data: dict):

        if event_type != "ANALYSIS_COMPLETED":
            return

        file_exists = os.path.isfile(self.CSV_FILE)

        with open(self.CSV_FILE, "a", newline="", encoding="utf-8") as f:

            writer = csv.DictWriter(
                f,
                fieldnames=self.SHEET_COLUMNS
            )

            if not file_exists:
                writer.writeheader()

            # Garante que todas colunas existam
            row = {col: data.get(col, "") for col in self.SHEET_COLUMNS}

            if isinstance(row["rule"], dict):
                row["rule"] = json.dumps(row["rule"], ensure_ascii=False)

            writer.writerow(row)