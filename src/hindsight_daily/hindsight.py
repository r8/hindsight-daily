import asyncio
import re
import time
import warnings
from collections.abc import Coroutine
from datetime import date
from typing import Any, TypeVar

from hindsight_client import Hindsight as _Hindsight
from loguru import logger

from .config import Settings
from .parser import Note, to_retain_items

_MAX_POLL_INTERVAL = 15.0
_DOC_PAGE_SIZE = 100
_DOC_ID_RE = re.compile(r"journal:(\d{4}-\d{2}-\d{2})_\d+")

_T = TypeVar("_T")


def _run_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run one of the client's async API calls to completion.

    The generated client holds an aiohttp session bound to whichever loop first issued a
    request, and its own sync wrappers (`retain_batch`, `close`) resolve the loop through
    `asyncio.get_event_loop()`. So this has to reuse that same loop and install it as the
    current one — `asyncio.run()` would create and close a fresh loop per call, leaving the
    session attached to a loop that is gone.
    """
    with warnings.catch_warnings():
        # Fetching the current loop without creating one has no non-deprecated spelling.
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_event_loop_policy().get_event_loop()
        except RuntimeError:
            loop = None
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class HindsightError(Exception):
    """Base for failures talking to the Hindsight server."""


class HindsightSubmitError(HindsightError):
    """Raised when a note could not be retained by the Hindsight server."""


class HindsightDeleteError(HindsightError):
    """Raised when a note's documents could not be removed from the Hindsight server."""


