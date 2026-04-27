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

    heading_levels = [int(t.tag[1]) for t in tokens if t.type == "heading_open"]
    section_level = min(heading_levels) if heading_levels else 2

    sections: list[Section] = [Section(title=None, level=0)]
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token.type == "heading_open":
            level = int(token.tag[1])
            inline = tokens[i + 1]
            title = inline.content if inline else ""
            if level == section_level:
                sections.append(Section(title=title, level=level))
            else:
                prefix = "#" * level
                sections[-1].blocks.append(Block(type="text", content=f"{prefix} {title}"))
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

        if token.type in ("bullet_list_open", "ordered_list_open"):
            is_ordered = token.type == "ordered_list_open"
            depth = 1
            item_lines = []
            item_num = 1
            i += 1
            while i < len(tokens) and depth > 0:
                t = tokens[i]
                if t.type in ("bullet_list_open", "ordered_list_open"):
                    depth += 1
                elif t.type in ("bullet_list_close", "ordered_list_close"):
                    depth -= 1
                elif t.type == "inline" and depth == 1:
                    marker = f"{item_num}." if is_ordered else "-"
                    item_lines.append(f"{marker} {t.content.strip()}")
                    if is_ordered:
                        item_num += 1
                i += 1
            if item_lines:
                sections[-1].blocks.append(Block(type="text", content="\n".join(item_lines)))
            continue

        if token.type == "inline":
            text = token.content.strip()
            if text:
                sections[-1].blocks.append(Block(type="text", content=text))

        i += 1

    return [s for s in sections if s.title is not None or s.blocks]


def format_section(section: Section) -> str:
    parts = []
    for block in section.blocks:
        if block.type == "text":
            parts.append(block.content)
        elif block.type == "code":
            if block.language:
                parts.append(f"<code lang=\"{block.language}\">\n{block.content}\n</code>")
            else:
                parts.append(f"<quote>\n{block.content}\n</quote>")
        elif block.type == "quote":
            parts.append(f"<quote>\n{block.content}\n</quote>")
    return "\n\n".join(parts)
