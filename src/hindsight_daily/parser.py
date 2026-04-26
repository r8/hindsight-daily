import json
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any

import frontmatter


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

    timestamp = datetime.combine(note.date, time.min).isoformat()
    content = json.dumps([[{
        "role": "user",
        "content": f"User: {note.content}",
        "timestamp": timestamp,
    }]])

    return {
        "content": content,
        "timestamp": datetime.combine(note.date, time.min),
        "context": "Personal daily journal entry",
        "document_id": str(note.date),
        "metadata": {
            **metadata,
            "author": "user",
            "source": "obsidian-vault",
        },
        "tags": tags,
        "update_mode": "replace",
    }
