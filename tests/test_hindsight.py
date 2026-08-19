from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hindsight_daily.hindsight import HindsightSubmitError, submit
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


def make_client(retain: SimpleNamespace, statuses: list, existing_doc_ids: list[str] | None = None) -> MagicMock:
    """Client whose document listing and operation polling are scripted."""
    client = MagicMock()
    client.retain_batch.return_value = retain
    client.documents.list_documents.return_value = SimpleNamespace(
        items=[{"id": doc_id} for doc_id in existing_doc_ids or []]
    )
    client.operations.get_operation_status.side_effect = list(statuses)
    return client


def fake_config(**values) -> MagicMock:
    """confuse-like config where each key returns its own view (MagicMock reuses one child)."""
    def view_for(key):
        view = MagicMock()
        view.get.return_value = values[key]
        return view

    mock_config = MagicMock()
    mock_config.__getitem__.side_effect = view_for
    return mock_config


def run_submit(client: MagicMock, note: Note | None = None, *, timeout: float = 60.0):
    mock_config = fake_config(bank_id="bank", retain_timeout=timeout, retain_poll_interval=0.0)

    with patch("hindsight_daily.hindsight.config", mock_config), \
            patch("hindsight_daily.hindsight.time.sleep"), \
            patch("hindsight_daily.hindsight._run_async", side_effect=lambda coro: coro):
        submit(client, note or make_note())


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
