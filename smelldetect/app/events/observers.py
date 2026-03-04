import os
import json

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


class LogObserver:

    def notify(self, event_type: str, data: dict):
        cod_ctx = data.get("cod_ctx")
        log_file = os.path.join(LOG_DIR, f"{cod_ctx}.txt")

        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=4))


class ConsoleAuditObserver:

    def notify(self, event_type: str, data: dict):
        print(f"[EVENT RECEIVED] {event_type} -> {data.get('cod_ctx')}")

class ValidationLoggerObserver:

    def notify(self, event_type: str, data: dict):
        if event_type != "VALIDATION_COMPLETED":
            return

        print(f"[VALIDATION] ctx={data.get('cod_ctx')} valid={data.get('validation').get('valid')}")