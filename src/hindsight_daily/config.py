import functools
from dataclasses import dataclass
from pathlib import Path

import confuse


class SettingsError(Exception):
    """Raised when the configuration is missing, malformed, or points somewhere unusable."""


@dataclass(frozen=True, slots=True)
class Settings:
    bank_id: str
    api_key: str | None
    api_url: str
    notes_path: Path
    verbose: bool
    retain_timeout: float
    retain_poll_interval: float


@functools.cache
def _configuration() -> confuse.Configuration:
    """The confuse view, built on first use so a broken config cannot break `--help`."""
    return confuse.Configuration("hindsight-daily", __name__)


def config_path() -> Path:
    """Where the user config lives, resolved without reading it.

    Error messages name this path, so it has to work precisely when the file is unreadable.
    """
    directory = confuse.Configuration("hindsight-daily", __name__, read=False).config_dir()
    return Path(directory) / confuse.CONFIG_FILENAME


def _required(config: confuse.Configuration, key: str) -> str:
    value = config[key].get()
    if not value:
        raise SettingsError(f"{key} is not set — edit {config_path()}")
    return str(value)


def load_settings(*, verbose_override: bool | None = None) -> Settings:
    """Read and validate the configuration, reporting problems in terms the user can act on."""
    try:
        config = _configuration()
        bank_id = _required(config, "bank_id")
        api_url = _required(config, "api_url")
        _required(config, "daily_notes_path")
        # as_filename() expands `~` and resolves relative paths against the config directory.
        notes_path = Path(config["daily_notes_path"].as_filename())
        api_key = config["api_key"].get() or None
        verbose = config["verbose"].get(bool) if verbose_override is None else verbose_override
        retain_timeout = config["retain_timeout"].get(float)
        retain_poll_interval = config["retain_poll_interval"].get(float)
    except confuse.ConfigError as exc:
        message = str(exc)
        path = str(config_path())
        # confuse already names the file in read errors; don't say it twice.
        raise SettingsError(message if path in message else f"{message} — check {path}") from exc

    if not notes_path.is_dir():
        raise SettingsError(f"daily_notes_path is not a directory: {notes_path}")

    return Settings(
        bank_id=bank_id,
        api_key=str(api_key) if api_key else None,
        api_url=api_url,
        notes_path=notes_path,
        verbose=verbose,
        retain_timeout=retain_timeout,
        retain_poll_interval=retain_poll_interval,
    )
