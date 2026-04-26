from pathlib import Path

from diskcache import Cache
from platformdirs import user_cache_dir

from .parser import Note

_cache = Cache(user_cache_dir("hindsight-daily"))


def needs_sync(note: Note) -> bool:
    return _cache.get(str(note.date)) != note.content_hash


def mark_synced(note: Note) -> None:
    _cache.set(str(note.date), note.content_hash)
