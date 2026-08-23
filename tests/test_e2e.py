"""End-to-end sync against real files, a real cache, and the real parser.

`test_sync.py` patches `collect`, `parse` and `is_empty`, so the wiring between them is
never exercised — which is exactly how silently-dropped nested lists and
misclassified-as-empty notes survived the whole suite. Here only the Hindsight client is
mocked; everything else is the real thing.
"""

import json
from unittest.mock import MagicMock, patch

import confuse
import pytest
from click.testing import CliRunner
from diskcache import Cache

from hindsight_daily import cache as cache_module
from hindsight_daily.cli import cli
from hindsight_daily.config import Settings


@pytest.fixture
def vault(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
    return path


@pytest.fixture
def real_cache(tmp_path, monkeypatch):
    fresh = Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(cache_module, "_cache", fresh)
    monkeypatch.setattr(cache_module, "_open", lambda: fresh)
    yield fresh
    fresh.close()


def settings_for(vault, *, bank_id="bank") -> Settings:
    return Settings(
        bank_id=bank_id,
        api_key="key",
        api_url="https://hindsight.example",
        notes_path=vault,
        verbose=False,
        retain_timeout=60.0,
        retain_poll_interval=0.0,
    )


def fake_client() -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.retain_batch.return_value = MagicMock(operation_ids=None, operation_id=None)
    client.documents.list_documents.return_value = MagicMock(items=[], total=0)
    return client


def run(vault, args, *, client=None, bank_id="bank"):
    client = client or fake_client()
    with patch("hindsight_daily.cli.load_settings", return_value=settings_for(vault, bank_id=bank_id)), \
            patch("hindsight_daily.cli.get_client", return_value=client), \
            patch("hindsight_daily.hindsight._run_sync", side_effect=lambda coro: coro):
        result = CliRunner().invoke(cli, args)
    return result, client


def retained_documents(client) -> list[str]:
    """The markdown of every section submitted, in order."""
    documents = []
    for call in client.retain_batch.call_args_list:
        for item in call.kwargs["items"]:
            payload = json.loads(item["content"])
            documents.append(payload["sections"][0]["content"])
    return documents


# --- the parser bugs, end to end ---

def test_nested_list_reaches_the_payload(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Work\n\n- outer\n  - inner detail\n- second\n")

    result, client = run(vault, ["sync"])

    assert result.exit_code == 0, result.output
    assert retained_documents(client) == ["## Work\n\n- outer\n  - inner detail\n- second"]


def test_indented_code_is_synced_not_dropped(vault, real_cache):
    # Note that frontmatter.load strips the document, so indented code only reads as code
    # when something precedes it — which is the realistic case anyway.
    (vault / "2026-01-15.md").write_text("## Notes\n\n    x = 1\n    y = 2\n")

    result, client = run(vault, ["sync"])

    assert result.exit_code == 0, result.output
    assert retained_documents(client) == ["## Notes\n\n<quote>\nx = 1\ny = 2\n</quote>"]
    client.documents.delete_document.assert_not_called()


def test_ordered_list_keeps_its_start_number(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Steps\n\n3. third\n4. fourth\n")

    _, client = run(vault, ["sync"])

    assert retained_documents(client) == ["## Steps\n\n3. third\n4. fourth"]


def test_html_only_note_is_synced(vault, real_cache):
    (vault / "2026-01-15.md").write_text("<div>hello</div>\n")

    _, client = run(vault, ["sync"])

    assert retained_documents(client) == ["<div>hello</div>"]


# --- identity and cache behaviour ---

def test_unchanged_note_is_not_resubmitted(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Work\n\nDid stuff.\n")

    run(vault, ["sync"])
    _, second = run(vault, ["sync"])

    assert second.retain_batch.call_count == 0


def test_edited_note_is_resubmitted(vault, real_cache):
    note = vault / "2026-01-15.md"
    note.write_text("## Work\n\nDid stuff.\n")
    run(vault, ["sync"])

    note.write_text("## Work\n\nDid other stuff.\n")
    _, second = run(vault, ["sync"])

    assert second.retain_batch.call_count == 1
    assert retained_documents(second) == ["## Work\n\nDid other stuff."]


def test_duplicate_dates_fail_loudly(vault, real_cache):
    (vault / "a").mkdir()
    (vault / "b").mkdir()
    (vault / "a" / "2026-01-15.md").write_text("## A\n\none\n")
    (vault / "b" / "2026-01-15.md").write_text("## B\n\ntwo\n")

    result, client = run(vault, ["sync"])

    assert result.exit_code != 0
    assert "two notes share the date" in result.output
    client.retain_batch.assert_not_called()


def test_missing_vault_aborts_without_deleting(vault, real_cache):
    """Goes through the real load_settings, since that is where the directory check lives."""
    (vault / "2026-01-15.md").write_text("## Work\n\nDid stuff.\n")
    run(vault, ["sync"])

    gone = vault.parent / "unmounted"
    config = confuse.Configuration("hindsight-daily-test", read=False)
    config.set({
        "verbose": False, "bank_id": "bank", "api_key": "key",
        "api_url": "https://hindsight.example", "daily_notes_path": str(gone),
        "retain_timeout": 60, "retain_poll_interval": 0,
    })

    with patch("hindsight_daily.config._configuration", return_value=config), \
            patch("hindsight_daily.cli.get_client") as get_client:
        result = CliRunner().invoke(cli, ["sync"])

    assert result.exit_code != 0
    assert "not a directory" in result.output
    assert real_cache.get("2026-01-15") is not None
    get_client.assert_not_called()


def test_empty_vault_directory_does_not_prune(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Work\n\nDid stuff.\n")
    run(vault, ["sync"])

    (vault / "2026-01-15.md").unlink()
    result, client = run(vault, ["sync"])

    assert result.exit_code != 0
    assert "refusing to delete" in result.output
    client.documents.delete_document.assert_not_called()


def test_note_deleted_from_a_populated_vault_is_removed(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Work\n\nDid stuff.\n")
    (vault / "2026-01-16.md").write_text("## More\n\nAlso stuff.\n")
    run(vault, ["sync"])

    (vault / "2026-01-15.md").unlink()
    client = fake_client()
    client.documents.list_documents.return_value = MagicMock(
        items=[{"id": "journal:2026-01-15_001"}], total=1
    )
    result, client = run(vault, ["sync"], client=client)

    assert result.exit_code == 0, result.output
    deleted = {call.args[1] for call in client.documents.delete_document.call_args_list}
    assert deleted == {"journal:2026-01-15_001"}
    assert real_cache.get("2026-01-15") is None


def test_emptied_note_is_removed_from_the_server(vault, real_cache):
    note = vault / "2026-01-15.md"
    note.write_text("## Work\n\nDid stuff.\n")
    (vault / "2026-01-16.md").write_text("## More\n\nAlso stuff.\n")
    run(vault, ["sync"])

    note.write_text("## Work\n")  # heading only: nothing left to submit
    client = fake_client()
    client.documents.list_documents.return_value = MagicMock(
        items=[{"id": "journal:2026-01-15_001"}], total=1
    )
    result, client = run(vault, ["sync"], client=client)

    assert result.exit_code == 0, result.output
    assert "now empty" in result.output
    assert real_cache.get("2026-01-15") is None


def test_obsolete_documents_survive_a_failed_retain(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Work\n\nDid stuff.\n")
    client = fake_client()
    client.retain_batch.side_effect = TimeoutError("timed out")
    client.documents.list_documents.return_value = MagicMock(
        items=[{"id": "journal:2026-01-15_001"}, {"id": "journal:2026-01-15_002"}], total=2
    )

    result, client = run(vault, ["sync"], client=client)

    assert result.exit_code != 0
    client.documents.delete_document.assert_not_called()
    assert real_cache.get("2026-01-15") is None  # not marked synced, so it retries


def test_status_counts_real_notes(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Work\n\nDid stuff.\n")
    (vault / "2026-01-16.md").write_text("## More\n\nAlso stuff.\n")
    run(vault, ["sync"])
    (vault / "2026-01-17.md").write_text("## New\n\nUnsynced.\n")

    result, _ = run(vault, ["status"])

    assert "up to date     2" in result.output
    assert "needs sync     1" in result.output
    assert "stale          0" in result.output


def test_sections_become_separate_documents(vault, real_cache):
    (vault / "2026-01-15.md").write_text("## Morning\n\nWoke up.\n\n## Evening\n\nSlept.\n")

    _, client = run(vault, ["sync"])

    ids = [item["document_id"] for item in client.retain_batch.call_args.kwargs["items"]]
    assert ids == ["journal:2026-01-15_001", "journal:2026-01-15_002"]
