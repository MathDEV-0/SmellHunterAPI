import pandas as pd
import numpy as np
from scipy.stats import linregress
from statsmodels.tsa.seasonal import seasonal_decompose
from statsforecast import StatsForecast
from statsforecast.models import CrostonClassic, AutoARIMA


class ForecastService:

    def __init__(self, repository):
        self.repository = repository

    # -------------------------
    # PUBLIC API
    # -------------------------
    def forecast_project(self, project_id: str):

        df = self.repository.get_warehouse_data(project_id).copy()

        if df.empty:
            raise ValueError("No data")

        df = self._prepare_dataframe(df)
        df_daily = self._build_daily_series(df, project_id)

        if len(df_daily) < 7:
            raise ValueError("Not enough data")

        future_df, model_used = self._forecast(df_daily)
        trends = self._compute_trends(df, df_daily)

        return {
            "model_used": model_used,
            "forecast": future_df.to_dict(orient="records"),
            "trends": trends
        }

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

        df['timestamp'] = pd.to_datetime(df['timestamp'])
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