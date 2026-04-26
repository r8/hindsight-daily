import re
from pathlib import Path
from datetime import date

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def collect(path: Path) -> list[tuple[date, Path]]:
    results = []
    for file in path.rglob("*.md"):
        if DATE_PATTERN.match(file.stem):
            results.append((date.fromisoformat(file.stem), file))
    results.sort(key=lambda x: x[0])
    return results
