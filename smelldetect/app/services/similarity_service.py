import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


class SimilarityService:

    def __init__(self, repository):
        self.repository = repository

    # -------------------------
    # PUBLIC API
    # -------------------------
    def build_similar_daily_series(self, project_id: str, top_k=3):

        project_id = str(project_id)

        df_all = self.repository.get_warehouse_data()

        if df_all.empty:
            raise ValueError("No data in warehouse")

        # -------------------------
        # CLEANING
        # -------------------------
        df_all = df_all.replace("", np.nan)
        df_all = df_all.astype(object)
        df_all = df_all.convert_dtypes()
        
        if 'ctx_id' in df_all.columns:
            df_all = df_all.drop_duplicates(subset=['ctx_id'])

        # -------------------------
        # TARGET (EVENT VARIABLE)
        # -------------------------
        if 'is_smell' in df_all.columns:
            df_all['is_smell'] = pd.to_numeric(df_all['is_smell'], errors='coerce').fillna(0)

        # -------------------------
        # NUMERIC FEATURES
        # -------------------------
        numeric_cols = [
            "team_size", "commit_velocity", "smell_count_24h",
            "file_change_frequency", "smell_debt_impact",
            "project_age_days", "user_recent_activity"
        ]

        for col in numeric_cols:
            if col in df_all.columns:
                df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        # -------------------------
        # TIMESTAMP
        # -------------------------
        if 'timestamp' in df_all.columns:
            df_all['timestamp'] = pd.to_datetime(df_all['timestamp'], errors='coerce')

        df_all = df_all.dropna(subset=['timestamp'])

        df_all['date'] = df_all['timestamp'].dt.date
        df_all['project_id'] = df_all['project_id'].astype(str)

        # -------------------------
        # FEATURES
        # -------------------------
        features_map = self._build_all_features(df_all)

        if project_id not in features_map:
            raise ValueError(f"Target project {project_id} not found")

        similar_projects = self._find_similar_projects(
            project_id,
            features_map,
            top_k=top_k
        )

        if not similar_projects:
            raise ValueError("No similar projects found")

        similar_ids = [pid for pid, _ in similar_projects]

        # -------------------------
        # DAILY SERIES
        # -------------------------
        df_similar = df_all[df_all['project_id'].isin(similar_ids)]

        if df_similar.empty:
            raise ValueError("Similar projects have no data")

        df_daily = (
            df_similar.groupby('date')
            .agg({'is_smell': 'sum'})
            .reset_index()
        )

        df_daily.rename(columns={'date': 'ds', 'is_smell': 'y'}, inplace=True)

        df_daily['y'] = pd.to_numeric(df_daily['y'], errors='coerce').fillna(0)

        df_daily['ds'] = pd.to_datetime(df_daily['ds'])
        df_daily = df_daily.sort_values('ds')

        # -------------------------
        # FULL DATE RANGE
        # -------------------------
        full_range = pd.date_range(
            start=df_daily['ds'].min(),
            end=pd.Timestamp.today().normalize(),
            freq='D'
        )

        df_daily = (
            df_daily.set_index('ds')
            .reindex(full_range)
            .ffill()
            .fillna(0)
            .rename_axis('ds')
            .reset_index()
        )

        df_daily['id'] = "similar_group"

        return df_daily, similar_projects

    # -------------------------
    # FEATURES
    # -------------------------
    def _build_all_features(self, df_all):

        features_map = {}

        for pid, group in df_all.groupby('project_id'):
            features_map[str(pid)] = self._build_project_features(group)

        return features_map

    def _safe_mean(self, series):
        if series is None:
            return 0.0

        series = pd.to_numeric(series, errors='coerce')
        return float(series.fillna(0).mean())

    def _build_project_features(self, df):

        return {
            "team_size": self._safe_mean(df["team_size"]) if "team_size" in df.columns else 0.0,
            "commit_velocity": self._safe_mean(df["commit_velocity"]) if "commit_velocity" in df.columns else 0.0,
            "smell_density": self._safe_mean(df["is_smell"]) if "is_smell" in df.columns else 0.0,
            "recent_smells": self._safe_mean(df["smell_count_24h"]) if "smell_count_24h" in df.columns else 0.0,
            "file_change_freq": self._safe_mean(df["file_change_frequency"]) if "file_change_frequency" in df.columns else 0.0,
            "avg_debt": self._safe_mean(df["smell_debt_impact"]) if "smell_debt_impact" in df.columns else 0.0,
            "project_age": self._safe_mean(df["project_age_days"]) if "project_age_days" in df.columns else 0.0,
            "dev_activity": self._safe_mean(df["user_recent_activity"]) if "user_recent_activity" in df.columns else 0.0
        }

    def _to_vector(self, features: dict):
        return np.array(list(features.values()), dtype=float)

    # -------------------------
    # SIMILARITY
    # -------------------------
    def _find_similar_projects(self, target_id, features_map, top_k):

        target_vec = self._to_vector(features_map[target_id]).reshape(1, -1)

        similarities = []

        for pid, features in features_map.items():

            if pid == target_id:
                continue

            vec = self._to_vector(features).reshape(1, -1)

            if np.isnan(vec).any() or np.isnan(target_vec).any():
                continue

            sim = cosine_similarity(target_vec, vec)[0][0]

            similarities.append((pid, float(sim)))

        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:top_k]