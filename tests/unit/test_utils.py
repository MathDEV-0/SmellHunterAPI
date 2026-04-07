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