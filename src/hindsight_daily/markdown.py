from dataclasses import dataclass, field
from typing import Literal

from markdown_it import MarkdownIt


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


def parse_sections(content: str) -> list[Section]:
    md = MarkdownIt()
    tokens = md.parse(content)

    sections: list[Section] = [Section(title=None, level=0)]
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token.type == "heading_open":
            level = int(token.tag[1])
            inline = tokens[i + 1]
            title = inline.content if inline else ""
            sections.append(Section(title=title, level=level))
            i += 3  # heading_open, inline, heading_close
            continue

        if token.type == "blockquote_open":
            quote_lines = []
            i += 1
            while i < len(tokens) and tokens[i].type != "blockquote_close":
                t = tokens[i]
                if t.type == "inline":
                    quote_lines.append(t.content)
                i += 1
            sections[-1].blocks.append(Block(type="quote", content="\n".join(quote_lines)))
            i += 1  # blockquote_close
            continue

        if token.type == "fence":
            sections[-1].blocks.append(Block(
                type="code",
                content=token.content.strip(),
                language=token.info.strip() or None,
            ))
            i += 1
            continue

        if token.type == "inline":
            text = token.content.strip()
            if text:
                sections[-1].blocks.append(Block(type="text", content=text))

        i += 1

    return [s for s in sections if s.title is not None or s.blocks]


def format_section(section: Section) -> str:
    parts = []
    user_lines = []

    def flush_user():
        if user_lines:
            text = "\n\n".join(user_lines)
            parts.append(f"User (human, journal author): {text}")
            user_lines.clear()

    for block in section.blocks:
        if block.type == "text":
            user_lines.append(block.content)
        elif block.type == "code":
            user_lines.append(f"```{block.language or ''}\n{block.content}\n```")
        elif block.type == "quote":
            flush_user()
            parts.append(f"<external_quote>\n{block.content}\n</external_quote>")

    flush_user()
    return "\n\n".join(parts)
