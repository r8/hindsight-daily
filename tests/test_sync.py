from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hindsight_daily.cli import cli
from hindsight_daily.collector import DuplicateNoteError
from hindsight_daily.config import Settings, SettingsError
from hindsight_daily.hindsight import HindsightDeleteError, HindsightSubmitError
from hindsight_daily.parser import Note


def make_note(d: date) -> Note:
    return Note(date=d, frontmatter={}, content="## S\n\nText", content_hash=f"hash_{d}")


def make_settings(tmp_path, *, verbose=False) -> Settings:
    return Settings(
        bank_id="bank",
        api_key="key",
        api_url="https://hindsight.example",
        notes_path=Path(tmp_path),
        verbose=verbose,
        retain_timeout=60.0,
        retain_poll_interval=0.0,
    )


def _base_patches(tmp_path, notes, *, needs_sync_val=True, cached=None, verbose=False,
                  empty_dates=(), is_cached_val=False, evicted=None):
    """Common patches shared by sync and status tests."""
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    # A real cache forgets an evicted date, so the fake one must too — otherwise the stale
    # phase re-deletes whatever _sync_one already removed.
    cached_set = {date.fromisoformat(d) for d in cached or []}

    def fake_evict(d):
        cached_set.discard(d)
        if evicted is not None:
            evicted.append(d)

    return [
        patch("hindsight_daily.cli.load_settings", return_value=make_settings(tmp_path, verbose=verbose)),
        patch("hindsight_daily.cli.get_client", return_value=mock_client),
        patch("hindsight_daily.cli.collect", return_value=[(n.date, Path(tmp_path)) for n in notes]),
        patch("hindsight_daily.cli.parse", side_effect=lambda d, _: next(n for n in notes if n.date == d)),
        patch("hindsight_daily.cli.is_empty", side_effect=lambda n: n.date in empty_dates),
        patch("hindsight_daily.cli.is_cached", return_value=is_cached_val),
        patch("hindsight_daily.cli.needs_sync", return_value=needs_sync_val),
        patch("hindsight_daily.cli.mark_synced"),
        patch("hindsight_daily.cli.cached_dates", side_effect=lambda: set(cached_set)),
        patch("hindsight_daily.cli.evict", side_effect=fake_evict),
    ]


def run_sync(tmp_path, notes, *, limit=None, date_arg=None, needs_sync_val=True, cached=None,
             failing_dates=(), prune=False, empty_dates=(), is_cached_val=False,
             reconcile_remote=False, remote_dates=None):
    """Invoke sync with all external dependencies mocked."""
    submitted: list[date] = []
    deleted: list[date] = []

    def fake_submit(_client, _settings, note):
        if note.date in failing_dates:
            raise HindsightSubmitError(f"{note.date}: still being ingested")
        submitted.append(note.date)

    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, needs_sync_val=needs_sync_val, cached=cached,
                               empty_dates=empty_dates, is_cached_val=is_cached_val):
            stack.enter_context(p)
        stack.enter_context(patch("hindsight_daily.cli.submit", side_effect=fake_submit))
        stack.enter_context(patch(
            "hindsight_daily.cli.list_journal_dates",
            return_value={date.fromisoformat(d) for d in remote_dates or []},
        ))
        stack.enter_context(patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d)))

        args = ["sync"]
        if limit is not None:
            args += ["--limit", str(limit)]
        if date_arg is not None:
            args += ["--date", date_arg]
        if prune:
            args.append("--prune")
        if reconcile_remote:
            args.append("--reconcile-remote")
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
    assert date(2026, 1, 15) in deleted


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
    cached = ["2026-01-02", "2025-12-31"]
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


def test_status_always_shows_the_stale_row(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result = run_status(tmp_path, notes, needs_sync_val=False, cached=["2026-01-01"])
    assert "stale          0" in result.output



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

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with ExitStack() as stack:
        stack.enter_context(
            patch("hindsight_daily.cli.load_settings", return_value=make_settings(tmp_path))
        )
        stack.enter_context(patch("hindsight_daily.cli.get_client", return_value=mock_client))
        stack.enter_context(patch(
            "hindsight_daily.cli.collect",
            return_value=[(d, Path(tmp_path)) for d in vault_dates],
        ))
        stack.enter_context(patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d)))
        stack.enter_context(patch("hindsight_daily.cli.evict", side_effect=lambda d: evicted.append(d)))
        result = CliRunner().invoke(cli, ["forget", date_arg])

    return result, deleted, evicted


# --- forget ---

def test_forget_happy_path(tmp_path):
    result, deleted, evicted = run_forget(tmp_path, "2026-01-15")
    assert result.exit_code == 0
    assert deleted == [date(2026, 1, 15)]
    assert evicted == [date(2026, 1, 15)]


