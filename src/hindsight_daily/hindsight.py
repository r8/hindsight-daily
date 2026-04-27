from hindsight_client import Hindsight as _Hindsight
from hindsight_client.hindsight_client import _run_async

from .config import config
from .parser import Note, to_retain_kwargs


def get_client() -> _Hindsight:
    api_key: str | None = config["api_key"].get() or None
    api_url: str | None = config["api_url"].get() or None
    return _Hindsight(api_key=api_key, base_url=api_url)  # type: ignore[arg-type]


def submit(client: _Hindsight, note: Note) -> None:
    bank_id = config["bank_id"].get(str)
    client.retain(bank_id=bank_id, **to_retain_kwargs(note))


def delete(client: _Hindsight, date_str: str) -> None:
    bank_id = config["bank_id"].get(str)
    _run_async(client.documents.delete_document(bank_id, date_str))
