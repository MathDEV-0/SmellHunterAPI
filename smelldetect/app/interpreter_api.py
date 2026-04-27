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
from app.events.observers import PersistenceWorker, FeatureEngineeringService
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


# import base64
# from scipy.stats import linregress
# from statsmodels.tsa.seasonal import seasonal_decompose
# from statsforecast import StatsForecast
# from statsforecast.models import (
#     CrostonClassic, CrostonOptimized, CrostonSBA,
#     ADIDA, IMAPA, TSB,
#     AutoARIMA, AutoETS, MSTL,
#     Naive, SeasonalNaive, RandomWalkWithDrift
# )
from statsmodels.tsa.holtwinters import ExponentialSmoothing
# @app.route("/forecast/<project_id>", methods=["GET"])
# def forecast(project_id):
#     try:
#         repository = SheetsRepository()
#         df_smell = repository.get_warehouse_data(project_id)

#         if df_smell.empty:
#             return jsonify({"error": f"No data found for project {project_id}"}), 404

#         print("[DEBUG] Rows available:", df_smell.columns.tolist())
        
#         # LIMPEZA DE DADOS
#         if 'ctx_id' in df_smell.columns:
#             df_smell = df_smell.drop_duplicates(subset=['ctx_id'])
        
#         # Converte a coluna is_smell para numérico (se === "y")
#         if 'is_smell' in df_smell.columns:
#             df_smell['is_smell'] = pd.to_numeric(df_smell['is_smell'], errors='coerce').fillna(0)
#         else:
#             return jsonify({"error": "Row 'is_smell' not found in Data_Warehouse"}), 500
        
#         if 'timestamp' in df_smell.columns:
#             df_smell['timestamp'] = pd.to_datetime(df_smell['timestamp'])
#             df_smell['date'] = df_smell['timestamp'].dt.date
#         else:
#             return jsonify({"error": "Row 'timestamp' not found in Data_Warehouse"}), 500

#         #DAILY TIME SERIES
#         df_daily = df_smell.groupby(['project_id', 'date']).agg({
#             'is_smell': 'sum'
#         }).reset_index()

#         df_daily.rename(columns={
#             'project_id': 'id',
#             'date': 'ds',
#             'is_smell': 'y'
#         }, inplace=True)

#         df_daily['ds'] = pd.to_datetime(df_daily['ds'])
#         df_daily['id'] = df_daily['id'].astype(str)
#         df_daily = df_daily.sort_values('ds')

#         today = pd.Timestamp.today().normalize()
#         full_range = pd.date_range(start=df_daily['ds'].min(), end=today, freq='D')
#         df_daily = (
#             df_daily.set_index('ds')
#             .reindex(full_range)
#             .fillna(0)
#             .rename_axis('ds')
#             .reset_index()
#         )
#         df_daily['id'] = str(project_id)

#         if len(df_daily) < 7:
#             return jsonify({
#                 "error": "Not enough data for forecasting. At least 7 days of data are required.",
#                 "rows": len(df_daily)
#             }), 400

#         #FORECAST
#         model_used = None
#         future_df = None
#         import numpy as np

#         historical_values = df_daily['y'].values
#         historical_std = historical_values.std()
#         if historical_std == 0:
#             historical_std = 1
        
#         # BOOTSTRAP (add noise to create variability)
#         try:
#             print("[DEBUG] Trying Bootstrap with noise ...")
#             np.random.seed(42)
#             n_forecast = 30
#             bootstrap_forecast = []
            
#             for i in range(n_forecast):
#                 # Pega um bloco aleatório de 7 dias
#                 block_size = min(7, len(historical_values))
#                 if len(historical_values) > block_size:
#                     start_idx = np.random.randint(0, len(historical_values) - block_size)
#                 else:
#                     start_idx = 0
#                 sampled_value = historical_values[start_idx:start_idx+block_size].mean()
#                 sampled_value += np.random.normal(0, historical_std * 0.3)
#                 bootstrap_forecast.append(max(0, sampled_value))
            
#             future_df = pd.DataFrame({
#                 'ds': pd.date_range(start=df_daily['ds'].max() + pd.Timedelta(days=1), periods=n_forecast, freq='D'),
#                 'id': str(project_id),
#                 'bootstrap': bootstrap_forecast
#             })
            
#             model_used = "Bootstrap with Noise"
#             forecast_col = 'bootstrap'
            
#             future_df['lo-80'] = np.maximum(0, np.array(bootstrap_forecast) - historical_std * 0.8)
#             future_df['hi-80'] = np.array(bootstrap_forecast) + historical_std * 0.8
#             future_df['lo-95'] = np.maximum(0, np.array(bootstrap_forecast) - historical_std * 1.5)
#             future_df['hi-95'] = np.array(bootstrap_forecast) + historical_std * 1.5
            
#             print(f"[DEBUG] Bootstrap OK - STD historical: {historical_std:.2f}")
            
