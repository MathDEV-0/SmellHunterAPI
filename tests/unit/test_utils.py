def test_normalize_env():
    from app.interpreter_api import normalize_env

    input_data = {
        "long_method.size": 10,
        "simple": 5
    }

    result = normalize_env(input_data)

    assert result[("long_method", "size")] == 10
    assert result["simple"] == 5

def test_safe_json_parse_string():
    from app.interpreter_api import safe_json_parse

    data = '{"a": 1}'
    result = safe_json_parse(data)

    assert result == {"a": 1}

def test_safe_json_parse_invalid():
    from app.interpreter_api import safe_json_parse

    data = "invalid json"
    result = safe_json_parse(data, default={})

    assert result == {}

import os
import pytest


@pytest.mark.parametrize("filename", [
    "metrics_god_class.csv",
    "thresholds_god_class.csv"
])
def test_load_metrics_csv_types(filename):
    from app.interpreter_api import load_metrics

    path = os.path.join("test_files", "csv_for_plugin", filename)

    class FileMock:
        def __init__(self, filename):
            self.filename = filename

        def read(self):
            with open(path, "rb") as f:
                return f.read()

    result = load_metrics(FileMock(filename))

    assert isinstance(result, dict)
    assert len(result) > 0

def test_team_size_calculation():
    import pandas as pd
    from app.events.observers import FeatureEngineeringService

    df = build_df([
        {"ctx_id": "1", "timestamp_utc": "2026-01-01T10:00:00", "project_id": "A", "user_id": "u1", "file_path": "f1", "smell_type": "A", "is_smell": "YES"},
        {"ctx_id": "2", "timestamp_utc": "2026-01-01T11:00:00", "project_id": "A", "user_id": "u2", "file_path": "f2", "smell_type": "A", "is_smell": "NO"},
        {"ctx_id": "3", "timestamp_utc": "2026-01-01T12:00:00", "project_id": "A", "user_id": "u3", "file_path": "f3", "smell_type": "A", "is_smell": "NO"},
    ])

    service = FeatureEngineeringService(None)

    result = service.build_features(df.iloc[0], df)

    assert get_feature(result, "team_size") == 3


def test_project_age_days():
    import pandas as pd
    from app.events.observers import FeatureEngineeringService

    df = build_df([
        {"ctx_id": "1", "timestamp_utc": "2026-01-01T10:00:00", "project_id": "A", "user_id": "u1", "file_path": "f1", "smell_type": "A", "is_smell": "YES"},
        {"ctx_id": "2", "timestamp_utc": "2026-01-03T10:00:00", "project_id": "A", "user_id": "u1", "file_path": "f1", "smell_type": "A", "is_smell": "NO"},
    ])

    service = FeatureEngineeringService(None)

    result = service.build_features(df.iloc[1], df)

    assert get_feature(result, "project_age_days") == 2

def test_user_total_commits():
    import pandas as pd
    from app.events.observers import FeatureEngineeringService

    df = build_df([
        {"ctx_id": "1", "timestamp_utc": "2026-01-01T10:00:00", "project_id": "A", "user_id": "u1", "file_path": "f1", "smell_type": "A", "is_smell": "YES"},
        {"ctx_id": "2", "timestamp_utc": "2026-01-01T11:00:00", "project_id": "A", "user_id": "u1", "file_path": "f2", "smell_type": "A", "is_smell": "NO"},
        {"ctx_id": "3", "timestamp_utc": "2026-01-01T12:00:00", "project_id": "A", "user_id": "u2", "file_path": "f3", "smell_type": "A", "is_smell": "NO"},
    ])

    service = FeatureEngineeringService(None)

    result = service.build_features(df.iloc[2], df)

    assert get_feature(result, "user_total_commits") == 1

WAREHOUSE_COLUMNS = [
    "ctx_id","timestamp","project_id","user_id","file_path","smell_type","is_smell",
    "hour_of_day","day_of_week","is_weekend","time_since_last_smell",
    "time_since_last_commit","time_since_last_analysis","user_total_commits",
    "user_smell_rate","user_recent_activity","smell_count_24h","smell_trend",
    "file_change_frequency","file_smell_history","file_last_modified_delta",
    "project_age_days","team_size","commit_velocity","smell_debt_impact"
]

def get_feature(result, name):
    return result[name]

def build_df(data):
    import pandas as pd
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp_utc"])
    df["target"] = df["is_smell"].apply(lambda x: 1 if x == "YES" else 0)
    return df

def test_team_size_single_user():
    from app.events.observers import FeatureEngineeringService
    df = build_df([
        {"ctx_id": "1", "timestamp_utc": "2026-01-01T10:00:00", "project_id": "A", "user_id": "u1", "file_path": "f1", "smell_type": "A", "is_smell": "YES"}
    ])

    service = FeatureEngineeringService(None)
    result = service.build_features(df.iloc[0], df)

    assert get_feature(result, "team_size") == 1