import time
from datetime import date
from typing import Any

from hindsight_client import Hindsight as _Hindsight
from hindsight_client.hindsight_client import _run_async
from loguru import logger

from .config import Settings
from .parser import Note, to_retain_items

_MAX_POLL_INTERVAL = 15.0
_DOC_PAGE_SIZE = 100


class HindsightSubmitError(Exception):
    """Raised when a note could not be retained by the Hindsight server."""


def get_client(settings: Settings) -> _Hindsight:
    return _Hindsight(api_key=settings.api_key, base_url=settings.api_url)


def _list_section_doc_ids(client: _Hindsight, bank_id: str, date_str: str) -> list[str]:
    """Every document id for a date, paging until the server runs out of them."""
    prefix = f"journal:{date_str}_"
    ids: list[str] = []
    offset = 0
    while True:
        result = _run_async(client.documents.list_documents(
            bank_id=bank_id, q=f"journal:{date_str}", limit=_DOC_PAGE_SIZE, offset=offset,
        ))
        ids.extend(d["id"] for d in result.items if d["id"].startswith(prefix))
        # Advance by what came back, not by the page size the server may have clamped.
        offset += len(result.items)
        if not result.items or offset >= result.total:
            break
    return list(dict.fromkeys(ids))


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


def _wait_for_operations(
    client: _Hindsight, settings: Settings, op_ids: list[str], label: str
) -> None:
    """Poll async retain operations until all finish, fail, or the deadline passes."""
    if not op_ids:
        logger.debug("{}: retained inline, no operations to await", label)
        return

    timeout = settings.retain_timeout
    interval = settings.retain_poll_interval
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
                operation = _run_async(client.operations.get_operation_status(settings.bank_id, op_id))
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


def submit(client: _Hindsight, settings: Settings, note: Note) -> None:
    bank_id = settings.bank_id
    label = str(note.date)
    items = to_retain_items(note)
    if not items:
        # Nothing to store, and nothing to clean up against — deleting here would wipe the
        # note's documents and report success. Removing an emptied note is the caller's job.
        logger.debug("{}: nothing to retain", label)
        return

    try:
        # Retained asynchronously: big notes take the server minutes to ingest, far longer
        # than any request timeout, so we submit and then poll the operations to completion.
        response = client.retain_batch(bank_id=bank_id, items=items, retain_async=True)
    except Exception as exc:
        raise HindsightSubmitError(f"{label}: retain request failed: {exc!r}") from exc
    _wait_for_operations(client, settings, _operation_ids(response), label)

    # Only now that the replacements are stored. Deleting first meant a failed retain left the
    # server missing sections; this way it is left with stale ones, which the next run removes.
    # Listing after the retain also avoids deleting ids the retain itself just recreated.
    new_ids = {item["document_id"] for item in items}
    try:
        for doc_id in set(_list_section_doc_ids(client, bank_id, label)) - new_ids:
            _run_async(client.documents.delete_document(bank_id, doc_id))
    except Exception as exc:
        raise HindsightSubmitError(f"{label}: removing obsolete documents failed: {exc!r}") from exc


def delete(client: _Hindsight, settings: Settings, entry_date: date) -> None:
    for doc_id in _list_section_doc_ids(client, settings.bank_id, entry_date.isoformat()):
        _run_async(client.documents.delete_document(settings.bank_id, doc_id))
