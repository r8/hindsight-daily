import re
from dataclasses import dataclass, field
from typing import Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token

# markdown-it normalizes line endings with exactly this pattern. `str.splitlines()` also breaks
# on \x0b, \x0c, \x1c-\x1e, \x85,   and  , which would shift every token.map index.
_NEWLINE_RE = re.compile(r"\r\n?|\n")
_QUOTE_MARKER_RE = re.compile(r"^ {0,3}> ?")


@dataclass
class Block:
    type: Literal["text", "quote", "code"]
    content: str
    language: str | None = None


@dataclass
class Section:
    title: str | None
    level: int
    blocks: list[Block] = field(default_factory=list)


def _source(lines: list[str], token: Token) -> str:
    """The original markdown a token covers.

    List and blockquote maps include the blank line that terminates them, so trailing
    whitespace is dropped. Leading whitespace is not: up to three spaces of indentation
    is legal on a block and worth preserving.
    """
    start, end = token.map or (0, 0)
    return "\n".join(lines[start:end]).rstrip()


def _to_block(lines: list[str], token: Token) -> Block | None:
    if token.type == "fence":
        language = token.info.strip() or None
        content = token.content.strip()
        if not content:
            return None
        # An unlabeled fence is quoted material rather than code, and is rendered as such.
        return Block(type="code", content=content, language=language) if language \
            else Block(type="quote", content=content)

    if token.type == "code_block":  # indented code
        content = token.content.strip()
        return Block(type="quote", content=content) if content else None

    if token.type == "blockquote_open":
        content = "\n".join(
            _QUOTE_MARKER_RE.sub("", line) for line in _source(lines, token).split("\n")
        ).strip()
        return Block(type="quote", content=content) if content else None

    content = _source(lines, token)
    return Block(type="text", content=content) if content else None


def parse_sections(content: str) -> list[Section]:
    """Split a note into top-level sections, preserving the source markdown of each.

    Content is sliced out of the original text rather than reassembled from tokens, so
    nested lists, ordered-list numbering, indented code, HTML, tables and anything else
    markdown-it recognizes survive without needing a handler apiece.
    """
    lines = _NEWLINE_RE.split(content)
    tokens = MarkdownIt().parse(content)
    # Closing tokens carry no map, and inline tokens always sit inside a block, so this is
    # exactly the set of top-level blocks.
    top = [(i, t) for i, t in enumerate(tokens) if t.level == 0 and t.map is not None]

    heading_levels = [int(t.tag[1]) for _, t in top if t.type == "heading_open"]
    section_level = min(heading_levels) if heading_levels else 2

    sections: list[Section] = [Section(title=None, level=0)]
    for i, token in top:
        if token.type == "heading_open" and int(token.tag[1]) == section_level:
            sections.append(Section(title=tokens[i + 1].content, level=section_level))
            continue
        if (block := _to_block(lines, token)) is not None:
            sections[-1].blocks.append(block)

    return [s for s in sections if s.title is not None or s.blocks]


def format_section(section: Section) -> str:
    parts = []
    for block in section.blocks:
        if block.type == "code":
            parts.append(f"<code lang=\"{block.language}\">\n{block.content}\n</code>")
        elif block.type == "quote":
            parts.append(f"<quote>\n{block.content}\n</quote>")
        else:
            parts.append(block.content)
    return "\n\n".join(parts)
