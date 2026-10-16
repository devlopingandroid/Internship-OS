"""Never let tests mutate the user's local database or profile."""
import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    from app import database, main
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    monkeypatch.setattr(main, 'PROFILE', tmp_path / 'profile.json')
    database.init_db()
