import time
from typing import Any

from hindsight_client import Hindsight as _Hindsight
from hindsight_client.hindsight_client import _run_async
from loguru import logger

from .config import config
from .parser import Note, to_retain_items

_MAX_POLL_INTERVAL = 15.0


class HindsightSubmitError(Exception):
    """Raised when a note could not be retained by the Hindsight server."""


def get_client() -> _Hindsight:
    api_key: str | None = config["api_key"].get() or None
    api_url: str | None = config["api_url"].get() or None
    return _Hindsight(api_key=api_key, base_url=api_url)  # type: ignore[arg-type]


def _list_section_doc_ids(client: _Hindsight, bank_id: str, date_str: str) -> list[str]:
    prefix = f"journal:{date_str}_"
    result = _run_async(
        client.documents.list_documents(bank_id=bank_id, q=f"journal:{date_str}")
    )
    return [d["id"] for d in result.items if d["id"].startswith(prefix)]


def _operation_ids(response: Any) -> list[str]:
    """Operation ids to await, empty when the server retained the batch inline."""
    ids = getattr(response, "operation_ids", None)
    if ids:
        return [str(i) for i in ids]
    single = getattr(response, "operation_id", None)
    return [str(single)] if single else []


def _check_children(operation: Any, label: str) -> None:
    for child in getattr(operation, "child_operations", None) or []:
        if child.status == "failed":
            raise HindsightSubmitError(
                f"{label}: sub-batch {child.sub_batch_index} failed: {child.error_message or 'no error message'}"
            )
        logger.debug(
            "{}: sub-batch {} {} ({} items)", label, child.sub_batch_index, child.status, child.items_count
        )


def _wait_for_operations(client: _Hindsight, bank_id: str, op_ids: list[str], label: str) -> None:
    """Poll async retain operations until all finish, fail, or the deadline passes."""
    if not op_ids:
        logger.debug("{}: retained inline, no operations to await", label)
        return

    timeout = config["retain_timeout"].get(float)
    interval = config["retain_poll_interval"].get(float)
    deadline = time.monotonic() + timeout
    pending = list(op_ids)
    logger.debug("{}: awaiting {} retain operation(s)", label, len(pending))

    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HindsightSubmitError(
                f"{label}: still being ingested after {timeout:g}s, pending operations: {', '.join(pending)}"
            )
        time.sleep(min(interval, remaining))
        interval = min(interval * 1.5, _MAX_POLL_INTERVAL)

        still_pending = []
        for op_id in pending:
            try:
                operation = _run_async(client.operations.get_operation_status(bank_id, op_id))
            except Exception as exc:
                raise HindsightSubmitError(f"{label}: could not read status of operation {op_id}: {exc!r}") from exc
            _check_children(operation, label)
            if operation.status == "failed":
                raise HindsightSubmitError(
                    f"{label}: retain operation {op_id} failed: {operation.error_message or 'no error message'}"
                )
            if operation.status == "pending":
                still_pending.append(op_id)
            elif operation.status == "not_found":
                # The server purges operations once they complete, so this means done.
                logger.debug("{}: operation {} no longer tracked, assuming completed", label, op_id)
        pending = still_pending
        if pending:
            logger.debug("{}: {} operation(s) still pending", label, len(pending))


def submit(client: _Hindsight, note: Note) -> None:
    bank_id = config["bank_id"].get(str)
    label = str(note.date)
    items = to_retain_items(note)
    new_ids = {item["document_id"] for item in items}
    try:
        existing_ids = set(_list_section_doc_ids(client, bank_id, label))
        for doc_id in existing_ids - new_ids:
            _run_async(client.documents.delete_document(bank_id, doc_id))
        if not items:
            return
        # Retained asynchronously: big notes take the server minutes to ingest, far longer
        # than any request timeout, so we submit and then poll the operations to completion.
        response = client.retain_batch(bank_id=bank_id, items=items, retain_async=True)
    except Exception as exc:
        raise HindsightSubmitError(f"{label}: retain request failed: {exc!r}") from exc
    _wait_for_operations(client, bank_id, _operation_ids(response), label)


def delete(client: _Hindsight, date_str: str) -> None:
    bank_id = config["bank_id"].get(str)
    for doc_id in _list_section_doc_ids(client, bank_id, date_str):
        _run_async(client.documents.delete_document(bank_id, doc_id))
