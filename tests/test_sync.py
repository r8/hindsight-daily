from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hindsight_daily.cli import cli
from hindsight_daily.parser import Note


def make_note(d: date) -> Note:
    return Note(date=d, frontmatter={}, content="## S\n\nText", content_hash=f"hash_{d}")


def _base_patches(tmp_path, notes, *, needs_sync_val=True, cached=None, verbose=False):
    """Common patches shared by sync and status tests."""
    mock_config = MagicMock()
    mock_config["daily_notes_path"].as_filename.return_value = str(tmp_path)
    mock_config["verbose"].get.return_value = verbose

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    return [
        patch("hindsight_daily.cli.config", mock_config),
        patch("hindsight_daily.cli.get_client", return_value=mock_client),
        patch("hindsight_daily.cli.collect", return_value=[(n.date, Path(tmp_path)) for n in notes]),
        patch("hindsight_daily.cli.parse", side_effect=lambda d, _: next(n for n in notes if n.date == d)),
        patch("hindsight_daily.cli.is_empty", return_value=False),
        patch("hindsight_daily.cli.needs_sync", return_value=needs_sync_val),
        patch("hindsight_daily.cli.mark_synced"),
        patch("hindsight_daily.cli.cached_dates", return_value=set(cached or [])),
        patch("hindsight_daily.cli.evict"),
    ]


def run_sync(tmp_path, notes, *, limit=None, needs_sync_val=True, cached=None):
    """Invoke sync with all external dependencies mocked."""
    submitted: list[date] = []
    deleted: list[str] = []

    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, needs_sync_val=needs_sync_val, cached=cached):
            stack.enter_context(p)
        stack.enter_context(patch("hindsight_daily.cli.submit", side_effect=lambda _, n: submitted.append(n.date)))
        stack.enter_context(patch("hindsight_daily.cli.delete", side_effect=lambda _, d: deleted.append(d)))

        args = ["sync"]
        if limit is not None:
            args += ["--limit", str(limit)]
        result = CliRunner().invoke(cli, args)

    return result, submitted, deleted


def run_status(tmp_path, notes, *, needs_sync_val=True, cached=None, verbose=False, extra_patches=None):
    """Invoke status with all external dependencies mocked."""
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, needs_sync_val=needs_sync_val, cached=cached, verbose=verbose):
            stack.enter_context(p)
        for p in extra_patches or []:
            stack.enter_context(p)
        result = CliRunner().invoke(cli, ["status"])
    return result


# --- sync: no limit ---

def test_no_limit_submits_all(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 5)]
    result, submitted, _ = run_sync(tmp_path, notes)
    assert result.exit_code == 0
    assert len(submitted) == 4


def test_no_limit_skips_unchanged(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    _, submitted, _ = run_sync(tmp_path, notes, needs_sync_val=False)
    assert submitted == []


# --- sync: with limit ---

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


def test_deferred_notes_not_deleted(tmp_path):
    """Notes that hit the limit are still in synced_dates and must not be deleted."""
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    cached = ["2026-01-01", "2026-01-02", "2026-01-03"]
    _, _, deleted = run_sync(tmp_path, notes, limit=1, cached=cached)
    assert deleted == []


def test_removed_notes_still_deleted(tmp_path):
    """Notes absent from vault but present in cache are deleted regardless of limit."""
    notes = [make_note(date(2026, 1, 1))]
    cached = ["2026-01-01", "2026-01-15"]
    _, _, deleted = run_sync(tmp_path, notes, cached=cached)
    assert "2026-01-15" in deleted


# --- status ---

def test_status_counts_up_to_date(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    result = run_status(tmp_path, notes, needs_sync_val=False)
    assert result.exit_code == 0
    assert "up to date     3" in result.output


def test_status_counts_pending(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    result = run_status(tmp_path, notes, needs_sync_val=True)
    assert "needs sync     3" in result.output


def test_status_shows_stale(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result = run_status(tmp_path, notes, needs_sync_val=False, cached=["2026-01-01", "2026-01-15"])
    assert "stale          1" in result.output


def test_status_no_stale_line_when_clean(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result = run_status(tmp_path, notes, needs_sync_val=False, cached=["2026-01-01"])
    assert "stale" not in result.output



def test_status_verbose_lists_pending_dates(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 3)]
    result = run_status(tmp_path, notes, needs_sync_val=True, verbose=True)
    assert "2026-01-01" in result.output
    assert "2026-01-02" in result.output


def test_status_verbose_lists_stale_dates(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result = run_status(tmp_path, notes, needs_sync_val=False, cached=["2026-01-01", "2026-01-15"], verbose=True)
    assert "2026-01-15" in result.output


def test_status_non_verbose_no_individual_dates(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 3)]
    result = run_status(tmp_path, notes, needs_sync_val=True, verbose=False)
    assert "2026-01-01" not in result.output


def test_status_mixed(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 5)]

    def needs_sync_side_effect(note):
        return note.date.day <= 2

    result = run_status(
        tmp_path, notes,
        extra_patches=[patch("hindsight_daily.cli.needs_sync", side_effect=needs_sync_side_effect)],
    )
    assert "needs sync     2" in result.output
    assert "up to date     2" in result.output
