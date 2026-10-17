"""HW2 authentication tests. Offline: no Langfuse, Docker, or model key."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server import app as server_app


@pytest.fixture
def client(world, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(server_app, "SESSIONS_DB", tmp_path / "sessions.db")
    monkeypatch.setattr(server_app, "_SESSIONS", {})
    return TestClient(server_app.app)  # no `with`: skips the lifespan, so tracing stays off


def test_create_session_rejects_role_mismatch(client: TestClient) -> None:
    # User 1 is a shopper in the database.
    response = client.post("/sessions", json={"user_id": 1, "role": "merchant"})
    assert response.status_code == 403
    assert server_app._SESSIONS == {}


def test_token_cannot_authorize_another_session(client: TestClient) -> None:
    first = client.post("/sessions", json={"user_id": 1, "role": "shopper"}).json()
    second = client.post("/sessions", json={"user_id": 2, "role": "shopper"}).json()
    response = client.post(
        f"/sessions/{second['session_id']}/messages",
        headers={"Authorization": f"Bearer {first['token']}"},
        json={"message": "Show my recent orders."},
    )
    assert response.status_code == 403
