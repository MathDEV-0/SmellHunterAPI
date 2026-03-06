import datetime
from datetime import timezone
from xml.parsers.expat import model
from flask import Flask, request, jsonify
from app.interpreter_core import run_interpretation
import os
import io
import csv
import json
import time
import uuid
import re
import traceback
from app.events.event_types import EventTypes
from app.events.observers import ValidationObserver
from app.events.event_types import EventTypes

# Configs for sheets persistence

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

app = Flask(__name__)

#Inicialização dos Observers
from app.events.event_bus import EventBus
from app.events.observers import CsvSheetsObserver, LogObserver, ConsoleAuditObserver, ValidationLoggerObserver
from app.events.validation_service import ValidationService
from app.events.observers import InterpreterWorker
from app.repositories.sheets_repository import SheetsRepository
from app.events.observers import PersistenceWorker
from app.events.observers import SheetsPersistenceObserver
from app.events.observers import EventBusLoggerObserver

event_bus = EventBus()
validation_service = ValidationService()
validation_observer = ValidationObserver(validation_service, event_bus)
interpreter_worker = InterpreterWorker(event_bus)

#Persistence

repository = SheetsRepository()
persistence_worker = PersistenceWorker(repository, event_bus)
sheets_persistence_observer = SheetsPersistenceObserver(repository)



# Register observers
# Validation flow
event_bus.subscribe(EventTypes.METRICS_VALIDATION_REQUESTED,validation_observer)

event_bus.subscribe(EventTypes.VALIDATION_COMPLETED,ValidationLoggerObserver())

event_bus.subscribe(EventTypes.VALIDATION_COMPLETED,interpreter_worker)


# Analysis flow
event_bus.subscribe(EventTypes.ANALYSIS_COMPLETED,LogObserver())

event_bus.subscribe(EventTypes.ANALYSIS_COMPLETED,ConsoleAuditObserver())

event_bus.subscribe(EventTypes.ANALYSIS_COMPLETED,CsvSheetsObserver())

event_bus.subscribe(EventTypes.ANALYSIS_COMPLETED,persistence_worker)

# Persistence flow
event_bus.subscribe(EventTypes.PERSISTENCE_COMPLETED,sheets_persistence_observer)

#Log flow
logger = EventBusLoggerObserver(repository)

event_bus.subscribe(EventTypes.METRICS_VALIDATION_REQUESTED, logger)
event_bus.subscribe(EventTypes.VALIDATION_COMPLETED, logger)
event_bus.subscribe(EventTypes.ANALYSIS_COMPLETED, logger)
event_bus.subscribe(EventTypes.PERSISTENCE_COMPLETED, logger)
#Utils
def normalize_env(env_raw: dict) -> dict:
    env = {}

    for key, value in env_raw.items():
        if "." in key:
            smell, feature = key.split(".", 1)
            env[(smell, feature)] = value
        else:
            env[key] = value

    return env


'''
receive_request()

generate_cod_ctx()

validate()

publish("VALIDATION_COMPLETED")

if invalid:
    return 400

interpret()

publish("ANALYSIS_COMPLETED")

return 202
'''
@app.route("/asynchAnalisis", methods=["POST"])
def asynchAnalisis():

    try:

        if not request.form and not request.files:
            return jsonify({"error": "form-data required"}), 400

        user_id = request.form.get("user_id")

        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        smell_dsl = request.files["smell_dsl"].read().decode("utf-8")
        env_raw = json.load(request.files["metrics"])

        cod_ctx = str(uuid.uuid4())
        smell_id = request.form.get("id") or str(uuid.uuid4())
        org_id = request.form.get("org_id")

        timestamp = datetime.datetime.now(timezone.utc).isoformat()

        event_payload = {
            "ctx_id": cod_ctx,
            "id": smell_id,
            "timestamp_utc": timestamp,
            "user_id": user_id,
            "metrics": env_raw,
            "smell_dsl": smell_dsl,
            "request_data": dict(request.form)
        }

        event_bus.publish(
            EventTypes.METRICS_VALIDATION_REQUESTED,
            event_payload
        )

        return jsonify({
            "status": "accepted",
            "ctx_id": cod_ctx,
            "smell_id": smell_id
        }), 202

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
def main():
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()