def _describe(exc: BaseException) -> str:
    """`TimeoutError: timed out` rather than a bare `TimeoutError()`."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def get_client(settings: Settings) -> _Hindsight:
    return _Hindsight(api_key=settings.api_key, base_url=settings.api_url)


def _list_section_doc_ids(client: _Hindsight, bank_id: str, date_str: str) -> list[str]:
    """Every document id for a date, paging until the server runs out of them."""
    prefix = f"journal:{date_str}_"
    ids: list[str] = []
    offset = 0
    while True:
        result = _run_sync(client.documents.list_documents(
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
    """Sub-batch statuses are unvalidated strings in the client, so treat anything
    unrecognized as a failure rather than as quiet progress."""
    for child in getattr(operation, "child_operations", None) or []:
        match child.status:
            case "pending" | "processing" | "in_progress" | "running" | "completed":
                logger.debug(
                    "{}: sub-batch {} {} ({} items)",
                    label, child.sub_batch_index, child.status, child.items_count,
                )
            case "failed" | "cancelled" | "canceled" | "timed_out":
                raise HindsightSubmitError(
                    f"{label}: sub-batch {child.sub_batch_index} {child.status}: "
                    f"{child.error_message or 'no error message'}"
                )
            case unknown:
                raise HindsightSubmitError(
                    f"{label}: sub-batch {child.sub_batch_index} reported an unknown status: {unknown}"
                )


def _confirm_documents_landed(
    client: _Hindsight, settings: Settings, label: str, expected: int
) -> None:
    """Check the sections really are on the server after an operation stopped being tracked."""
    try:
        found = len(_list_section_doc_ids(client, settings.bank_id, label))
    except Exception as exc:
        raise HindsightSubmitError(f"{label}: listing documents failed: {_describe(exc)}") from exc
    if found < expected:
        raise HindsightSubmitError(
            f"{label}: retain operation is no longer tracked and only {found} of {expected} "
            f"document(s) are present, so the operation was probably lost"
        )


def _wait_for_operations(
    client: _Hindsight, settings: Settings, op_ids: list[str], label: str, expected: int
) -> None:
    """Poll async retain operations until all finish, fail, or the deadline passes."""
    if not op_ids:
        logger.debug("{}: retained inline, no operations to await", label)
        return

    timeout = settings.retain_timeout
    interval = settings.retain_poll_interval
    deadline = time.monotonic() + timeout
    pending = list(op_ids)
    confirmed = False
    logger.debug("{}: awaiting {} retain operation(s)", label, len(pending))

    while True:
        still_pending = []
        for op_id in pending:
            try:
                operation = _run_sync(client.operations.get_operation_status(settings.bank_id, op_id))
            except Exception as exc:
                raise HindsightSubmitError(
                    f"{label}: could not read status of operation {op_id}: {_describe(exc)}"
                ) from exc
            _check_children(operation, label)
            if operation.status == "failed":
                raise HindsightSubmitError(
                    f"{label}: retain operation {op_id} failed: {operation.error_message or 'no error message'}"
                )
            if operation.status == "pending":
                still_pending.append(op_id)
            elif operation.status == "not_found":
                # The server purges operations once they complete, so this usually means done.
                # A restart that dropped an in-flight operation looks identical though, and the
                # content hash means the note would never be retried — so check the documents
                # are actually there before believing it.
                if not confirmed:
                    _confirm_documents_landed(client, settings, label, expected)
                    confirmed = True
                logger.debug("{}: operation {} no longer tracked, documents present", label, op_id)
        pending = still_pending
        if not pending:
            return
        logger.debug("{}: {} operation(s) still pending", label, len(pending))

        # Poll first, sleep only if there is a reason to: an operation that finished inline
        # used to cost a full interval per note before anyone looked at it.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HindsightSubmitError(
                f"{label}: still being ingested after {timeout:g}s, pending operations: {', '.join(pending)}"
            )
        time.sleep(min(interval, remaining))
        interval = min(interval * 1.5, _MAX_POLL_INTERVAL)


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
        raise HindsightSubmitError(f"{label}: retain request failed: {_describe(exc)}") from exc
    _wait_for_operations(client, settings, _operation_ids(response), label, len(items))

    # Only now that the replacements are stored. Deleting first meant a failed retain left the
    # server missing sections; this way it is left with stale ones, which the next run removes.
    # Listing after the retain also avoids deleting ids the retain itself just recreated.
    new_ids = {item["document_id"] for item in items}
    try:
        obsolete = set(_list_section_doc_ids(client, bank_id, label)) - new_ids
    except Exception as exc:
        raise HindsightSubmitError(f"{label}: listing documents failed: {_describe(exc)}") from exc
    try:
        for doc_id in obsolete:
            _run_sync(client.documents.delete_document(bank_id, doc_id))
    except Exception as exc:
        raise HindsightSubmitError(
            f"{label}: removing obsolete documents failed: {_describe(exc)}"
        ) from exc


def list_journal_dates(client: _Hindsight, settings: Settings) -> set[date]:
    """Every date the server still holds journal documents for.

    Reconciling against this rather than local cache history is the only way to notice a
    note deleted from the vault on another machine, or while the cache was missing.
    """
    dates: set[date] = set()
    offset = 0
    try:
        while True:
            result = _run_sync(client.documents.list_documents(
                bank_id=settings.bank_id, q="journal:", limit=_DOC_PAGE_SIZE, offset=offset,
            ))
            for item in result.items:
                if match := _DOC_ID_RE.fullmatch(item["id"]):
                    try:
                        dates.add(date.fromisoformat(match.group(1)))
                    except ValueError:
                        continue
            offset += len(result.items)
            if not result.items or offset >= result.total:
                break
    except Exception as exc:
        raise HindsightError(f"listing journal documents failed: {_describe(exc)}") from exc
    return dates


def delete(client: _Hindsight, settings: Settings, entry_date: date) -> None:
    label = entry_date.isoformat()
    try:
        doc_ids = _list_section_doc_ids(client, settings.bank_id, label)
    except Exception as exc:
        raise HindsightDeleteError(f"{label}: listing documents failed: {_describe(exc)}") from exc
    for doc_id in doc_ids:
        try:
            _run_sync(client.documents.delete_document(settings.bank_id, doc_id))
        except Exception as exc:
            raise HindsightDeleteError(
                f"{label}: deleting {doc_id} failed: {_describe(exc)}"
            ) from exc
