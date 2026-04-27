from datetime import date

import pytest
from diskcache import Cache

from hindsight_daily.parser import Note


def make_note(d: date, content_hash: str) -> Note:
    return Note(date=d, frontmatter={}, content="", content_hash=content_hash)


@pytest.fixture
def cache_module(tmp_path, monkeypatch):
    from hindsight_daily import cache
    fresh = Cache(str(tmp_path))
    monkeypatch.setattr(cache, "_cache", fresh)
    yield cache
    fresh.close()


def test_unknown_note_needs_sync(cache_module):
    note = make_note(date(2026, 1, 15), "abc123")
    assert cache_module.needs_sync(note) is True


def test_synced_note_does_not_need_sync(cache_module):
    note = make_note(date(2026, 1, 15), "abc123")
    cache_module.mark_synced(note)
    assert cache_module.needs_sync(note) is False


def test_changed_hash_needs_sync_again(cache_module):
    note_v1 = make_note(date(2026, 1, 15), "hash_v1")
    cache_module.mark_synced(note_v1)
    note_v2 = make_note(date(2026, 1, 15), "hash_v2")
    assert cache_module.needs_sync(note_v2) is True


def test_evicted_note_needs_sync(cache_module):
    note = make_note(date(2026, 1, 15), "abc123")
    cache_module.mark_synced(note)
    cache_module.evict("2026-01-15")
    assert cache_module.needs_sync(note) is True


def test_cached_dates_returns_all_synced(cache_module):
    cache_module.mark_synced(make_note(date(2026, 1, 15), "h1"))
    cache_module.mark_synced(make_note(date(2026, 2, 20), "h2"))
    assert cache_module.cached_dates() == {"2026-01-15", "2026-02-20"}


def test_cached_dates_excludes_evicted(cache_module):
    cache_module.mark_synced(make_note(date(2026, 1, 15), "h1"))
    cache_module.mark_synced(make_note(date(2026, 2, 20), "h2"))
    cache_module.evict("2026-01-15")
    assert cache_module.cached_dates() == {"2026-02-20"}


def test_cached_dates_empty_initially(cache_module):
    assert cache_module.cached_dates() == set()


def test_different_dates_are_independent(cache_module):
    note_a = make_note(date(2026, 1, 15), "hash_a")
    note_b = make_note(date(2026, 1, 16), "hash_b")
    cache_module.mark_synced(note_a)
    assert cache_module.needs_sync(note_b) is True
    assert cache_module.needs_sync(note_a) is False
