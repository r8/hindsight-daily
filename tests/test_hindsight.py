from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hindsight_daily.config import Settings
from hindsight_daily.hindsight import HindsightSubmitError, delete, submit
from hindsight_daily.parser import Note


def make_note(content: str = "## S\n\nText") -> Note:
    return Note(date=date(2026, 1, 2), frontmatter={}, content=content, content_hash="hash")


def retain_response(*op_ids: str, operation_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(operation_ids=list(op_ids) or None, operation_id=operation_id)


def op(status: str, op_id: str = "op-1", *, error_message=None, children=None) -> SimpleNamespace:
    return SimpleNamespace(
        operation_id=op_id, status=status, error_message=error_message, child_operations=children
    )


def child(status: str, *, index: int = 0, items: int = 1, error_message=None) -> SimpleNamespace:
    return SimpleNamespace(
        operation_id=f"child-{index}", status=status, sub_batch_index=index,
        items_count=items, error_message=error_message,
    )


def paged_listing(doc_ids: list[str], *, server_page_size: int | None = None, total: int | None = None):
    """Serve doc_ids the way the API does: one page per call, honouring offset and limit."""
    def list_documents(bank_id, q=None, limit=None, offset=0, **_):
        page_size = min(limit or len(doc_ids), server_page_size or (limit or len(doc_ids)))
        page = doc_ids[offset:offset + page_size]
        return SimpleNamespace(
            items=[{"id": doc_id} for doc_id in page],
            total=len(doc_ids) if total is None else total,
            limit=page_size,
            offset=offset,
        )

    return list_documents


def make_client(
    retain: SimpleNamespace,
    statuses: list,
    existing_doc_ids: list[str] | None = None,
    *,
    server_page_size: int | None = None,
    total: int | None = None,
) -> MagicMock:
    """Client whose document listing and operation polling are scripted."""
    client = MagicMock()
    client.retain_batch.return_value = retain
    client.documents.list_documents.side_effect = paged_listing(
        existing_doc_ids or [], server_page_size=server_page_size, total=total,
    )
    client.operations.get_operation_status.side_effect = list(statuses)
    return client


def make_settings(*, timeout: float = 60.0) -> Settings:
    return Settings(
        bank_id="bank",
        api_key="key",
        api_url="https://hindsight.example",
        notes_path=Path("/vault"),
        verbose=False,
        retain_timeout=timeout,
        retain_poll_interval=0.0,
    )


def run_submit(client: MagicMock, note: Note | None = None, *, timeout: float = 60.0):
    with patch("hindsight_daily.hindsight.time.sleep"), \
            patch("hindsight_daily.hindsight._run_async", side_effect=lambda coro: coro):
        submit(client, make_settings(timeout=timeout), note or make_note())


# --- submission ---

def test_submits_asynchronously_with_all_items():
    client = make_client(retain_response("op-1"), [op("completed")])
    run_submit(client)

    kwargs = client.retain_batch.call_args.kwargs
    assert kwargs["retain_async"] is True
    assert kwargs["bank_id"] == "bank"
    assert [item["document_id"] for item in kwargs["items"]] == ["journal:2026-01-02_001"]


def test_stale_documents_deleted_before_retain():
    client = make_client(
        retain_response("op-1"), [op("completed")],
        existing_doc_ids=["journal:2026-01-02_001", "journal:2026-01-02_002"],
    )
    run_submit(client)

    client.documents.delete_document.assert_called_once_with("bank", "journal:2026-01-02_002")


def test_stale_document_on_a_later_page_is_deleted():
    """The bug this paging exists for: cleanup used to only see the first page."""
    doc_ids = [f"journal:2026-01-02_{i:03d}" for i in range(1, 151)]
    client = make_client(retain_response("op-1"), [op("completed")], doc_ids, server_page_size=100)
    run_submit(client)

    deleted = {call.args[1] for call in client.documents.delete_document.call_args_list}
    assert "journal:2026-01-02_150" in deleted
    assert deleted == set(doc_ids) - {"journal:2026-01-02_001"}


def test_ids_collected_across_pages_once_each():
    doc_ids = [f"journal:2026-01-02_{i:03d}" for i in range(1, 121)]
    client = make_client(retain_response("op-1"), [op("completed")], doc_ids, server_page_size=50)
    run_submit(client)

    deleted = [call.args[1] for call in client.documents.delete_document.call_args_list]
    assert len(deleted) == len(set(deleted)) == 119  # every id but the one the note still has
    assert client.documents.list_documents.call_count == 3


def test_paging_survives_a_server_that_clamps_limit():
    doc_ids = [f"journal:2026-01-02_{i:03d}" for i in range(1, 121)]
    client = make_client(retain_response("op-1"), [op("completed")], doc_ids, server_page_size=10)
    run_submit(client)

    assert client.documents.delete_document.call_count == 119


def test_empty_page_stops_paging_when_total_overstates():
    doc_ids = [f"journal:2026-01-02_{i:03d}" for i in range(1, 4)]
    client = make_client(
        retain_response("op-1"), [op("completed")], doc_ids, server_page_size=2, total=9999,
    )
    run_submit(client)

    # pages of 2, 1, then empty
    assert client.documents.list_documents.call_count == 3
    assert client.documents.delete_document.call_count == 2


def test_other_dates_filtered_out_on_later_pages():
    doc_ids = ["journal:2026-01-02_001", "journal:2026-01-020_001", "journal:2026-01-02_002"]
    client = make_client(retain_response("op-1"), [op("completed")], doc_ids, server_page_size=1)
    run_submit(client)

    deleted = {call.args[1] for call in client.documents.delete_document.call_args_list}
    assert deleted == {"journal:2026-01-02_002"}


def test_delete_removes_documents_from_every_page():
    doc_ids = [f"journal:2026-01-02_{i:03d}" for i in range(1, 121)]
    client = make_client(retain_response(), [], doc_ids, server_page_size=100)

    with patch("hindsight_daily.hindsight._run_async", side_effect=lambda coro: coro):
        delete(client, make_settings(), date(2026, 1, 2))

    deleted = {call.args[1] for call in client.documents.delete_document.call_args_list}
    assert deleted == set(doc_ids)


def test_empty_note_retains_nothing():
    client = make_client(retain_response("op-1"), [])
    run_submit(client, Note(date=date(2026, 1, 2), frontmatter={}, content="", content_hash="h"))

    client.retain_batch.assert_not_called()


def test_transport_failure_becomes_submit_error():
    client = make_client(retain_response("op-1"), [])
    client.retain_batch.side_effect = TimeoutError()

    with pytest.raises(HindsightSubmitError, match="retain request failed"):
        run_submit(client)


# --- polling ---

def test_waits_until_operation_completes():
    client = make_client(retain_response("op-1"), [op("pending"), op("pending"), op("completed")])
    run_submit(client)

    assert client.operations.get_operation_status.call_count == 3


def test_awaits_every_operation_id():
    client = make_client(
        retain_response("op-1", "op-2"),
        [op("completed", "op-1"), op("pending", "op-2"), op("completed", "op-2")],
    )
    run_submit(client)

    assert client.operations.get_operation_status.call_count == 3


def test_no_polling_without_operation_ids():
    client = make_client(retain_response(), [])
    run_submit(client)

    client.operations.get_operation_status.assert_not_called()


def test_single_operation_id_is_awaited():
    client = make_client(retain_response(operation_id="op-9"), [op("completed", "op-9")])
    run_submit(client)

    client.operations.get_operation_status.assert_called_once_with("bank", "op-9")


def test_not_found_treated_as_completed():
    client = make_client(retain_response("op-1"), [op("not_found")])
    run_submit(client)

    assert client.operations.get_operation_status.call_count == 1


def test_failed_operation_raises_with_server_message():
    client = make_client(retain_response("op-1"), [op("failed", error_message="llm exploded")])

    with pytest.raises(HindsightSubmitError, match="llm exploded"):
        run_submit(client)


def test_failed_child_operation_raises():
    client = make_client(
        retain_response("op-1"),
        [op("pending", children=[child("completed"), child("failed", index=1, error_message="chunk 1 died")])],
    )

    with pytest.raises(HindsightSubmitError, match="chunk 1 died"):
        run_submit(client)


def test_status_read_failure_becomes_submit_error():
    client = make_client(retain_response("op-1"), [])
    client.operations.get_operation_status.side_effect = TimeoutError()

    with pytest.raises(HindsightSubmitError, match="could not read status"):
        run_submit(client)


def test_deadline_exceeded_raises_and_names_pending_operations():
    client = make_client(retain_response("op-1"), [op("pending")] * 10)
    clock = iter([0.0, 1.0, 2.0, 999.0, 999.0])

    with patch("hindsight_daily.hindsight.time.monotonic", side_effect=lambda: next(clock)):
        with pytest.raises(HindsightSubmitError, match="op-1"):
            run_submit(client, timeout=10.0)
