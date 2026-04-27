from hindsight_daily.markdown import Block, Section, format_section, parse_sections


def sections(content):
    return parse_sections(content)


# --- section structure ---

def test_empty_content_returns_nothing():
    assert sections("") == []


def test_plain_text_goes_into_preamble():
    result = sections("Hello world")
    assert len(result) == 1
    assert result[0].title is None
    assert result[0].blocks[0].content == "Hello world"


def test_h2_creates_section():
    result = sections("## Work\n\nDid stuff.")
    assert len(result) == 1
    assert result[0].title == "Work"


def test_h2_no_preamble_when_note_starts_with_heading():
    result = sections("## Work\n\nDid stuff.")
    assert all(s.title is not None for s in result)


def test_preamble_kept_when_content_precedes_first_heading():
    result = sections("intro\n\n## Work\n\nDid stuff.")
    assert result[0].title is None
    assert result[1].title == "Work"


def test_multiple_h2_sections():
    result = sections("## Morning\n\nWoke up.\n\n## Evening\n\nSlept.")
    assert [s.title for s in result] == ["Morning", "Evening"]


# --- dynamic section level ---

def test_h3_only_becomes_section_level():
    result = sections("### Morning\n\nWoke up.\n\n### Evening\n\nSlept.")
    assert [s.title for s in result] == ["Morning", "Evening"]


def test_h1_is_section_level_when_present():
    result = sections("# Title\n\nIntro.\n\n## Sub\n\nBody.")
    assert len(result) == 1
    assert result[0].title == "Title"


def test_h2_sub_heading_becomes_text_block_under_h1():
    result = sections("# Day\n\n## Work\n\nDid it.")
    content = format_section(result[0])
    assert "## Work" in content


def test_h3_sub_heading_becomes_text_block_under_h2():
    result = sections("## Work\n\n### Task A\n\nDetails.")
    assert result[0].title == "Work"
    content = format_section(result[0])
    assert "### Task A" in content


# --- lists ---

def test_bullet_list_preserves_markers():
    result = sections("- alpha\n- beta\n- gamma")
    content = format_section(result[0])
    assert "- alpha" in content
    assert "- beta" in content
    assert "- gamma" in content


def test_ordered_list_preserves_markers():
    result = sections("1. first\n2. second\n3. third")
    content = format_section(result[0])
    assert "1. first" in content
    assert "2. second" in content
    assert "3. third" in content


def test_list_in_section():
    result = sections("## Steps\n\n1. do this\n2. then that")
    assert result[0].title == "Steps"
    content = format_section(result[0])
    assert "1. do this" in content
    assert "2. then that" in content


def test_nested_list_top_level_items_preserved():
    result = sections("- outer one\n- outer two")
    content = format_section(result[0])
    assert "- outer one" in content
    assert "- outer two" in content


# --- block types ---

def test_code_fence_with_language():
    result = sections("```python\nprint('hi')\n```")
    block = result[0].blocks[0]
    assert block.type == "code"
    assert block.language == "python"
    assert block.content == "print('hi')"


def test_code_fence_no_language():
    result = sections("```\nraw text\n```")
    block = result[0].blocks[0]
    assert block.type == "code"
    assert block.language is None


def test_blockquote():
    result = sections("> wise words")
    block = result[0].blocks[0]
    assert block.type == "quote"
    assert "wise words" in block.content


# --- format_section ---

def test_format_section_joins_blocks_with_blank_line():
    s = Section(title="T", level=2, blocks=[
        Block(type="text", content="First"),
        Block(type="text", content="Second"),
    ])
    assert format_section(s) == "First\n\nSecond"


def test_format_section_code_with_language():
    s = Section(title="T", level=2, blocks=[
        Block(type="code", content="x = 1", language="python"),
    ])
    assert format_section(s) == '<code lang="python">\nx = 1\n</code>'


def test_format_section_code_without_language_uses_quote_tag():
    s = Section(title="T", level=2, blocks=[
        Block(type="code", content="raw", language=None),
    ])
    assert format_section(s) == "<quote>\nraw\n</quote>"


def test_format_section_blockquote():
    s = Section(title="T", level=2, blocks=[
        Block(type="quote", content="words"),
    ])
    assert format_section(s) == "<quote>\nwords\n</quote>"
