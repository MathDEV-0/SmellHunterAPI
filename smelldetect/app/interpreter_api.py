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
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoETS
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from app.events.event_types import EventTypes
from app.events.observers import StatusWorker, ValidationObserver
from app.events.event_types import EventTypes

# Configs for sheets persistence

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

app = Flask(__name__)

# Initialize event bus and observers
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


#Status
status_worker = StatusWorker()

event_bus.subscribe(EventTypes.ANALYSIS_COMPLETED, status_worker)


# Register observers
# Validation flow
event_bus.subscribe(EventTypes.ANALYSIS_REQUESTED,validation_observer)

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

event_bus.subscribe(EventTypes.ANALYSIS_REQUESTED, logger)
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

def load_metrics(file):

    filename = file.filename.lower()

    if filename.endswith(".json"):
        return json.load(file)

    elif filename.endswith(".csv"):
        decoded = file.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(decoded))

        metrics = {}

        for row in reader:
            metric = row["Metrica"].strip()
            value = float(row["Valor"])
            metrics[metric] = value

        return metrics

    else:
        raise ValueError("Unsupported metrics format. Use CSV or JSON.")
    

def safe_json_parse(value, default=None):
    """
    Safely parse a value that could be a JSON string, dict, or other type
    """
    if default is None:
        default = {} if isinstance(value, (dict, str)) else value
    
    if isinstance(value, dict):
        return value
    elif isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return default
    else:
        return default
    
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
@app.route("/analyze", methods=["POST"])
def asynchAnalisis():

    try:
        if request.is_json:
            data = request.get_json()

            user_id = data.get("user_id", "")
            smell_dsl = data.get("smell_dsl")
            metrics = data.get("metrics", {})
            thresholds = data.get("thresholds", {})
            
            # print(f"[DEBUG] Received metrics keys: {list(metrics.keys())}")
            # print(f"[DEBUG] Received thresholds keys: {list(thresholds.keys())}")
            
        else:
            if not request.form and not request.files:
                return jsonify({"error": "form-data required"}), 400

            user_id = request.form.get("user_id", "")
            if not user_id:
                return jsonify({"error": "user_id required"}), 400

            smell_dsl = request.files["smell_dsl"].read().decode("utf-8")
            metrics_file = request.files["metrics"]
            metrics = load_metrics(metrics_file)
            

            thresholds = {}
            if "thresholds" in request.files:
                thresholds_file = request.files["thresholds"]
                thresholds = load_metrics(thresholds_file)
                # print(f"[DEBUG] Loaded thresholds keys: {list(thresholds.keys())}")

        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        
        cod_ctx = str(uuid.uuid4())
        smell_id = data.get("request_data", {}).get("id", str(uuid.uuid4()))

        timestamp = datetime.datetime.now(timezone.utc).isoformat()

        event_payload = {
            "ctx_id": cod_ctx,
            "id": smell_id,
            "timestamp_utc": timestamp,
            "user_id": user_id,
            "metrics": metrics,
            "thresholds": thresholds, 
            "smell_dsl": smell_dsl,
            "request_data": data.get("request_data", {})
        }

        # print(f"[DEBUG] Event payload keys: {list(event_payload.keys())}")
        # print(f"[DEBUG] Thresholds in payload: {list(thresholds.keys())}")

        event_bus.publish(
            EventTypes.ANALYSIS_REQUESTED,
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

@app.route("/status/<ctx_id>", methods=["GET"])
def status(ctx_id):

    result = status_worker.get(ctx_id)

    if not result:
        return jsonify({
            "status": "processing"
        }), 200

    return jsonify(result), 200

@app.route("/forecast/<project_id>", methods=["GET"])
def forecast(project_id):
    try:
        # --------------------------------
        # Lê os registros do Google Sheets
        # --------------------------------
        repository = SheetsRepository()
        df_smell = repository.get_bad_smell_records(project_id)

        if df_smell.empty:
            return jsonify({"error": f"No Bad_Smell records found for project {project_id}"}), 404

        # --------------------------------
        # Converte is_smell para 0/1 e timestamp
        # --------------------------------
        df_smell['target'] = df_smell['is_smell'].apply(lambda x: 1 if x == 'YES' else 0)
        df_smell['timestamp'] = pd.to_datetime(df_smell['timestamp_utc'])

        # --------------------------------
        # Agrega por dia
        # --------------------------------
        df_daily = df_smell.groupby(['project_id', df_smell['timestamp'].dt.date])['target'].sum().reset_index()
        df_daily.rename(columns={'timestamp': 'ds', 'project_id': 'id', 'target': 'y'}, inplace=True)

        # --------------------------------
        # DEBUG: informações da série
        # --------------------------------
        print(f"[DEBUG] df_daily.shape: {df_daily.shape}")
        print(df_daily.head(10))
        print(df_daily['id'].value_counts())
        print(df_daily['y'].describe())

        # --------------------------------
        # Checa se tem dados suficientes
        # --------------------------------
        if len(df_daily) < 2:
            return jsonify({
                "error": "tiny dataset: not enough data points for forecasting",
                "rows": len(df_daily)
            }), 400

        # --------------------------------
        # Cria o modelo StatsForecast
        # --------------------------------
        from statsforecast import StatsForecast
        from statsforecast.models import AutoETS, Naive

        if len(df_daily) < 5:
            print(f"[DEBUG] tiny dataset detected ({len(df_daily)} rows), using Naive")
            model_to_use = Naive()
        else:
            model_to_use = AutoETS(season_length=1)

        model = StatsForecast(models=[model_to_use], freq='D')

        # --------------------------------
        #  Faz o forecast 30 dias
        # --------------------------------
        future_df = model.forecast(df=df_daily, h=30, id_col='id', time_col='ds', target_col='y')

        # --------------------------------
        # Gera gráfico base64 (opcional)
        # --------------------------------
        import os
        import matplotlib.pyplot as plt
        import base64

        # detecta o nome da coluna de forecast (Naive ou AutoETS)
        forecast_col = [c for c in future_df.columns if c != 'ds'][0]

        # garante que os dados estão em float
        future_df[forecast_col] = future_df[forecast_col].astype(float)

        # --------------------------------
        # Gera gráfico
        # --------------------------------
        fig, ax = plt.subplots(figsize=(10, 5))
        df_daily.set_index('ds')['y'].astype(float).plot(ax=ax, marker='o', label='Histórico')
        future_df.set_index('ds')[forecast_col].plot(ax=ax, color='red', label='Forecast')

        ax.set_title(f"Forecast 30 dias - Project {project_id}")
        ax.set_ylabel("Smells previstos")
        ax.legend()

        # --------------------------------
        # Salva PNG na pasta logs
        # --------------------------------
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        png_path = os.path.join(logs_dir, f"forecast_project_{project_id}.png")
        plt.savefig(png_path, format='png')
        plt.close(fig)

        # --------------------------------
        # Gera Base64 a partir do PNG (opcional)
        # --------------------------------
        with open(png_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode('utf-8')

        # png_path e img_base64 estão prontos para usar


        # --------------------------------
        #  Retorna JSON com forecast e gráfico
        # --------------------------------
        return jsonify({
            "project_id": project_id,
            "forecast": future_df.to_dict(orient='records'),
            "plot_base64": img_base64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/smells/<smell_id>", methods=["GET"])
def get_smell_by_id(smell_id):
    """
    Retorna os dados de um smell específico pelo ID
    """
    try:
        # Busca no repositório Sheets
        repository = SheetsRepository()
        smell_data = repository.get_smell_by_id(smell_id)
        
        if not smell_data:
            return jsonify({
                "error": "Smell not found",
                "smell_id": smell_id
            }), 404
        
        # print(f"[API] smell_data keys: {smell_data.keys()}")
        # print(f"[API] rule type: {type(smell_data.get('rule'))}")
        # print(f"[API] metrics type: {type(smell_data.get('metrics'))}")
        
        # Format response, parsing JSON fields if necessary
        response = {
            "id": smell_data.get("id"),
            "ctx_id": smell_data.get("ctx_id"),
            "timestamp_utc": smell_data.get("timestamp_utc"),
            "user_id": smell_data.get("user_id"),
            "org_id": smell_data.get("org_id"),
            "loc_id": smell_data.get("loc_id"),
            "project_id": smell_data.get("project_id"),
            "type": smell_data.get("type"),
            "smell_type": smell_data.get("smell_type"),
            "is_smell": smell_data.get("is_smell") == "YES",
            "rule": safe_json_parse(smell_data.get("rule"), {}),
            "file_path": smell_data.get("file_path"),
            "language": smell_data.get("language"),
            "branch": smell_data.get("branch"),
            "commit_sha": smell_data.get("commit_sha"),
            "treatment": smell_data.get("treatment"),
            "metrics": safe_json_parse(smell_data.get("metrics"), {})
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
def main():
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()