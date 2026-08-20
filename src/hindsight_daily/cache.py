from datetime import date

from diskcache import Cache
from platformdirs import user_cache_dir

from .parser import Note

_cache: Cache | None = None


def _open() -> Cache:
    """Opened on first use, so importing the module does not create the cache directory."""
    global _cache
    if _cache is None:
        _cache = Cache(user_cache_dir("hindsight-daily"))
    return _cache


def close_cache() -> None:
    global _cache
    if _cache is not None:
        _cache.close()
        _cache = None


def needs_sync(note: Note) -> bool:
    cached: str | None = _open().get(note.date.isoformat())
    return cached != note.content_hash


def mark_synced(note: Note) -> None:
    _open().set(note.date.isoformat(), note.content_hash)


def evict(entry_date: date) -> None:
    _open().delete(entry_date.isoformat())


def cached_dates() -> set[date]:
    """Dates recorded as synced. Keys that are not dates are ignored, never deleted from."""
    dates: set[date] = set()
    for key in _open().iterkeys():
        try:
            dates.add(date.fromisoformat(key))
        except (TypeError, ValueError):
            continue
    return dates
