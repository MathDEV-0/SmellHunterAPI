import csv
import os
import json
import re
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

            row = {col: data.get(col, "") for col in self.SHEET_COLUMNS}

            if isinstance(row["rule"], dict):
                row["rule"] = json.dumps(row["rule"], ensure_ascii=False)

            writer.writerow(row)

class ValidationObserver:

    def __init__(self, validation_service, event_bus):
        self.validation_service = validation_service
        self.event_bus = event_bus

    def notify(self, event_type, data):

        print("[VALIDATOR] received:", event_type)

        if event_type != EventTypes.ANALYSIS_REQUESTED:
            return

        smell_dsl = data["smell_dsl"]
        metrics = data["metrics"]
        
        # Get thresholds from payload
        thresholds = data.get("thresholds", {})
        
        # print(f"[VALIDATOR] metrics keys: {list(metrics.keys())}")
        # print(f"[VALIDATOR] thresholds keys: {list(thresholds.keys())}")
        
        # COMBINE metrics and thresholds for validation AND for forwarding
        combined_metrics = {**metrics, **thresholds}
        
        # print(f"[VALIDATOR] combined keys: {list(combined_metrics.keys())}")

        # Validate using the combined metrics (so thresholds are available if needed)
        result = self.validation_service.validate(smell_dsl, combined_metrics)

        if result["valid"]:
            print(f"[VALIDATOR] ctx={data['ctx_id']} validation successful")
            
            # Pass the combined metrics forward
            enriched_data = {
                **data,
                "validation": result,
                "metrics": combined_metrics  # ← CRITICAL: pass combined metrics
            }
            
            self.event_bus.publish(
                EventTypes.VALIDATION_COMPLETED,
                enriched_data
            )

        else:
            print(f"[VALIDATOR] ctx={data['ctx_id']} validation failed: {result.get('errors')}")
            self.event_bus.publish(
                EventTypes.VALIDATION_FAILED,
                {**data, "validation": result}
            )
class InterpreterWorker:

    def __init__(self, event_bus):
        self.event_bus = event_bus

    def notify(self, event_type, data):

        print("[INTERPRETER] received:", event_type)

        if event_type != EventTypes.VALIDATION_COMPLETED:
            return

        smell_dsl = data["smell_dsl"]
        env_raw = data["metrics"]

        # print(f"[INTERPRETER] env_raw keys: {list(env_raw.keys())}")

        # Convert string keys with dots to tuple keys for the interpreter
        env = {}
        for key, value in env_raw.items():
            if "." in key:
                # Split only on first dot to preserve feature names with hyphens
                parts = key.split(".", 1)
                if len(parts) == 2:
                    smell, feature = parts
                    env[(smell, feature)] = value
                else:
                    env[key] = value
            else:
                env[key] = value

        #print(f"[INTERPRETER] converted env keys: {list(env.keys())}")

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

        #print("DATA RECEIVED BY PERSISTENCE:")
        #import json
        #print(json.dumps(data, indent=2))
        self.event_bus.publish(
            EventTypes.PERSISTENCE_COMPLETED,
            {
                **data,
                "persisted_id": record_id,
                "persisted_record": payload
            }
        )

    def _build_payload(self, data, analysis):
        import re

        smells = analysis.get("smells", [])
        rules = analysis.get("rules", {})
        treatments = analysis.get("treatments", {})

        dsl = data.get("smell_dsl", "")

        match = re.search(r"extends\s+(\w+)", dsl, re.IGNORECASE)
        smell_types = match.group(1) if match else ""

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

class StatusWorker:

    def __init__(self):
        self.results = {}

    def notify(self, event_type, data):

        print("[STATUS] received:", event_type)

        if event_type != EventTypes.ANALYSIS_COMPLETED:
            return

        ctx = data["ctx_id"]

        self.results[ctx] = {
            "status": "ok",
            "history": [
                {
                    "cod_ctx": ctx,
                    "status": "INTERPRETED",
                    "details": json.dumps({
                        "result": {
                            "is_smell": len(data["analysis"]["smells"]) > 0,
                            "smells_detected": data["analysis"]["smells"]
                        }
                    })
                }
            ]
        }

    def get(self, ctx):
        return self.results.get(ctx)
    
import pandas as pd

