import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from loguru import logger

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _try_parse_date(file: Path) -> tuple[date, Path] | None:
    try:
        return (date.fromisoformat(file.stem), file)
    except ValueError:
        logger.warning("Skipping file with invalid date: {}", file)
        return None


def collect(path: Path) -> Iterator[tuple[date, Path]]:
    parsed = filter(None, (
        _try_parse_date(file)
        for file in path.rglob("*.md")
        if DATE_PATTERN.match(file.stem)
    ))
    yield from sorted(parsed, key=lambda x: x[0])