#         except Exception as e:
#             print(f"[DEBUG] Bootstrap failed: {e}")
        
#         # Croston classic (stable to series with many zeros)
#         if future_df is None:
#             try:
#                 print("[DEBUG] Trying CrostonClassic...")
#                 model = StatsForecast(models=[CrostonClassic()], freq='D', n_jobs=-1)
#                 future_df = model.forecast(df=df_daily, h=30, id_col='id', time_col='ds', target_col='y')
#                 model_used = "CrostonClassic"
#                 forecast_col = future_df.columns.difference(['ds', 'id'])[0]
                
#                 future_df['lo-80'] = future_df[forecast_col] * 0.5
#                 future_df['hi-80'] = future_df[forecast_col] * 1.5
#                 future_df['lo-95'] = future_df[forecast_col] * 0.2
#                 future_df['hi-95'] = future_df[forecast_col] * 1.8
#                 future_df.rename(columns={forecast_col: 'croston'}, inplace=True)
                
#                 print("[DEBUG] Model used: CrostonClassic")
                
#             except Exception as e:
#                 print(f"[DEBUG] CrostonClassic failed: {e}")
#                 future_df = None
        
#         # Autoarima (good for general forecasting, fail in short series )
#         if future_df is None:
#             try:
#                 print("[DEBUG] Trying AutoARIMA...")
#                 model = StatsForecast(models=[AutoARIMA(season_length=7)], freq='D', n_jobs=-1)
#                 future_df = model.forecast(df=df_daily, h=30, id_col='id', time_col='ds', target_col='y')
#                 model_used = "AutoARIMA"
#                 forecast_col = future_df.columns.difference(['ds', 'id'])[0]
                
#                 future_df['lo-80'] = future_df[forecast_col] * 0.7
#                 future_df['hi-80'] = future_df[forecast_col] * 1.3
#                 future_df['lo-95'] = future_df[forecast_col] * 0.5
#                 future_df['hi-95'] = future_df[forecast_col] * 1.5
#                 future_df.rename(columns={forecast_col: 'autoarima'}, inplace=True)
                
#                 print("[DEBUG] Modelo utilizado: AutoARIMA")
                
#             except Exception as e:
#                 print(f"[DEBUG] AutoARIMA failed: {e}")
#                 return jsonify({"error": "Failed to generate forecast"}), 500

#         future_df['ds'] = pd.to_datetime(future_df['ds'])
        
#         forecast_value_col = [c for c in future_df.columns if c not in ['ds', 'id', 'lo-80', 'hi-80', 'lo-95', 'hi-95']]
#         if not forecast_value_col:
#             return jsonify({"error": "No forecast column found"}), 500
#         forecast_value_col = forecast_value_col[0]
        
#         print(f"[DEBUG] Final model used: {model_used}")
#         print(f"[DEBUG] Forecast column: {forecast_value_col}")
#         print(f"[DEBUG] First 5 predicted values: {future_df[forecast_value_col].head(5).tolist()}")

#         # Advanced trends analysis
#         y_vals = df_daily['y'].values.astype(float)

#         # Linear trend
#         if len(y_vals) >= 7:
#             slope, _, _, p_value, _ = linregress(range(len(y_vals)), y_vals)
#             if slope > 0.05 and p_value < 0.1:
#                 direction = "upward"
#             elif slope < -0.05 and p_value < 0.1:
#                 direction = "downward"
#             else:
#                 direction = "stable"
#         else:
#             direction = "not enough data"

#         # Week-over-week variation
#         last_week = y_vals[-7:].mean() if len(y_vals) >= 7 else 0
#         prev_week = y_vals[-14:-7].mean() if len(y_vals) >= 14 else 0
#         wow_change = ((last_week - prev_week) / prev_week) if prev_week > 0 else None

#         seasonality_strength = None
#         if len(df_daily) >= 14:
#             try:
#                 import numpy as np
#                 df_ts = df_daily.set_index('ds').asfreq('D')
#                 df_ts['y'] = df_ts['y'].fillna(0)
#                 decomp = seasonal_decompose(df_ts['y'], model='additive', period=7, extrapolate_trend='freq')
#                 seasonal_var = np.var(decomp.seasonal)
#                 residual_var = np.var(decomp.resid)
#                 if (seasonal_var + residual_var) > 0:
#                     seasonality_strength = 1 - (residual_var / (seasonal_var + residual_var))
#             except:
#                 pass

#         df_smell_with_smell = df_smell[df_smell['is_smell'] == 1]
#         smell_type_counts = df_smell_with_smell['smell_type'].value_counts().to_dict() if 'smell_type' in df_smell.columns else {}

#         top_files = df_smell_with_smell.groupby('file_path').size().nlargest(5).to_dict() if 'file_path' in df_smell.columns else {}
#         top_users = df_smell_with_smell.groupby('user_id').size().nlargest(5).to_dict() if 'user_id' in df_smell.columns else {}

