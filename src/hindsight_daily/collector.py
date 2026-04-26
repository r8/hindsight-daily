import re
from collections.abc import Iterator
from pathlib import Path
from datetime import date

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def collect(path: Path) -> Iterator[tuple[date, Path]]:
    matches = (
        (date.fromisoformat(file.stem), file)
        for file in path.rglob("*.md")
        if DATE_PATTERN.match(file.stem)
    )
    yield from sorted(matches, key=lambda x: x[0])
