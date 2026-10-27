import pytest

from pace import config, db


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PACE_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("PACE_DEV_USER", "tester")
    monkeypatch.setenv("PACE_PUBLIC_URL", "http://localhost")
    config.settings.cache_clear()
    db.init()
    yield
    config.settings.cache_clear()
