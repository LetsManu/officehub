import os
import shutil
import tempfile

import pytest

# Settings are read at import time, so configure a throw-away data folder first.
_DATA_DIR = tempfile.mkdtemp(prefix="officehub-test-")
os.environ["DATA_DIR"] = _DATA_DIR
os.environ["DEMO_MODE"] = "true"
os.environ["DEMO_LANGUAGE"] = "en"
os.environ["BCRYPT_ROUNDS"] = "4"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD, ensure_initial_data  # noqa: E402
from app.security import login_throttle  # noqa: E402

HEADERS = {"X-Requested-With": "OfficeHub"}


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_initial_data(db)
    login_throttle._failures.clear()
    yield


def make_client(email: str | None = None) -> TestClient:
    client = TestClient(app, headers=HEADERS)
    if email:
        response = client.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
        assert response.status_code == 200, response.text
    return client


@pytest.fixture
def anna():
    return make_client("anna.mayer@example.com")


@pytest.fixture
def lukas():
    return make_client("lukas.schmid@example.com")


@pytest.fixture
def tom():
    return make_client("tom.huber@example.com")


@pytest.fixture
def julia():
    return make_client("julia.weber@example.com")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_DATA_DIR, ignore_errors=True)
