import httpx2
import pytest
from fastapi.testclient import TestClient
from reclamos_api.main import create_app
from reclamos_api.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_client_gets_its_minute_of_searches_then_waits_for_refill() -> None:
    clock = Clock()
    limiter = RateLimiter(per_minute=3, clock=clock)

    assert [limiter.wait("a") for _ in range(3)] == [0, 0, 0]
    assert limiter.wait("a") == pytest.approx(20)
    assert limiter.wait("b") == 0, "another client has its own bucket"

    clock.now = 20
    assert limiter.wait("a") == 0
    assert limiter.wait("a") == pytest.approx(20)


def test_forgetting_the_oldest_client_only_refills_it() -> None:
    limiter = RateLimiter(per_minute=1, clock=Clock(), max_clients=1)

    assert limiter.wait("a") == 0
    assert limiter.wait("b") == 0
    assert limiter.wait("a") == 0
    assert limiter.wait("a") > 0


@pytest.mark.parametrize("route", ["/search", "/cases"])
def test_the_search_routes_answer_429_past_the_limit(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    monkeypatch.setenv("SEARCHES_PER_MINUTE", "2")
    client: httpx2.Client = TestClient(create_app())

    # An empty query fails validation, so the limit is checked without a database.
    statuses = [client.post(route, json={"query": ""}).status_code for _ in range(3)]
    limited = client.post(route, json={"query": ""})

    assert statuses == [422, 422, 429]
    assert limited.headers["retry-after"] == "30"
