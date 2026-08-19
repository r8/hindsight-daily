from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hindsight_daily.cli import cli
from hindsight_daily.hindsight import HindsightSubmitError
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


def run_sync(tmp_path, notes, *, limit=None, date_arg=None, needs_sync_val=True, cached=None, failing_dates=()):
    """Invoke sync with all external dependencies mocked."""
    submitted: list[date] = []
    deleted: list[str] = []

    def fake_submit(_, note):
        if note.date in failing_dates:
            raise HindsightSubmitError(f"{note.date}: still being ingested")
        submitted.append(note.date)

    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, needs_sync_val=needs_sync_val, cached=cached):
            stack.enter_context(p)
        stack.enter_context(patch("hindsight_daily.cli.submit", side_effect=fake_submit))
        stack.enter_context(patch("hindsight_daily.cli.delete", side_effect=lambda _, d: deleted.append(d)))

        args = ["sync"]
        if limit is not None:
            args += ["--limit", str(limit)]
        if date_arg is not None:
            args += ["--date", date_arg]
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


# --- sync: submit failures ---

def test_failed_note_does_not_stop_the_run(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    result, submitted, _ = run_sync(tmp_path, notes, failing_dates=[date(2026, 1, 2)])
    assert result.exit_code != 0
    assert submitted == [date(2026, 1, 1), date(2026, 1, 3)]
    assert "1 note(s) failed to sync" in result.output
    assert "still being ingested" in result.output


def test_failed_note_not_marked_synced(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    marked: list[date] = []
    with patch("hindsight_daily.cli.mark_synced", side_effect=marked.append):
        run_sync(tmp_path, notes, failing_dates=[date(2026, 1, 1)])
    assert marked == []


def test_failed_note_is_not_deleted_from_server(tmp_path):
    """A note that failed to submit is still in the vault, so it must not be treated as stale."""
    notes = [make_note(date(2026, 1, 1))]
    _, _, deleted = run_sync(tmp_path, notes, cached=["2026-01-01"], failing_dates=[date(2026, 1, 1)])
    assert deleted == []


def test_sync_date_failure_reports_cleanly(tmp_path):
    notes = [make_note(date(2026, 1, 2))]
    result, submitted, _ = run_sync(
        tmp_path, notes, date_arg="2026-01-02", failing_dates=[date(2026, 1, 2)],
    )
    assert result.exit_code != 0
    assert submitted == []
    assert "still being ingested" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


# --- sync: --date ---

def test_sync_date_submits_only_target(tmp_path):
    notes = [make_note(date(2026, 1, d)) for d in range(1, 4)]
    result, submitted, _ = run_sync(tmp_path, notes, date_arg="2026-01-02")
    assert result.exit_code == 0
    assert submitted == [date(2026, 1, 2)]


def test_sync_date_unchanged_skips(tmp_path):
    notes = [make_note(date(2026, 1, 2))]
    result, submitted, _ = run_sync(tmp_path, notes, date_arg="2026-01-02", needs_sync_val=False)
    assert result.exit_code == 0
    assert submitted == []


def test_sync_date_invalid_format(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result, submitted, deleted = run_sync(tmp_path, notes, date_arg="not-a-date")
    assert result.exit_code != 0
    assert submitted == []
    assert deleted == []


def test_sync_date_not_in_vault(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result, submitted, _ = run_sync(tmp_path, notes, date_arg="2026-01-15")
    assert result.exit_code != 0
    assert submitted == []


def test_sync_date_skips_deletion_phase(tmp_path):
    notes = [make_note(date(2026, 1, 2))]
    cached = ["2026-01-02", "2026-01-99-stale"]
    _, _, deleted = run_sync(tmp_path, notes, date_arg="2026-01-02", cached=cached)
    assert deleted == []


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


def run_forget(tmp_path, date_arg, *, vault_dates=()):
    """Invoke forget with all external dependencies mocked."""
    deleted: list[str] = []
    evicted: list[str] = []

    mock_config = MagicMock()
    mock_config["daily_notes_path"].as_filename.return_value = str(tmp_path)
    mock_config["verbose"].get.return_value = False

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with ExitStack() as stack:
        stack.enter_context(patch("hindsight_daily.cli.config", mock_config))
        stack.enter_context(patch("hindsight_daily.cli.get_client", return_value=mock_client))
        stack.enter_context(patch(
            "hindsight_daily.cli.collect",
            return_value=[(d, Path(tmp_path)) for d in vault_dates],
        ))
        stack.enter_context(patch("hindsight_daily.cli.delete", side_effect=lambda _, d: deleted.append(d)))
        stack.enter_context(patch("hindsight_daily.cli.evict", side_effect=lambda d: evicted.append(d)))
        result = CliRunner().invoke(cli, ["forget", date_arg])

    return result, deleted, evicted


# --- forget ---

def test_forget_happy_path(tmp_path):
    result, deleted, evicted = run_forget(tmp_path, "2026-01-15")
    assert result.exit_code == 0
    assert deleted == ["2026-01-15"]
    assert evicted == ["2026-01-15"]


def test_forget_invalid_date(tmp_path):
    result, deleted, evicted = run_forget(tmp_path, "not-a-date")
    assert result.exit_code != 0
    assert deleted == []
    assert evicted == []


def test_forget_warns_when_note_in_vault(tmp_path):
    target = date(2026, 1, 15)
    result, deleted, evicted = run_forget(tmp_path, "2026-01-15", vault_dates=[target])
    assert result.exit_code == 0
    assert deleted == ["2026-01-15"]
    assert evicted == ["2026-01-15"]
    assert "still exists in vault" in result.output


def test_forget_no_warning_when_note_not_in_vault(tmp_path):
    other = date(2026, 1, 1)
    result, _, _ = run_forget(tmp_path, "2026-01-15", vault_dates=[other])
    assert result.exit_code == 0
    assert "still exists in vault" not in result.output


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
