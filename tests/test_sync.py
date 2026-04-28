from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hindsight_daily.cli import cli
from hindsight_daily.parser import Note


def make_note(d: date) -> Note:
    return Note(date=d, frontmatter={}, content="## S\n\nText", content_hash=f"hash_{d}")


def run_sync(tmp_path, notes, *, limit=None, needs_sync_val=True, cached=None):
    """Invoke sync with all external dependencies mocked. Returns (result, submitted_dates)."""
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config["daily_notes_path"].as_filename.return_value = str(tmp_path)

    submitted: list[date] = []
    deleted: list[str] = []

    with (
        patch("hindsight_daily.cli.config", mock_config),
        patch("hindsight_daily.cli.get_client", return_value=mock_client),
        patch("hindsight_daily.cli.collect", return_value=[(n.date, Path(tmp_path)) for n in notes]),
        patch("hindsight_daily.cli.parse", side_effect=lambda d, _: next(n for n in notes if n.date == d)),
        patch("hindsight_daily.cli.is_empty", return_value=False),
        patch("hindsight_daily.cli.needs_sync", return_value=needs_sync_val),
        patch("hindsight_daily.cli.submit", side_effect=lambda _, n: submitted.append(n.date)),
        patch("hindsight_daily.cli.mark_synced"),
        patch("hindsight_daily.cli.cached_dates", return_value=set(cached or [])),
        patch("hindsight_daily.cli.delete", side_effect=lambda _, d: deleted.append(d)),
        patch("hindsight_daily.cli.evict"),
    ):
        args = ["sync"]
        if limit is not None:
            args += ["--limit", str(limit)]
        result = CliRunner().invoke(cli, args)

    return result, submitted, deleted


# --- no limit ---

def test_no_limit_submits_all(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 5)]
    result, submitted, _ = run_sync(tmp_path, notes)
    assert result.exit_code == 0
    assert len(submitted) == 4


def test_no_limit_skips_unchanged(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    _, submitted, _ = run_sync(tmp_path, notes, needs_sync_val=False)
    assert submitted == []


# --- with limit ---

def test_limit_caps_submissions(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 6)]
    _, submitted, _ = run_sync(tmp_path, notes, limit=2)
    assert len(submitted) == 2


def test_limit_zero_submits_nothing(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    _, submitted, _ = run_sync(tmp_path, notes, limit=0)
    assert submitted == []


def test_limit_larger_than_queue_submits_all(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    _, submitted, _ = run_sync(tmp_path, notes, limit=100)
    assert len(submitted) == 3


def test_limit_submits_oldest_first(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 6)]
    _, submitted, _ = run_sync(tmp_path, notes, limit=2)
    assert submitted == [date(2026, 1, 1), date(2026, 1, 2)]


# --- deferred notes not deleted ---

def test_deferred_notes_not_deleted(tmp_path):
    """Notes that hit the limit are still in synced_dates and must not be deleted."""
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    cached = ["2026-01-01", "2026-01-02", "2026-01-03"]
    _, _, deleted = run_sync(tmp_path, notes, limit=1, cached=cached)
    assert deleted == []


def test_removed_notes_still_deleted(tmp_path):
    """Notes absent from vault but present in cache are deleted regardless of limit."""
    notes = [make_note(date(2026, 1, 1))]
    cached = ["2026-01-01", "2026-01-15"]  # 2026-01-15 is gone from vault
    _, _, deleted = run_sync(tmp_path, notes, cached=cached)
    assert "2026-01-15" in deleted