class FeatureEngineeringService:

    def __init__(self, repository):
        self.repository = repository

    def run(self, project_id=None):
        print("[ETL] starting feature engineering")
        df = self.repository.get_unified_context(project_id)

        if df.empty:
            print("[ETL] empty dataset")
            return 0

        df['timestamp'] = pd.to_datetime(df['timestamp_utc'])
        df['target'] = df['is_smell'].apply(lambda x: 1 if x == 'YES' else 0)

        df = df.sort_values("timestamp")

        rows = []

        for _, row in df.iterrows():
            features = self.build_features(row, df)
            rows.append(features)

        print(f"[ETL] generated {len(rows)} rows")

        self.repository.append_warehouse_rows(rows)

        return len(rows)
    
    def build_features(self, row, df):

        now = row["timestamp"]

        #Time feats
        hour_of_day = now.hour
        day_of_week = now.weekday()
        is_weekend = day_of_week >= 5

        df_prev = df[df["timestamp"] < now]

        last_smell = df_prev[
            (df_prev["file_path"] == row["file_path"]) &
            (df_prev["target"] == 1)
        ].sort_values("timestamp").tail(1)

        if not last_smell.empty:
            time_since_last_smell = (
                now - last_smell.iloc[0]["timestamp"]
            ).total_seconds()
        else:
            time_since_last_smell = 0

        last_24h = df[
            (df["timestamp"] >= now - pd.Timedelta(hours=24)) &
            (df["timestamp"] <= now)
        ]

        smell_count_24h = last_24h["target"].sum()

        file_smell_history = df[
            (df["file_path"] == row["file_path"]) &
            (df["target"] == 1)
        ].shape[0]

        next_24h = df[
            (df["timestamp"] > now) &
            (df["timestamp"] <= now + pd.Timedelta(hours=24)) &
            (df["file_path"] == row["file_path"])
        ]

        smells_next_24h = next_24h["target"].sum()
        #User feats
        user_data = df[df["user_id"] == row["user_id"]]

        user_total_commits = len(user_data)

        user_smell_rate = (
            user_data["target"].sum() / len(user_data)
            if len(user_data) > 0 else None
        )

        user_recent_activity = df[
            (df["user_id"] == row["user_id"]) &
            (df["timestamp"] >= now - pd.Timedelta(hours=24))
        ].shape[0]
        
        #File feats
        file_data = df[df["file_path"] == row["file_path"]]

        file_smell_history = file_data[
            file_data["target"] == 1
        ].shape[0]

        file_change_frequency = file_data.shape[0]

        last_mod = file_data.sort_values("timestamp").tail(1)

        file_last_modified_delta = (
            (now - last_mod.iloc[0]["timestamp"]).total_seconds()
            if not last_mod.empty else None
        )

        #Project/Team feats
        # ---------- PROJECT ----------
        project_data = df[df["project_id"] == row["project_id"]]

        team_size = project_data["user_id"].nunique()

        project_age_days = (
            now - project_data["timestamp"].min()
        ).days

        time_span = (
            project_data["timestamp"].max() -
            project_data["timestamp"].min()
        ).total_seconds() / 3600

        commit_velocity = (
            len(project_data) / time_span if time_span > 0 else None
        )

        #Quality of life feature: a combined "smell debt impact" score that considers recency, frequency, and future risk
        smell_debt_impact = (
            (1 + time_since_last_smell) *
            (1 + file_smell_history) *
            (1 + smells_next_24h)
        )



        return {
            "ctx_id": row["ctx_id"],
            "timestamp": row["timestamp"].isoformat(),
            "project_id": row["project_id"],
            "user_id": row["user_id"],
            "file_path": row["file_path"],
            "smell_type": row["smell_type"],
            "is_smell": row["target"],
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
            "time_since_last_smell": time_since_last_smell,
            "time_since_last_commit": None,
            "time_since_last_analysis": time_since_last_smell,
            "user_total_commits": user_total_commits,
            "user_smell_rate": user_smell_rate,
            "user_recent_activity": user_recent_activity,
            "smell_count_24h": smell_count_24h,
            "smell_trend": "stable",
            "file_change_frequency": file_change_frequency,
            "file_smell_history": file_smell_history,
            "file_last_modified_delta": file_last_modified_delta,
            "project_age_days": project_age_days,
            "team_size": team_size,
            "commit_velocity": commit_velocity,
            "smell_debt_impact": smell_debt_impact
        }