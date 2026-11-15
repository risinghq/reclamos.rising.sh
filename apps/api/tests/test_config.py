from urllib.parse import unquote, urlsplit

import pytest
from reclamos_api.config import Settings


def test_database_url_keeps_a_password_with_url_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "reclamos")
    monkeypatch.setenv("DB_USER", "reclamos")
    monkeypatch.setenv("DB_PASSWORD", "a#b:c/d@e?f%g")

    url = urlsplit(Settings.from_environment().database_url)

    assert url.hostname == "db.internal"
    assert url.port == 5432
    assert url.path == "/reclamos"
    assert unquote(url.username or "") == "reclamos"
    assert unquote(url.password or "") == "a#b:c/d@e?f%g"
