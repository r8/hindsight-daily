import json
from datetime import date, datetime, time
from pathlib import Path

from hindsight_daily.parser import parse, to_retain_kwargs


def write_note(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# --- parse() ---

def test_parse_returns_correct_date(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\nBody")
    note = parse(date(2026, 1, 15), p)
    assert note.date == date(2026, 1, 15)


def test_parse_extracts_frontmatter(tmp_path):
    p = write_note(tmp_path / "note.md", "---\nmood: happy\n---\nBody")
    note = parse(date(2026, 1, 15), p)
    assert note.frontmatter["mood"] == "happy"


def test_parse_extracts_body(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\nHello world")
    note = parse(date(2026, 1, 15), p)
    assert "Hello world" in note.content


def test_content_hash_is_stable(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: [work]\n---\nBody")
    h1 = parse(date(2026, 1, 15), p).content_hash
    h2 = parse(date(2026, 1, 15), p).content_hash
    assert h1 == h2


def test_content_hash_changes_when_body_changes(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: [work]\n---\nBody A")
    h1 = parse(date(2026, 1, 15), p).content_hash
    write_note(p, "---\ntags: [work]\n---\nBody B")
    h2 = parse(date(2026, 1, 15), p).content_hash
    assert h1 != h2


def test_content_hash_changes_when_only_frontmatter_changes(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: [work]\n---\nSame body")
    h1 = parse(date(2026, 1, 15), p).content_hash
    write_note(p, "---\ntags: [work, personal]\n---\nSame body")
    h2 = parse(date(2026, 1, 15), p).content_hash
    assert h1 != h2


# --- to_retain_kwargs() ---

def test_timestamp_is_midnight_of_date(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert to_retain_kwargs(note)["timestamp"] == datetime.combine(date(2026, 1, 15), time.min)


def test_document_id_is_date_string(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert to_retain_kwargs(note)["document_id"] == "2026-01-15"


def test_update_mode_is_replace(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert to_retain_kwargs(note)["update_mode"] == "replace"


def test_tags_list_passthrough(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: [work, personal]\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert to_retain_kwargs(note)["tags"] == ["work", "personal"]


def test_tags_string_wrapped_in_list(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: work\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert to_retain_kwargs(note)["tags"] == ["work"]


def test_tags_absent_defaults_to_empty_list(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert to_retain_kwargs(note)["tags"] == []


def test_scalar_frontmatter_goes_to_metadata(tmp_path):
    p = write_note(tmp_path / "note.md", "---\nmood: happy\nrating: 8\n---\n")
    note = parse(date(2026, 1, 15), p)
    metadata = to_retain_kwargs(note)["metadata"]
    assert metadata["mood"] == "happy"
    assert metadata["rating"] == "8"


def test_reserved_keys_excluded_from_metadata(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: [x]\ncreated: 2026-01-15\nmodified: 2026-01-15\n---\n")
    note = parse(date(2026, 1, 15), p)
    metadata = to_retain_kwargs(note)["metadata"]
    for key in ("tags", "created", "modified"):
        assert key not in metadata


def test_list_values_excluded_from_metadata(tmp_path):
    p = write_note(tmp_path / "note.md", "---\nitems: [a, b]\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert "items" not in to_retain_kwargs(note)["metadata"]


def test_dict_values_excluded_from_metadata(tmp_path):
    p = write_note(tmp_path / "note.md", "---\nnested:\n  key: val\n---\n")
    note = parse(date(2026, 1, 15), p)
    assert "nested" not in to_retain_kwargs(note)["metadata"]


def test_metadata_always_includes_author_and_source(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    note = parse(date(2026, 1, 15), p)
    metadata = to_retain_kwargs(note)["metadata"]
    assert metadata["author"] == "user"
    assert metadata["source"] == "daily-journal"


def test_content_field_is_valid_json(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Work\n\nDid stuff.")
    note = parse(date(2026, 1, 15), p)
    parsed = json.loads(to_retain_kwargs(note)["content"])
    assert "sections" in parsed
    assert "narrator" in parsed


def test_content_sections_match_headings(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\nDrank coffee.\n\n## Evening\n\nRead a book.")
    note = parse(date(2026, 1, 15), p)
    parsed = json.loads(to_retain_kwargs(note)["content"])
    titles = [s["title"] for s in parsed["sections"]]
    assert titles == ["Morning", "Evening"]


def test_sections_without_content_are_excluded(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Empty\n\n## Has content\n\nText here.")
    note = parse(date(2026, 1, 15), p)
    parsed = json.loads(to_retain_kwargs(note)["content"])
    titles = [s["title"] for s in parsed["sections"]]
    assert "Has content" in titles
    assert "Empty" not in titles
