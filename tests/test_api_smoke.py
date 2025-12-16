from __future__ import annotations

from fastapi.testclient import TestClient

from reos.app import app


def test_health_ok() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_ingest_event_and_reflect() -> None:
    client = TestClient(app)

    res = client.post(
        "/events",
        json={"source": "test", "payload_metadata": {"kind": "smoke"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stored"] is True
    assert "event_id" in body

    res = client.get("/reflections")
    assert res.status_code == 200
    data = res.json()
    assert "reflections" in data
    assert isinstance(data["reflections"], list)
