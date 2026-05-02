from hindsight_client import Hindsight as _Hindsight
from hindsight_client.hindsight_client import _run_async

from .config import config
from .parser import Note, to_retain_items


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


def submit(client: _Hindsight, note: Note) -> None:
    bank_id = config["bank_id"].get(str)
    items = to_retain_items(note)
    new_ids = {item["document_id"] for item in items}
    existing_ids = set(_list_section_doc_ids(client, bank_id, str(note.date)))
    for doc_id in existing_ids - new_ids:
        _run_async(client.documents.delete_document(bank_id, doc_id))
    if items:
        client.retain_batch(bank_id=bank_id, items=items)


def delete(client: _Hindsight, date_str: str) -> None:
    bank_id = config["bank_id"].get(str)
    for doc_id in _list_section_doc_ids(client, bank_id, date_str):
        _run_async(client.documents.delete_document(bank_id, doc_id))
