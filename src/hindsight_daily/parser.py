import json
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any

import frontmatter

from .markdown import Section, format_section, parse_sections

_NARRATOR = "The human user who owns this journal. All first-person statements refer to the user, not any AI agent."


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


def _format_section_content(s: Section) -> str:
    body = format_section(s)
    return f"Topic: {s.title}\n\n{body}" if s.title else body


def to_retain_kwargs(note: Note) -> dict[str, Any]:
    metadata = {
        k: str(v)
        for k, v in note.frontmatter.items()
        if k not in ("tags", "created", "modified") and not isinstance(v, (list, dict))
    }
    tags = note.frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    timestamp = datetime.combine(note.date, time.min)
    sections = parse_sections(note.content)

    structured = [
        {"date": str(note.date), "author": "user", "content": _format_section_content(s)}
        for s in sections
        if s.blocks
    ]

    content = json.dumps({
        "narrator": _NARRATOR,
        "sections": structured,
    }, ensure_ascii=False)

    return {
        "content": content,
        "timestamp": timestamp,
        "context": "Daily journal entry written by the User",
        "document_id": str(note.date),
        "metadata": {
            **metadata,
            "author": "user",
            "source": "daily-journal",
        },
        "tags": tags,
        "update_mode": "replace",
    }
