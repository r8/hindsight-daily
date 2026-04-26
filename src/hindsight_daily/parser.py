import json
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any

import frontmatter

from .markdown import parse_sections, format_section


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
        content_hash=sha256(post.content.encode()).hexdigest(),
    )


def to_retain_kwargs(note: Note) -> dict[str, Any]:
    metadata = {
        k: str(v)
        for k, v in note.frontmatter.items()
        if k != "tags" and not isinstance(v, (list, dict))
    }
    tags = note.frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    timestamp = datetime.combine(note.date, time.min)
    sections = parse_sections(note.content)

    structured = [
        {
            "title": s.title,
            "blocks": [
                {"type": b.type, "content": b.content, **({"language": b.language} if b.language else {})}
                for b in s.blocks
            ],
        }
        for s in sections
        if s.blocks
    ]

    content = json.dumps({"sections": structured}, ensure_ascii=False)

    return {
        "content": content,
        "timestamp": timestamp,
        "context": "Daily journal entry written by the User",
        "document_id": str(note.date),
        "metadata": {
            **metadata,
            "author": "user",
            "author_type": "human",
            "source": "daily-journal",
        },
        "tags": tags,
        "update_mode": "replace",
    }
