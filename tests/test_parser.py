import json
from datetime import date, datetime, time
from pathlib import Path

from hindsight_daily.parser import is_empty, parse, to_retain_items


def write_note(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# --- is_empty() ---

def test_is_empty_for_blank_note(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    assert is_empty(parse(date(2026, 1, 15), p)) is True


def test_is_empty_for_headings_only_note(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\n## Evening\n")
    assert is_empty(parse(date(2026, 1, 15), p)) is True


def test_is_empty_false_when_note_has_content(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\nDrank coffee.")
    assert is_empty(parse(date(2026, 1, 15), p)) is False


def test_is_empty_false_for_frontmatter_only_note_with_body_text(tmp_path):
    p = write_note(tmp_path / "note.md", "---\ntags: [work]\n---\nSome text.")
    assert is_empty(parse(date(2026, 1, 15), p)) is False


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


# --- to_retain_items() ---

def _note_with_content(tmp_path, frontmatter="---\n---\n", body="## Work\n\nDid stuff."):
    p = write_note(tmp_path / "note.md", frontmatter + body)
    return parse(date(2026, 1, 15), p)


def test_empty_note_returns_empty_list(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n")
    assert to_retain_items(parse(date(2026, 1, 15), p)) == []


def test_returns_one_item_per_section_with_blocks(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\nDrank coffee.\n\n## Evening\n\nRead a book.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert len(items) == 2


def test_document_ids_are_namespaced_and_indexed(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\nDrank coffee.\n\n## Evening\n\nRead a book.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert items[0]["document_id"] == "journal:2026-01-15_001"
    assert items[1]["document_id"] == "journal:2026-01-15_002"


def test_timestamp_is_midnight_of_date(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path))
    assert items[0]["timestamp"] == datetime.combine(date(2026, 1, 15), time.min)


def test_update_mode_is_replace(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path))
    assert items[0]["update_mode"] == "replace"


def test_tags_list_passthrough(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path, frontmatter="---\ntags: [work, personal]\n---\n"))
    assert items[0]["tags"] == ["work", "personal"]


def test_tags_string_wrapped_in_list(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path, frontmatter="---\ntags: work\n---\n"))
    assert items[0]["tags"] == ["work"]


def test_tags_absent_defaults_to_empty_list(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path))
    assert items[0]["tags"] == []


def test_scalar_frontmatter_goes_to_metadata(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path, frontmatter="---\nmood: happy\nrating: 8\n---\n"))
    metadata = items[0]["metadata"]
    assert metadata["mood"] == "happy"
    assert metadata["rating"] == "8"


def test_reserved_keys_excluded_from_metadata(tmp_path):
    items = to_retain_items(_note_with_content(
        tmp_path, frontmatter="---\ntags: [x]\ncreated: 2026-01-15\nmodified: 2026-01-15\n---\n"
    ))
    for key in ("tags", "created", "modified"):
        assert key not in items[0]["metadata"]


def test_list_values_excluded_from_metadata(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path, frontmatter="---\nitems: [a, b]\n---\n"))
    assert "items" not in items[0]["metadata"]


def test_dict_values_excluded_from_metadata(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path, frontmatter="---\nnested:\n  key: val\n---\n"))
    assert "nested" not in items[0]["metadata"]


def test_metadata_always_includes_author_and_source(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path))
    assert items[0]["metadata"]["author"] == "user"
    assert items[0]["metadata"]["source"] == "daily-journal"


def test_content_field_is_valid_json(tmp_path):
    items = to_retain_items(_note_with_content(tmp_path))
    parsed = json.loads(items[0]["content"])
    assert "sections" in parsed
    assert "narrator" in parsed


