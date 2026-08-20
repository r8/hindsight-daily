import re
from datetime import date
from pathlib import Path

from loguru import logger

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class DuplicateNoteError(Exception):
    """Raised when two files in the vault claim the same date."""

    def __init__(self, entry_date: date, first: Path, second: Path) -> None:
        super().__init__(
            f"two notes share the date {entry_date}: {first} and {second} — "
            f"rename or move one of them"
        )
        self.date = entry_date
        self.first = first
        self.second = second


def _try_parse_date(file: Path) -> tuple[date, Path] | None:
    try:
        return (date.fromisoformat(file.stem), file)
    except ValueError:
        logger.warning("Skipping file with invalid date: {}", file)
        return None


def collect(path: Path) -> list[tuple[date, Path]]:
    """Every dated note in the vault, oldest first.

    A date identifies a note everywhere downstream — cache key, document ids — so two
    files claiming one date is an error rather than something to resolve by guessing.
    """
    parsed = filter(None, (
        _try_parse_date(file)
        for file in path.rglob("*.md")
        if DATE_PATTERN.fullmatch(file.stem)
    ))

    seen: dict[date, Path] = {}
    # Sort by path as well, so a duplicate is always reported the same way around.
    for entry_date, file in sorted(parsed, key=lambda x: (x[0], x[1])):
        if (previous := seen.get(entry_date)) is not None:
            raise DuplicateNoteError(entry_date, previous, file)
        seen[entry_date] = file
    return sorted(seen.items())
