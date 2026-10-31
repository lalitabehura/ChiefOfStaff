import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
    "ANTHROPIC_API_KEY": "",
    "REDIS_URL": "",
    "GLOBAL_RATE_LIMIT_PER_MINUTE": "100000",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Correct-Horse-42!"


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    limiter.reset()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update({"X-Requested-With": "XMLHttpRequest"})
        yield c


def register(client, email="alice@example.com", password=PASSWORD, tz="America/New_York"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password,
                                                  "full_name": "Alice Doe", "timezone": tz})
    assert r.status_code == 201, r.text
    return r.json()


def auth_headers(token_out) -> dict:
    return {"Authorization": f"Bearer {token_out['access_token']}"}
