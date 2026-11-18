import httpx2
import pytest
from fastapi.testclient import TestClient
from reclamos_api.main import app


@pytest.mark.integration
def test_health_reports_database_and_queue(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("COMMIT_SHA", raising=False)
    with TestClient(app) as test_client:
        client: httpx2.Client = test_client
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "commit": None,
        "database": {"ok": True},
        "queue": {"ok": True, "schema": "task_queue"},
    }


@pytest.mark.integration
def test_health_reports_the_commit_the_image_was_built_for(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("COMMIT_SHA", "0a1b2c3")
    with TestClient(app) as test_client:
        client: httpx2.Client = test_client
        response = client.get("/health")

    assert response.json()["commit"] == "0a1b2c3"