def test_each_item_contains_only_its_own_section(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\nDrank coffee.\n\n## Evening\n\nRead a book.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert json.loads(items[0]["content"])["sections"][0]["content"].startswith("## Morning")
    assert json.loads(items[1]["content"])["sections"][0]["content"].startswith("## Evening")
    assert len(json.loads(items[0]["content"])["sections"]) == 1
    assert len(json.loads(items[1]["content"])["sections"]) == 1


def test_sections_without_content_are_excluded(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Empty\n\n## Has content\n\nText here.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert len(items) == 1
    assert "Has content" in json.loads(items[0]["content"])["sections"][0]["content"]


def test_entities_from_wikilinked_titles(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## [[УЦБ]]: notes\n\nBody text.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert items[0]["entities"] == [{"text": "УЦБ"}]
    assert "УЦБ" in items[0]["context"]


def test_entities_aliased_wikilink_uses_canonical_name(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## [[УЦБ | Центр]]\n\nBody.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert items[0]["entities"] == [{"text": "УЦБ"}]


def test_entities_empty_for_plain_titles(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Morning\n\nDrank coffee.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert items[0]["entities"] == []
    assert items[0]["context"] == "Daily journal entry written by the User"


def test_entities_scoped_per_section(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## [[A]]\n\nText.\n\n## [[B]]\n\nMore.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert items[0]["entities"] == [{"text": "A"}]
    assert items[1]["entities"] == [{"text": "B"}]


def test_wikilinks_in_body_not_added_to_entities(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## Plain title\n\n[[BodyEntity]] mentioned here.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    assert items[0]["entities"] == []


def test_section_content_has_markdown_h2_prefix(tmp_path):
    p = write_note(tmp_path / "note.md", "---\n---\n## [[Proj]]\n\nDid work.")
    items = to_retain_items(parse(date(2026, 1, 15), p))
    parsed = json.loads(items[0]["content"])
    assert parsed["sections"][0]["content"].startswith("## [[Proj]]")


# --- emptiness matches what would be submitted ---

def test_indented_code_only_note_is_not_empty(tmp_path):
    p = write_note(tmp_path / "note.md", "    x = 1\n    y = 2\n")
    note = parse(date(2026, 1, 15), p)
    assert is_empty(note) is False
    assert len(to_retain_items(note)) == 1


def test_html_only_note_is_not_empty(tmp_path):
    p = write_note(tmp_path / "note.md", "<div>hello</div>\n")
    note = parse(date(2026, 1, 15), p)
    assert is_empty(note) is False
    assert len(to_retain_items(note)) == 1


def test_headings_only_note_is_still_empty(tmp_path):
    p = write_note(tmp_path / "note.md", "## Morning\n\n## Evening\n")
    note = parse(date(2026, 1, 15), p)
    assert is_empty(note) is True
    assert to_retain_items(note) == []


def test_is_empty_agrees_with_to_retain_items(tmp_path):
    bodies = ["", "   \n\n  \n", "## H\n", "text", "    code", "<div/>", "---", "> quote"]
    for body in bodies:
        note = parse(date(2026, 1, 15), write_note(tmp_path / "note.md", body))
        assert is_empty(note) == (not to_retain_items(note)), body


# --- wikilink anchors ---

def test_heading_anchor_collapses_to_the_same_entity(tmp_path):
    p = write_note(tmp_path / "note.md", "## [[Project#Meeting notes]] and [[Project]]\n\nBody.")
    entities = to_retain_items(parse(date(2026, 1, 15), p))[0]["entities"]
    assert entities == [{"text": "Project"}]


def test_block_anchor_collapses_to_the_same_entity(tmp_path):
    p = write_note(tmp_path / "note.md", "## [[Project^abc123]] and [[Project]]\n\nBody.")
    entities = to_retain_items(parse(date(2026, 1, 15), p))[0]["entities"]
    assert entities == [{"text": "Project"}]


def test_alias_and_anchor_together(tmp_path):
    p = write_note(tmp_path / "note.md", "## [[Project#Notes|the project]]\n\nBody.")
    entities = to_retain_items(parse(date(2026, 1, 15), p))[0]["entities"]
    assert entities == [{"text": "Project"}]


def test_anchor_only_link_yields_no_entity(tmp_path):
    p = write_note(tmp_path / "note.md", "## [[#Local heading]]\n\nBody.")
    entities = to_retain_items(parse(date(2026, 1, 15), p))[0]["entities"]
    assert entities == []


def test_distinct_entities_are_still_distinct(tmp_path):
    p = write_note(tmp_path / "note.md", "## [[Alpha#x]] and [[Beta]]\n\nBody.")
    entities = to_retain_items(parse(date(2026, 1, 15), p))[0]["entities"]
    assert entities == [{"text": "Alpha"}, {"text": "Beta"}]
