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

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

app = Flask(__name__)

#Inicialização dos Observers
from app.events.event_bus import EventBus
from app.events.observers import CsvSheetsObserver, LogObserver, ConsoleAuditObserver, ValidationLoggerObserver
from app.events.validation_service import ValidationService

event_bus = EventBus()
validation_service = ValidationService()

# Registrar observers
event_bus.subscribe("ANALYSIS_COMPLETED", LogObserver())
event_bus.subscribe("ANALYSIS_COMPLETED", ConsoleAuditObserver())
event_bus.subscribe("ANALYSIS_COMPLETED", CsvSheetsObserver())
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
        # 1️ - Request form-data
        if not request.form and not request.files:
            return jsonify({"error": "form-data required"}), 400

        user_id = request.form.get("user_id")
        loc_id = request.form.get("loc_id")
        project_id = request.form.get("project_id")
        smell_id = request.form.get("id")

        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        # 2 -  Request DSL
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
        smells_list = result_public.get("smells", [])
        

        #Util para payload builder
        rules = result.get("rules", {})
        smells_list = result.get("smells", [])
        treatments_map = result.get("treatments", {})
        model = result.get("model")

        is_smell_flag = bool(smells_list) and all(rules.values()) if rules else False

        smell_types = []
        if model and hasattr(model, "smells"):
            smell_types = [
                model.smells[name].extends or ""
                for name in smells_list
                if name in model.smells
            ]
        treatments_text = " | ".join(
            treatments_map.get(smell, "")
            for smell in smells_list
            if treatments_map.get(smell)
        )
        # 7 - Salva log completo (com model)
        event_payload = {
            "id": smell_id if smell_id else cod_ctx,
            "timestamp_utc": timestamp,
            "time_zone": "UTC",
            "user_id": user_id,
            "org_id": request.form.get("org_id") or "",
            "loc_id": loc_id or "",
            "project_id": project_id or "",
            "type": ", ".join(smells_list),                
            "smell_type": ", ".join(smell_types),          
            "is_smell": "YES" if is_smell_flag else "NO",  
            "rule": rules,
            "file_path": request.form.get("file_path") or "",
            "language": request.form.get("language") or "",
            "branch": request.form.get("branch") or "",
            "commit_sha": request.form.get("commit_sha") or "",
            "ctx_id": cod_ctx,
            "treatment": treatments_text
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