def test_forget_invalid_date(tmp_path):
    result, deleted, evicted = run_forget(tmp_path, "not-a-date")
    assert result.exit_code != 0
    assert deleted == []
    assert evicted == []


def test_forget_warns_when_note_in_vault(tmp_path):
    target = date(2026, 1, 15)
    result, deleted, evicted = run_forget(tmp_path, "2026-01-15", vault_dates=[target])
    assert result.exit_code == 0
    assert deleted == [date(2026, 1, 15)]
    assert evicted == [date(2026, 1, 15)]
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


# --- configuration errors ---

def test_help_works_without_a_usable_config():
    with patch("hindsight_daily.cli.load_settings", side_effect=SettingsError("bank_id is not set")):
        assert CliRunner().invoke(cli, ["--help"]).exit_code == 0
        assert CliRunner().invoke(cli, ["sync", "--help"]).exit_code == 0


def test_config_error_is_reported_without_a_traceback():
    with patch("hindsight_daily.cli.load_settings", side_effect=SettingsError("bank_id is not set")):
        result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code != 0
    assert "bank_id is not set" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


# --- empty-vault guard ---

def test_empty_vault_does_not_delete_cached_notes(tmp_path):
    result, submitted, deleted = run_sync(tmp_path, [], cached=["2026-01-01", "2026-01-02"])
    assert result.exit_code != 0
    assert deleted == []
    assert "refusing to delete" in result.output


def test_empty_vault_deletes_with_explicit_prune(tmp_path):
    result, submitted, deleted = run_sync(
        tmp_path, [], cached=["2026-01-01", "2026-01-02"], prune=True
    )
    assert result.exit_code == 0
    assert deleted == [date(2026, 1, 1), date(2026, 1, 2)]


def test_empty_vault_and_empty_cache_is_not_an_error(tmp_path):
    result, submitted, deleted = run_sync(tmp_path, [], cached=[])
    assert result.exit_code == 0
    assert deleted == []


def test_stale_notes_still_deleted_when_the_vault_has_notes(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result, submitted, deleted = run_sync(tmp_path, notes, cached=["2026-01-01", "2025-12-31"])
    assert result.exit_code == 0
    assert deleted == [date(2025, 12, 31)]


def test_duplicate_dates_abort_sync_without_deleting(tmp_path):
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, [], cached=["2026-01-15"]):
            stack.enter_context(p)
        stack.enter_context(patch(
            "hindsight_daily.cli.collect",
            side_effect=DuplicateNoteError(date(2026, 1, 15), Path("/a.md"), Path("/b.md")),
        ))
        deleted: list[str] = []
        stack.enter_context(
            patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d))
        )
        result = CliRunner().invoke(cli, ["sync"])

    assert result.exit_code != 0
    assert "two notes share the date" in result.output
    assert deleted == []


# --- notes that became empty ---

def test_emptied_note_is_deleted_by_full_sync(tmp_path):
    target = date(2026, 1, 15)
    notes = [make_note(target)]
    evicted: list[date] = []
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, empty_dates={target}, is_cached_val=True,
                               cached=["2026-01-15"], evicted=evicted):
            stack.enter_context(p)
        deleted: list[date] = []
        stack.enter_context(patch("hindsight_daily.cli.submit"))
        stack.enter_context(
            patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d))
        )
        result = CliRunner().invoke(cli, ["sync"])

    assert result.exit_code == 0
    assert deleted == [target]
    assert evicted == [target]
    assert "now empty" in result.output


def test_emptied_note_is_deleted_by_targeted_sync(tmp_path):
    target = date(2026, 1, 15)
    notes = [make_note(target)]
    evicted: list[date] = []
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, empty_dates={target}, is_cached_val=True,
                               evicted=evicted):
            stack.enter_context(p)
        deleted: list[date] = []
        stack.enter_context(patch("hindsight_daily.cli.submit"))
        stack.enter_context(
            patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d))
        )
        result = CliRunner().invoke(cli, ["sync", "--date", "2026-01-15"])

    assert result.exit_code == 0
    assert deleted == [target]
    assert evicted == [target]
    assert "now empty" in result.output


def test_empty_note_that_was_never_synced_is_left_alone(tmp_path):
    target = date(2026, 1, 15)
    notes = [make_note(target)]
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, empty_dates={target}, is_cached_val=False):
            stack.enter_context(p)
        deleted: list[date] = []
        submitted: list[date] = []
        stack.enter_context(
            patch("hindsight_daily.cli.submit", side_effect=lambda _c, _s, n: submitted.append(n.date))
        )
        stack.enter_context(
            patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d))
        )
        result = CliRunner().invoke(cli, ["sync"])

    assert result.exit_code == 0
    assert deleted == []
    assert submitted == []


