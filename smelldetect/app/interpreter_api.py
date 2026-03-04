import datetime
from datetime import timezone

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

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

app = Flask(__name__)

#Inicialização dos Observers
from app.events.event_bus import EventBus
from app.events.observers import LogObserver, ConsoleAuditObserver, ValidationLoggerObserver
from app.events.validation_service import ValidationService

event_bus = EventBus()
validation_service = ValidationService()

# Registrar observers
event_bus.subscribe("ANALYSIS_COMPLETED", LogObserver())
event_bus.subscribe("ANALYSIS_COMPLETED", ConsoleAuditObserver())
event_bus.subscribe("VALIDATION_COMPLETED", ValidationLoggerObserver())

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
        # -----------------------------
        # 1️ - Request form-data
        # -----------------------------
        if not request.form and not request.files:
            return jsonify({"error": "form-data required"}), 400

        user_id = request.form.get("user_id")
        loc_id = request.form.get("loc_id")
        project_id = request.form.get("project_id")

        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        # -----------------------------
        # 2 -  Request DSL
        # -----------------------------
        if "smell_dsl" not in request.files:
            return jsonify({"error": "smell_dsl file required"}), 400

        smell_dsl = request.files["smell_dsl"].read().decode("utf-8")

        # 3 - Arquivo de métricas (env)
        if "metrics" not in request.files:
            return jsonify({"error": "metrics file required"}), 400

        env_raw = json.load(request.files["metrics"])
        env = normalize_env(env_raw)


        # 4 -  Cria contexto
        cod_ctx = str(uuid.uuid4())
        timestamp = datetime.datetime.now(timezone.utc).isoformat()

        # 5 - Validação
        validation_result = validation_service.validate(smell_dsl, env_raw)

        validation_event = {
            "cod_ctx": cod_ctx,
            "timestamp_utc": timestamp,
            "user_id": user_id,
            "validation": validation_result
        }

        event_bus.publish("VALIDATION_COMPLETED", validation_event)

        # Se inválido retorna erro e não executa análise
        if not validation_result["valid"]:
            return jsonify({
                "status": "validation_failed",
                "cod_ctx": cod_ctx,
                **validation_result
            }), 400
        
        # 6- Executa interpretação
        result = run_interpretation(env, smell_dsl)
        rules = result.get("rules", {})

        result_public = {
            "smells": result.get("smells", []),
            "rules": result.get("rules", {}),
            "interpreted": result.get("interpreted", False),
            "treatments": result.get("treatments", {}),
            "is_smell": bool(rules) and all(rules.values())
        }

        # 7 - Salva log completo (com model)
        event_payload = {
            "cod_ctx": cod_ctx,
            "timestamp_utc": timestamp,
            "user_id": user_id,
            "loc_id": loc_id,
            "project_id": project_id,
            "env": env_raw,
            "result": result_public
        }

        log_file = os.path.join(LOG_DIR, f"{cod_ctx}.txt")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(event_payload, indent=4))

        event_bus.publish("ANALYSIS_COMPLETED", event_payload)

        # 8 - Retorno assíncrono
        return jsonify({
            "status": "accepted",
            "cod_ctx": cod_ctx,
            **result_public
        }), 202

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
def main():
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()