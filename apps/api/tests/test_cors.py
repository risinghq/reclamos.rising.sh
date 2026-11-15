import httpx2
import pytest
from fastapi.testclient import TestClient
from reclamos_api.main import create_app

WEB = "https://reclamos.example"


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [(WEB, True), ("https://elsewhere.example", False)],
    ids=["configured origin", "other origin"],
)
def test_only_the_web_origins_may_call_the_api(
    monkeypatch: pytest.MonkeyPatch, origin: str, allowed: bool
) -> None:
    monkeypatch.setenv("WEB_ORIGINS", f" {WEB} ,")
    client: httpx2.Client = TestClient(create_app())

    response = client.options(
        "/cases",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert (response.headers.get("access-control-allow-origin") == origin) is allowed
