import os
import pandas as pd
import numpy as np
from scipy.stats import linregress
from statsmodels.tsa.seasonal import seasonal_decompose
from statsforecast import StatsForecast
from statsforecast.models import CrostonClassic, AutoARIMA
from app.services.similarity_service import SimilarityService
import matplotlib.pyplot as plt
import io
import base64

from app.configs.settings import BASE_DIR

class ForecastService:

    def __init__(self, repository):
        self.repository = repository
        self.similarity_service = SimilarityService(repository)

    def _get_log_path(self, filename: str):
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        return os.path.join(logs_dir, filename)
    
    def _save_plot(self, fig, filename):
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)

        buffer.seek(0)

        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "wb") as f:
            f.write(buffer.getvalue())

        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    # -------------------------
    # PUBLIC API
    # -------------------------
    def forecast_project(self, project_id: str):

        df = self.repository.get_warehouse_data(project_id).copy()

        if df.empty:
            raise ValueError("No data")

        df = self._prepare_dataframe(df)
        df_daily = self._build_daily_series(df, project_id)

        total_events = df['is_smell'].sum()

        # -------------------------
        # SIMILARITY MODE
        # -------------------------
        if total_events < 10:

            df_daily_sim, similar_projects = self.similarity_service.build_similar_daily_series(project_id)

            weights = np.array([sim for _, sim in similar_projects])
            weights = weights / weights.sum() if weights.sum() > 0 else np.ones(len(weights)) / len(weights)

            similarity_meta = [
                {
                    "project_id": pid,
                    "similarity": float(sim),
                    "weight": float(w)
                }
                for (pid, sim), w in zip(similar_projects, weights)
            ]

            future_df, model_used = self._forecast(df_daily_sim)

            future_df["source"] = "similarity_based"

            # PLOT SIMILARITY SALVO EM DISCO
            img_base64 = self._build_similarity_plot(
                future_df,
                similarity_meta,
                df_daily_sim
            )

            filename = self._get_log_path(f"similarity_forecast_project_{project_id}.png")

            with open(filename, "wb") as f:
                f.write(base64.b64decode(img_base64))

            return {
                "model_used": "Similarity+" + model_used,
                "similar_projects": similarity_meta,
                "forecast": future_df.to_dict(orient="records"),
                "plot_path": filename,
                "trends": {
                    "mode": "similarity_fallback"
                }
            }

        # -------------------------
        # NORMAL MODE
        # -------------------------
        future_df, model_used = self._forecast(df_daily)
        trends = self._compute_trends(df, df_daily)

        forecast_col = "yhat"

        # PLOT FORECAST SALVO EM DISCO
        img_base64 = self._build_forecast_plot(
            df_daily,
            future_df,
            forecast_col,
            model_used,
            project_id
        )

        filename = self._get_log_path(f"forecast_project_{project_id}.png")

        with open(filename, "wb") as f:
            f.write(base64.b64decode(img_base64))

        return {
            "model_used": model_used,
            "forecast": future_df.to_dict(orient="records"),
            "trends": trends,
            "plot_path": filename
        }

        # return {
        #     "model_used": model_used,
        #     "forecast": future_df.to_dict(orient="records"),
        #     "trends": trends
        # }

    # -------------------------
    # DATA PREPARATION
    # -------------------------
    def _prepare_dataframe(self, df):

        if 'ctx_id' in df.columns:
            df = df.drop_duplicates(subset=['ctx_id']).copy()

        if 'is_smell' not in df.columns:
            raise ValueError("Missing column: is_smell")

        df['is_smell'] = pd.to_numeric(df['is_smell'], errors='coerce').fillna(0)

        if 'timestamp' not in df.columns:
            raise ValueError("Missing column: timestamp")

        df['timestamp'] = pd.to_datetime(df['timestamp'],format='mixed',errors='coerce')

        df = df.dropna(subset=['timestamp'])
        df['date'] = df['timestamp'].dt.date

        return df

    # -------------------------
    # TIME SERIES
    # -------------------------
    def _build_daily_series(self, df, project_id):

        df_daily = df.groupby(['project_id', 'date']).agg({
            'is_smell': 'sum'
        }).reset_index()

        df_daily.rename(columns={
            'project_id': 'id',
            'date': 'ds',
            'is_smell': 'y'
        }, inplace=True)

        df_daily['ds'] = pd.to_datetime(df_daily['ds'])
        df_daily = df_daily.sort_values('ds')

        # preencher buracos
        today = pd.Timestamp.today().normalize()
        full_range = pd.date_range(start=df_daily['ds'].min(), end=today, freq='D')

        df_daily = (
            df_daily.set_index('ds')
            .reindex(full_range)
            .fillna(0)
            .rename_axis('ds')
            .reset_index()
        )

        df_daily['id'] = str(project_id)

        return df_daily

    # -------------------------
    # FORECAST
    # -------------------------
    def _forecast(self, df_daily):

        historical_values = df_daily['y'].values
        historical_std = historical_values.std() or 1

        # -------- Bootstrap --------
        try:
            np.random.seed(42)
            n_forecast = 30
            forecast = []

            for _ in range(n_forecast):
                block_size = min(7, len(historical_values))

                start_idx = (
                    np.random.randint(0, len(historical_values) - block_size)
                    if len(historical_values) > block_size
                    else 0
                )

                sampled = historical_values[start_idx:start_idx+block_size].mean()
                sampled += np.random.normal(0, historical_std * 0.3)

                forecast.append(max(0, sampled))

            future_df = pd.DataFrame({
                'ds': pd.date_range(
                    start=df_daily['ds'].max() + pd.Timedelta(days=1),
                    periods=n_forecast,
                    freq='D'
                ),
                'yhat': forecast
            })

            future_df['lo-80'] = np.maximum(0, np.array(forecast) - historical_std * 0.8)
            future_df['hi-80'] = np.array(forecast) + historical_std * 0.8
            future_df['lo-95'] = np.maximum(0, np.array(forecast) - historical_std * 1.5)
            future_df['hi-95'] = np.array(forecast) + historical_std * 1.5

            return future_df, "Bootstrap"

        except Exception:
            pass

        # -------- Croston --------
        try:
            model = StatsForecast(models=[CrostonClassic()], freq='D', n_jobs=-1)

            future_df = model.forecast(
                df=df_daily,
                h=30,
                id_col='id',
                time_col='ds',
                target_col='y'
            )

            col = future_df.columns.difference(['ds', 'id'])[0]

            future_df['lo-80'] = future_df[col] * 0.5
            future_df['hi-80'] = future_df[col] * 1.5
            future_df['lo-95'] = future_df[col] * 0.2
            future_df['hi-95'] = future_df[col] * 1.8

            future_df.rename(columns={col: 'yhat'}, inplace=True)

            return future_df[['ds', 'yhat', 'lo-80', 'hi-80', 'lo-95', 'hi-95']], "Croston"

        except Exception:
            pass

        # -------- AutoARIMA --------
        model = StatsForecast(models=[AutoARIMA(season_length=7)], freq='D', n_jobs=-1)

        future_df = model.forecast(
            df=df_daily,
            h=30,
            id_col='id',
            time_col='ds',
            target_col='y'
        )

        col = future_df.columns.difference(['ds', 'id'])[0]

        future_df['lo-80'] = future_df[col] * 0.7
        future_df['hi-80'] = future_df[col] * 1.3
        future_df['lo-95'] = future_df[col] * 0.5
        future_df['hi-95'] = future_df[col] * 1.5

        future_df.rename(columns={col: 'yhat'}, inplace=True)

        return future_df[['ds', 'yhat', 'lo-80', 'hi-80', 'lo-95', 'hi-95']], "AutoARIMA"

    # -------------------------
    # TRENDS
    # -------------------------
    def _compute_trends(self, df, df_daily):

        y_vals = df_daily['y'].values.astype(float)

        # tendência linear
        if len(y_vals) >= 7:
            slope, _, _, p_value, _ = linregress(range(len(y_vals)), y_vals)

            if slope > 0.05 and p_value < 0.1:
                direction = "upward"
            elif slope < -0.05 and p_value < 0.1:
                direction = "downward"
            else:
                direction = "stable"
        else:
            direction = "not enough data"

        # média
        avg_per_day = float(df_daily['y'].mean())
        total_smells = int(df['is_smell'].sum())

        # pico
        peak = df_daily.loc[df_daily['y'].idxmax()]

        # distribuição
        smell_type_counts = df[df['is_smell'] == 1]['smell_type'].value_counts().to_dict()

        # debt
        total_debt = float(df.get('smell_debt_impact', pd.Series()).sum())
        avg_debt = float(df.get('smell_debt_impact', pd.Series()).mean())

        return {
            "total_smells": total_smells,
            "average_per_day": avg_per_day,
            "peak_day": {
                "date": str(peak['ds'].date()),
                "value": float(peak['y'])
            },
            "direction": direction,
            "smell_type_distribution": smell_type_counts,
            "debt_impact": {
                "total": total_debt,
                "average": avg_debt
            }
        }   

    def _compute_full_trends(self, df, df_daily):

        import numpy as np

        y_vals = df_daily['y'].values.astype(float)

        # -------- trend --------
        if len(y_vals) >= 7:
            slope, _, _, p_value, _ = linregress(range(len(y_vals)), y_vals)

            if slope > 0.05 and p_value < 0.1:
                direction = "upward"
            elif slope < -0.05 and p_value < 0.1:
                direction = "downward"
            else:
                direction = "stable"
        else:
            direction = "not enough data"

        # -------- wow --------
        last_week = y_vals[-7:].mean() if len(y_vals) >= 7 else 0
        prev_week = y_vals[-14:-7].mean() if len(y_vals) >= 14 else 0
        wow_change = ((last_week - prev_week) / prev_week) if prev_week > 0 else None

        # -------- seasonality --------
        seasonality_strength = None
        if len(df_daily) >= 14:
            try:
                df_ts = df_daily.set_index('ds').asfreq('D')
                df_ts['y'] = df_ts['y'].fillna(0)

                decomp = seasonal_decompose(df_ts['y'], model='additive', period=7, extrapolate_trend='freq')

                seasonal_var = np.var(decomp.seasonal)
                residual_var = np.var(decomp.resid)

                if (seasonal_var + residual_var) > 0:
                    seasonality_strength = 1 - (residual_var / (seasonal_var + residual_var))
            except:
                pass

        # -------- stats --------
        total_smells = int(df['is_smell'].sum())
        avg_per_day = float(df_daily['y'].mean())

        peak = df_daily.loc[df_daily['y'].idxmax()]

        smell_type_counts = df[df['is_smell'] == 1]['smell_type'].value_counts().to_dict() \
            if 'smell_type' in df.columns else {}

        top_files = df[df['is_smell'] == 1].groupby('file_path').size().nlargest(5).to_dict() \
            if 'file_path' in df.columns else {}

        top_users = df[df['is_smell'] == 1].groupby('user_id').size().nlargest(5).to_dict() \
            if 'user_id' in df.columns else {}

        total_debt = float(df.get('smell_debt_impact', pd.Series()).sum())
        avg_debt = float(df.get('smell_debt_impact', pd.Series()).mean())

        most_smell_hour = int(df.groupby('hour_of_day')['is_smell'].sum().idxmax()) \
            if 'hour_of_day' in df.columns else 0

        weekday_map = {
            0:'Monday',1:'Tuesday',2:'Wednesday',3:'Thursday',
            4:'Friday',5:'Saturday',6:'Sunday'
        }

        if 'day_of_week' in df.columns:
            most_smell_day = weekday_map.get(
                int(df.groupby('day_of_week')['is_smell'].sum().idxmax()),
                "Unknown"
            )
        else:
            most_smell_day = "Unknown"

        return {
            "total_smells": total_smells,
            "average_per_day": avg_per_day,
            "most_smell_hour": most_smell_hour,
            "most_smell_day": most_smell_day,
            "peak_day": {
                "date": str(peak['ds'].date()),
                "value": float(peak['y'])
            },
            "direction": direction,
            "wow_change": wow_change,
            "seasonality_strength": seasonality_strength,
            "smell_type_distribution": smell_type_counts,
            "top_files": top_files,
            "top_users": top_users,
            "debt_impact": {
                "total": total_debt,
                "average": avg_debt
            }
        }

    def _build_similarity_plot(self, forecast_df, similar_projects=None, df_daily=None):
        df = pd.DataFrame(forecast_df).copy()
        df['ds'] = pd.to_datetime(df['ds'])

        fig, ax = plt.subplots(figsize=(12, 6))

        # histórico
        if df_daily is not None and not df_daily.empty:
            ax.plot(
                df_daily['ds'],
                df_daily['y'],
                marker='o',
                label='Historical',
                color='blue',
                linewidth=2,
                markersize=4
            )

        # forecast
        ax.plot(
            df['ds'],
            df['yhat'],
            marker='o',
            label='Forecast (Similarity)',
            color='orange',
            linewidth=2,
            markersize=4
        )

        # intervalos 50%
        if 'lo-50' in df:
            ax.fill_between(
                df['ds'],
                df['lo-50'],
                df['hi-50'],
                color='orange',
                alpha=0.25,
                label='50% Interval'
            )

        # fallback (caso ainda venha modelo antigo)
        elif 'lo-80' in df:
            ax.fill_between(
                df['ds'],
                df['lo-80'],
                df['hi-80'],
                color='orange',
                alpha=0.25,
                label='Interval'
            )

        # similar projects annotation
        if similar_projects:
            text = "Similar projects:\n"
            for p in similar_projects:
                text += f"{p['project_id']} (sim={p['similarity']:.2f})\n"

            ax.text(0.02, 0.98, text, transform=ax.transAxes, va='top')

        ax.set_title("Similarity Forecast")
        ax.set_xlabel("Time")
        ax.set_ylabel("Number of Smells")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)

        plt.xticks(rotation=45)
        plt.tight_layout()

        filename = self._get_log_path(f"similarity_forecast_project.png")

        return self._save_plot(fig, filename)

    def _build_forecast_plot(self, df_daily, future_df, forecast_col, model_used, project_id):
        fig, ax = plt.subplots(figsize=(12, 6))

        # histórico
        ax.plot(
            df_daily['ds'],
            df_daily['y'],
            marker='o',
            label='Historical',
            color='blue',
            linewidth=2,
            markersize=4
        )

        # forecast
        ax.plot(
            future_df['ds'],
            future_df[forecast_col],
            marker='o',
            label=f'Forecasting ({model_used})',
            color='red',
            linewidth=2,
            markersize=4
        )

        # intervalos
        ax.fill_between(
            future_df['ds'],
            future_df['lo-80'],
            future_df['hi-80'],
            color='red',
            alpha=0.2,
            label='80% Interval'
        )

        ax.fill_between(
            future_df['ds'],
            future_df['lo-95'],
            future_df['hi-95'],
            color='red',
            alpha=0.1,
            label='95% Interval'
        )

        ax.set_title(f'Smell Forecast - Project {project_id}', fontsize=14, fontweight='bold')
        ax.set_xlabel('Time')
        ax.set_ylabel('Number of Smells')
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)

        plt.xticks(rotation=45)
        plt.tight_layout()

        filename = self._get_log_path(f"forecast_project_{project_id}.png")

        return self._save_plot(fig, filename)