from pathlib import Path

import pytest

from backend.config import DEFAULT_DATA_DIR, Settings, load_settings


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBUI_DATA_DIR", raising=False)
    monkeypatch.delenv("WEBUI_HOST", raising=False)
    monkeypatch.delenv("WEBUI_PORT", raising=False)
    monkeypatch.delenv("WEBUI_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("WEBUI_CORS_ORIGIN_REGEX", raising=False)

    s = load_settings()

    assert s.data_dir == DEFAULT_DATA_DIR.resolve()
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.cors_origins == ()
    assert s.cors_origin_regex is None


def test_load_settings_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEBUI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEBUI_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBUI_PORT", "9001")

    s = load_settings()

    assert s.data_dir == tmp_path.resolve()
    assert s.host == "127.0.0.1"
    assert s.port == 9001


def test_load_settings_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "WEBUI_CORS_ORIGINS",
        "moz-extension://abc-def, http://nas.local:8000 ,",
    )
    monkeypatch.setenv("WEBUI_CORS_ORIGIN_REGEX", r"moz-extension://.*")

    s = load_settings()

    assert s.cors_origins == ("moz-extension://abc-def", "http://nas.local:8000")
    assert s.cors_origin_regex == r"moz-extension://.*"


def test_settings_derived_paths(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path)

    assert s.downloads_dir == tmp_path / "downloads"
    assert s.archive_db_path == tmp_path / "archive.db"
    assert s.jobs_db_path == tmp_path / "jobs.db"
