import pytest
import io
import app.interpreter_api as api


# -------------------------
# Fixture do client Flask
# -------------------------
@pytest.fixture
def client():
    api.app.config["TESTING"] = True
    return api.app.test_client()