def test_empty_note_is_not_counted_as_a_vault_date(tmp_path):
    """An emptied note must not keep itself alive by appearing in the vault set."""
    target = date(2026, 1, 15)
    notes = [make_note(target), make_note(date(2026, 1, 16))]
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, empty_dates={target}, is_cached_val=True,
                               cached=["2026-01-15", "2026-01-16"]):
            stack.enter_context(p)
        deleted: list[date] = []
        stack.enter_context(patch("hindsight_daily.cli.submit"))
        stack.enter_context(
            patch("hindsight_daily.cli.delete", side_effect=lambda _c, _s, d: deleted.append(d))
        )
        result = CliRunner().invoke(cli, ["sync"])

    assert result.exit_code == 0
    # deleted once by _sync_one; the stale phase must not see it as a vault date and skip it,
    # nor delete 2026-01-16, which is present and non-empty
    assert deleted == [target]


# --- error handling around deletion ---

def test_failed_stale_deletion_reports_cleanly(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    with ExitStack() as stack:
        for p in _base_patches(tmp_path, notes, cached=["2026-01-01", "2025-12-31"]):
            stack.enter_context(p)
        stack.enter_context(patch("hindsight_daily.cli.submit"))
        stack.enter_context(patch(
            "hindsight_daily.cli.delete",
            side_effect=HindsightDeleteError("2025-12-31: listing documents failed"),
        ))
        result = CliRunner().invoke(cli, ["sync"])

    assert result.exit_code != 0
    assert "listing documents failed" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_failed_forget_reports_cleanly(tmp_path):
    with ExitStack() as stack:
        stack.enter_context(
            patch("hindsight_daily.cli.load_settings", return_value=make_settings(tmp_path))
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        stack.enter_context(patch("hindsight_daily.cli.get_client", return_value=mock_client))
        stack.enter_context(patch("hindsight_daily.cli.collect", return_value=[]))
        stack.enter_context(patch(
            "hindsight_daily.cli.delete",
            side_effect=HindsightDeleteError("2026-01-15: deleting failed"),
        ))
        evicted: list[date] = []
        stack.enter_context(patch("hindsight_daily.cli.evict", side_effect=evicted.append))
        result = CliRunner().invoke(cli, ["forget", "2026-01-15"])

    assert result.exit_code != 0
    assert "deleting failed" in result.output
    assert evicted == []  # nothing was removed from the server, so keep the cache entry


# --- argument validation ---

def test_negative_limit_is_rejected(tmp_path):
    result, submitted, deleted = run_sync(tmp_path, [make_note(date(2026, 1, 1))], limit=-1)
    assert result.exit_code != 0
    assert submitted == []
    assert deleted == []


def test_zero_limit_is_still_allowed(tmp_path):
    result, submitted, _ = run_sync(tmp_path, [make_note(date(2026, 1, 1))], limit=0)
    assert result.exit_code == 0
    assert submitted == []


def test_date_and_limit_together_are_rejected(tmp_path):
    result, submitted, deleted = run_sync(
        tmp_path, [make_note(date(2026, 1, 1))], date_arg="2026-01-01", limit=2
    )
    assert result.exit_code != 0
    assert "--limit does not apply" in result.output
    assert submitted == []


def test_targeted_sync_says_it_skipped_the_deletion_phase(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    result, _, _ = run_sync(tmp_path, notes, date_arg="2026-01-01", cached=["2025-12-31"])
    assert result.exit_code == 0
    assert "skipping the deletion phase" in result.output


# --- reconciling against the server ---

def test_remote_only_date_is_not_deleted_by_default(tmp_path):
    """Without the flag, deletion still depends purely on local cache history."""
    notes = [make_note(date(2026, 1, 1))]
    _, _, deleted = run_sync(tmp_path, notes, cached=["2026-01-01"], remote_dates=["2020-05-05"])
    assert deleted == []


def test_remote_only_date_is_deleted_when_reconciling(tmp_path):
    notes = [make_note(date(2026, 1, 1))]
    _, _, deleted = run_sync(
        tmp_path, notes, cached=["2026-01-01"], remote_dates=["2026-01-01", "2020-05-05"],
        reconcile_remote=True,
    )
    assert deleted == [date(2020, 5, 5)]


def test_reconciling_does_not_delete_dates_present_in_the_vault(tmp_path):
    notes = [make_note(date(2026, 1, 1)), make_note(date(2026, 1, 2))]
    _, _, deleted = run_sync(
        tmp_path, notes, cached=[], remote_dates=["2026-01-01", "2026-01-02"],
        reconcile_remote=True,
    )
    assert deleted == []


def test_reconcile_remote_rejected_with_date(tmp_path):
    result, _, _ = run_sync(
        tmp_path, [make_note(date(2026, 1, 1))], date_arg="2026-01-01", reconcile_remote=True
    )
    assert result.exit_code != 0
    assert "--reconcile-remote does not apply" in result.output
