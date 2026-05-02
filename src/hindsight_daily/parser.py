import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any

import frontmatter

from .markdown import Section, format_section, parse_sections

_NARRATOR = "The human user who owns this journal. All first-person statements refer to the user, not any AI agent."

WIKILINK_RE = re.compile(r'\[\[([^|\]]+?)(?:\s*\|[^\]]*)?\]\]')


@dataclass
class Note:
    date: date
    frontmatter: dict
    content: str
    content_hash: str


def parse(entry_date: date, path: Path) -> Note:
    post = frontmatter.load(path)
    return Note(
        date=entry_date,
        frontmatter=post.metadata,
        content=post.content,
        content_hash=sha256(
            (json.dumps(post.metadata, sort_keys=True, default=str) + "\n" + post.content).encode()
        ).hexdigest(),
    )


def is_empty(note: Note) -> bool:
    return not any(s.blocks for s in parse_sections(note.content))


def _extract_canonical_names(text: str) -> list[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for m in WIKILINK_RE.finditer(text):
        seen[m.group(1).strip()] = None
    return list(seen)


def _section_to_markdown(s: Section) -> str:
    body = format_section(s)
    return f"## {s.title}\n\n{body}" if s.title else body


def to_retain_items(note: Note) -> list[dict[str, Any]]:
    metadata = {
        k: str(v)
        for k, v in note.frontmatter.items()
        if k not in ("tags", "created", "modified") and not isinstance(v, (list, dict))
    }
    tags = note.frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    timestamp = datetime.combine(note.date, time.min)
    shared_metadata = {**metadata, "author": "user", "source": "daily-journal"}

    items = []
    for idx, s in enumerate((s for s in parse_sections(note.content) if s.blocks), start=1):
        title_entities = _extract_canonical_names(s.title) if s.title else []
        context = (
            f"Daily journal entry by user. Topic: {', '.join(title_entities)}"
            if title_entities
            else "Daily journal entry written by the User"
        )
        content = json.dumps({
            "narrator": _NARRATOR,
            "sections": [{"date": str(note.date), "author": "user", "content": _section_to_markdown(s)}],
        }, ensure_ascii=False)
        items.append({
            "content": content,
            "document_id": f"journal:{note.date}_{idx:03d}",
            "timestamp": timestamp,
            "context": context,
            "metadata": shared_metadata,
            "tags": tags,
            "entities": [{"text": e} for e in title_entities],
            "update_mode": "replace",
        })
    return items
