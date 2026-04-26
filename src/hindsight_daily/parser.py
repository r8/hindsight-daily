from dataclasses import dataclass
from datetime import date
from pathlib import Path

import frontmatter


@dataclass
class Note:
    date: date
    frontmatter: dict
    content: str


def parse(entry_date: date, path: Path) -> Note:
    post = frontmatter.load(path)
    return Note(date=entry_date, frontmatter=post.metadata, content=post.content)
