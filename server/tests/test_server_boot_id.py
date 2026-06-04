"""serverBootId is stable within a process and exposed on health/config."""

from fastapi.testclient import TestClient

from app.config import SERVER_BOOT_ID
from app.main import app


def test_health_exposes_server_boot_id() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["serverBootId"] == SERVER_BOOT_ID
    assert len(data["serverBootId"]) > 0


def test_config_exposes_server_boot_id() -> None:
    client = TestClient(app)
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["serverBootId"] == SERVER_BOOT_ID


def test_server_boot_id_stable_across_requests() -> None:
    client = TestClient(app)
    a = client.get("/health").json()["serverBootId"]
    b = client.get("/api/config").json()["serverBootId"]
    assert a == b
