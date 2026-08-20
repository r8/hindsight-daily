from pathlib import Path
from unittest.mock import MagicMock, patch

import confuse
import pytest

from hindsight_daily import config as config_module
from hindsight_daily.config import Settings, SettingsError, load_settings


def fake_configuration(tmp_path, **overrides):
    """A real confuse config seeded with a complete, valid configuration."""
    values = {
        "verbose": False,
        "bank_id": "bank",
        "api_key": "key",
        "api_url": "https://hindsight.example",
        "daily_notes_path": str(tmp_path),
        "retain_timeout": 1800,
        "retain_poll_interval": 3,
    }
    values.update(overrides)
    config = confuse.Configuration("hindsight-daily-test", read=False)
    config.set(values)
    return config


def load(tmp_path, **overrides):
    config = fake_configuration(tmp_path, **overrides)
    with patch("hindsight_daily.config._configuration", return_value=config):
        return load_settings()


def test_valid_configuration_returns_settings(tmp_path):
    settings = load(tmp_path)
    assert isinstance(settings, Settings)
    assert settings.bank_id == "bank"
    assert settings.api_url == "https://hindsight.example"
    assert settings.notes_path == tmp_path


def test_missing_bank_id_is_reported(tmp_path):
    with pytest.raises(SettingsError, match="bank_id is not set"):
        load(tmp_path, bank_id=None)


def test_missing_api_url_is_reported(tmp_path):
    with pytest.raises(SettingsError, match="api_url is not set"):
        load(tmp_path, api_url=None)


def test_missing_notes_path_is_reported(tmp_path):
    with pytest.raises(SettingsError, match="daily_notes_path is not set"):
        load(tmp_path, daily_notes_path=None)


def test_notes_path_that_is_not_a_directory_is_reported(tmp_path):
    note = tmp_path / "a-file.md"
    note.write_text("x")
    with pytest.raises(SettingsError, match="not a directory"):
        load(tmp_path, daily_notes_path=str(note))


def test_missing_notes_directory_is_reported(tmp_path):
    with pytest.raises(SettingsError, match="not a directory"):
        load(tmp_path, daily_notes_path=str(tmp_path / "gone"))


def test_api_key_is_optional(tmp_path):
    assert load(tmp_path, api_key=None).api_key is None


def test_verbose_override_wins_over_the_file(tmp_path):
    config = fake_configuration(tmp_path, verbose=False)
    with patch("hindsight_daily.config._configuration", return_value=config):
        assert load_settings(verbose_override=True).verbose is True
        assert load_settings().verbose is False


def test_numeric_settings_are_floats(tmp_path):
    settings = load(tmp_path)
    assert settings.retain_timeout == 1800.0
    assert settings.retain_poll_interval == 3.0


def test_malformed_value_becomes_a_settings_error(tmp_path):
    broken = MagicMock()
    broken.__getitem__.side_effect = confuse.ConfigTypeError("bad value")
    with patch("hindsight_daily.config._configuration", return_value=broken), \
            patch("hindsight_daily.config.config_path", return_value=Path("/cfg/config.yaml")):
        with pytest.raises(SettingsError, match="bad value"):
            load_settings()


def test_unreadable_yaml_file_becomes_a_settings_error(tmp_path, monkeypatch):
    """The message names the config file, so resolving that path must not re-read it."""
    (tmp_path / "config.yaml").write_text("bank_id: [unclosed\n")
    monkeypatch.setenv("HINDSIGHT-DAILYDIR", str(tmp_path))
    config_module._configuration.cache_clear()

    with pytest.raises(SettingsError) as exc_info:
        load_settings()

    assert "could not be read" in str(exc_info.value)
    assert str(tmp_path / "config.yaml") in str(exc_info.value)


def test_config_path_works_when_the_file_is_unreadable(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("bank_id: [unclosed\n")
    monkeypatch.setenv("HINDSIGHT-DAILYDIR", str(tmp_path))
    config_module._configuration.cache_clear()

    assert config_module.config_path() == tmp_path / "config.yaml"


def test_settings_are_frozen(tmp_path):
    settings = load(tmp_path)
    with pytest.raises(AttributeError):
        settings.bank_id = "other"  # type: ignore[misc]