#         # Debt Impact
#         total_debt_impact = float(df_smell['smell_debt_impact'].sum()) if 'smell_debt_impact' in df_smell.columns else 0
#         avg_debt_impact = float(df_smell['smell_debt_impact'].mean()) if 'smell_debt_impact' in df_smell.columns else 0

#         total_smells = int(df_smell['is_smell'].sum())
#         avg_per_day = float(df_daily['y'].mean())
#         peak_day = df_daily.loc[df_daily['y'].idxmax()]
#         peak_day_date = str(peak_day['ds'].date())
#         peak_day_value = float(peak_day['y'])

#         most_smell_hour = int(df_smell.groupby('hour_of_day')['is_smell'].sum().idxmax()) if 'hour_of_day' in df_smell.columns else 0
#         weekday_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
#         if 'day_of_week' in df_smell.columns:
#             most_smell_weekday_num = int(df_smell.groupby('day_of_week')['is_smell'].sum().idxmax())
#             most_smell_day = weekday_map.get(most_smell_weekday_num, 'Unknown')
#         else:
#             most_smell_day = 'Unknown'

#         fig, ax = plt.subplots(figsize=(12, 6))
#         ax.plot(df_daily['ds'], df_daily['y'], marker='o', label='Historical', color='blue', linewidth=2, markersize=4)
#         ax.plot(future_df['ds'], future_df[forecast_value_col], marker='o', label=f'Forecasting ({model_used})', color='red', linewidth=2, markersize=4)
#         ax.fill_between(future_df['ds'], future_df['lo-80'], future_df['hi-80'], color='red', alpha=0.2, label='80% Interval')
#         ax.set_title(f'Smell Forecast - Project {project_id}', fontsize=14, fontweight='bold')
#         ax.set_xlabel('Time', fontsize=12)
#         ax.set_ylabel('Number of Smells', fontsize=12)
#         ax.legend(fontsize=10)
#         ax.grid(True, linestyle='--', alpha=0.6)
        
#         plt.xticks(rotation=45, ha='right')
#         plt.tight_layout()

#         logs_dir = os.path.join(os.getcwd(), "logs")
#         os.makedirs(logs_dir, exist_ok=True)
#         png_path = os.path.join(logs_dir, f"forecast_project_{project_id}.png")
#         plt.savefig(png_path, format='png', dpi=100, bbox_inches='tight')
#         plt.close(fig)

#         with open(png_path, "rb") as f:
#             img_base64 = base64.b64encode(f.read()).decode('utf-8')

#         trends = {
#             "total_smells": total_smells,
#             "average_per_day": avg_per_day,
#             "most_smell_hour": most_smell_hour,
#             "most_smell_day": most_smell_day,
#             "peak_day": {
#                 "date": peak_day_date,
#                 "value": peak_day_value
#             },
#             "direction": direction,
#             "seasonality_strength": seasonality_strength,
#             "debt_impact": {      
#                 "total": total_debt_impact,
#                 "average": avg_debt_impact
#             },
#             "smell_type_distribution": smell_type_counts,
#             "top_files": top_files,
#             "top_users": top_users
#         }

#         return jsonify({
#             "project_id": project_id,
#             "model_used": model_used,
#             "forecast": future_df[[
#                 'ds', forecast_value_col, 'lo-80', 'hi-80', 'lo-95', 'hi-95'
#             ]].to_dict(orient='records'),
#             #"plot_base64": img_base64,
#             "trends": {
#                 "total_smells": total_smells,
#                 "average_per_day": avg_per_day,
#                 "most_smell_hour": most_smell_hour,
#                 "most_smell_day": most_smell_day,
#                 "peak_day": {
#                     "date": peak_day_date,
#                     "value": peak_day_value
#                 },
#                 "direction": direction,
#                 "wow_change": wow_change,
#                 "seasonality_strength": seasonality_strength,
#                 "smell_type_distribution": smell_type_counts,
#                 "top_files": top_files,
#                 "top_users": top_users,
#                 "debt_impact": {
#                     "total": total_debt_impact,
#                     "average": avg_debt_impact
#                 }
#             }
#         })

#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         return jsonify({"error": str(e)}), 500

from app.services.forecasting_service import ForecastService
@app.route("/forecast/<project_id>", methods=["GET"])
def forecast2(project_id):

    service = ForecastService(SheetsRepository())

    try:
        result = service.forecast_project(project_id)
        return jsonify(result)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    
feature_service = FeatureEngineeringService(repository)

@app.route("/etl/run", methods=["POST"])
def run_etl():
    try:
        repository = SheetsRepository()

        repository.clear_warehouse()
        processed = feature_service.run()
        return {
            "status": "ok",
            "rows_processed": processed
        }, 200
    except Exception as e:
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