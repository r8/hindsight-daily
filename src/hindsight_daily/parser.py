from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

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
