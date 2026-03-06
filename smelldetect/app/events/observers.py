import csv
import os
import json
from app.events.event_types import EventTypes
from app.interpreter_core import run_interpretation

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
        
class EventBusLoggerObserver:

    def __init__(self, sheets_repository):
        self.repo = sheets_repository

    def notify(self, event_type, data):

        ctx_id = data.get("ctx_id")
        user_id = data.get("user_id")
        org_id = data.get("request_data", {}).get("org_id", "")
        loc_id = data.get("request_data", {}).get("loc_id", "")
        timestamp = data.get("timestamp_utc")

        row = [
            ctx_id,
            user_id,
            org_id,
            loc_id,
            timestamp,
            event_type
        ]

        self.repo.append_context_event(row)

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

class ValidationObserver:

    def __init__(self, validation_service, event_bus):
        self.validation_service = validation_service
        self.event_bus = event_bus

    def notify(self, event_type, data):

        if event_type != EventTypes.METRICS_VALIDATION_REQUESTED:
            return

        smell_dsl = data["smell_dsl"]
        metrics = data["metrics"]

        result = self.validation_service.validate(smell_dsl, metrics)

        if result["valid"]:

            self.event_bus.publish(
                EventTypes.VALIDATION_COMPLETED,
                {**data, "validation": result}
            )

        else:

            self.event_bus.publish(
                EventTypes.VALIDATION_FAILED,
                {**data, "validation": result}
            )
class InterpreterWorker:

    def __init__(self, event_bus):
        self.event_bus = event_bus

    def notify(self, event_type, data):

        if event_type != EventTypes.VALIDATION_COMPLETED:
            return

        smell_dsl = data["smell_dsl"]
        env_raw = data["metrics"]

        # normalização
        env = {}
        for key, value in env_raw.items():
            if "." in key:
                smell, feature = key.split(".", 1)
                env[(smell, feature)] = value
            else:
                env[key] = value

        
        result = run_interpretation(env, smell_dsl)

        print(f"[INTERPRETER] ctx={data['ctx_id']} running analysis")

        analysis = {
            "smells": result.get("smells", []),
            "rules": result.get("rules", {}),
            "treatments": result.get("treatments", {}),
            "interpreted": result.get("interpreted", False)
        }

        payload = {
            **data,
            "analysis": analysis
        }

        self.event_bus.publish(
            EventTypes.ANALYSIS_COMPLETED,
            payload
        )

class PersistenceWorker:

    def __init__(self, repository, event_bus):
        self.repository = repository
        self.event_bus = event_bus

    def notify(self, event_type, data):

        if event_type != EventTypes.ANALYSIS_COMPLETED:
            return

        ctx = data["ctx_id"]
        print(f"[PERSISTENCE] ctx={ctx} saving analysis")

        analysis = data.get("analysis", {})

        payload = self._build_payload(data, analysis)

        record_id = self.repository.save_or_update(payload)

        self.event_bus.publish(
            EventTypes.PERSISTENCE_COMPLETED,
            {
                **data,
                "persisted_id": record_id,
                "persisted_record": payload
            }
        )

    def _build_payload(self, data, analysis):

        smells = analysis.get("smells", [])
        rules = analysis.get("rules", {})
        treatments = analysis.get("treatments", {})

        smell_types = data.get("request_data", {}).get("smell_type", "")

        return {
            "id": data["id"],
            "timestamp_utc": data["timestamp_utc"],
            "time_zone": "UTC",
            "user_id": data["user_id"],
            "org_id": data["request_data"].get("org_id", ""),
            "loc_id": data["request_data"].get("loc_id", ""),
            "project_id": data["request_data"].get("project_id", ""),
            "type": ", ".join(smells),
            "smell_type": smell_types,
            "is_smell": "YES" if rules and all(rules.values()) else "NO",
            "rule": rules,
            "file_path": data["request_data"].get("file_path", ""),
            "language": data["request_data"].get("language", ""),
            "branch": data["request_data"].get("branch", ""),
            "commit_sha": data["request_data"].get("commit_sha", ""),
            "ctx_id": data["ctx_id"],
            "treatment": " | ".join(treatments.values())
        }
    
class SheetsPersistenceObserver:

    def __init__(self, sheets_repository):
        self.repo = sheets_repository

    def notify(self, event_type, data):

        if event_type != EventTypes.PERSISTENCE_COMPLETED:
            return

        print(f"[SHEETS] ctx={data['ctx_id']} sending to sheets")

        record = data.get("persisted_record")

        if not record:
            return

        row = [
            record.get("id"),
            record.get("timestamp_utc"),
            record.get("time_zone"),
            record.get("user_id"),
            record.get("org_id"),
            record.get("loc_id"),
            record.get("project_id"),
            record.get("type"),
            record.get("smell_type"),
            record.get("is_smell"),
            json.dumps(record.get("rule", {})),
            record.get("file_path"),
            record.get("language"),
            record.get("branch"),
            record.get("commit_sha"),
            record.get("ctx_id"),
            record.get("treatment")
        ]

        self.repo.upsert_record(
            record.get("id"),
            row
        )

        context_row = [
            data.get("ctx_id"),
            record.get("user_id"),
            record.get("org_id"),
            record.get("loc_id"),
            record.get("timestamp_utc"),
            event_type
        ]

        self.repo.append_context_event(context_row)