from datetime import date

import pytest

from hindsight_daily.collector import DuplicateNoteError, collect


def test_collects_valid_date_files(tmp_path):
    (tmp_path / "2026-01-15.md").write_text("content")
    (tmp_path / "2026-03-20.md").write_text("content")
    result = list(collect(tmp_path))
    assert [d for d, _ in result] == [date(2026, 1, 15), date(2026, 3, 20)]


def test_results_sorted_by_date(tmp_path):
    (tmp_path / "2026-03-01.md").write_text("")
    (tmp_path / "2026-01-01.md").write_text("")
    (tmp_path / "2026-06-15.md").write_text("")
    dates = [d for d, _ in collect(tmp_path)]
    assert dates == sorted(dates)


def test_skips_invalid_calendar_date(tmp_path):
    (tmp_path / "2026-02-29.md").write_text("invalid")
    (tmp_path / "2026-02-28.md").write_text("valid")
    result = list(collect(tmp_path))
    assert len(result) == 1
    assert result[0][0] == date(2026, 2, 28)


def test_skips_invalid_month(tmp_path):
    (tmp_path / "2026-13-01.md").write_text("bad")
    assert list(collect(tmp_path)) == []


def test_ignores_non_date_filenames(tmp_path):
    (tmp_path / "notes.md").write_text("content")
    (tmp_path / "README.md").write_text("content")
    (tmp_path / "2026-01-01.md").write_text("content")
    result = list(collect(tmp_path))
    assert len(result) == 1


def test_recurses_into_subdirectories(tmp_path):
    sub = tmp_path / "2026" / "January"
    sub.mkdir(parents=True)
    (sub / "2026-01-01.md").write_text("content")
    result = list(collect(tmp_path))
    assert len(result) == 1
    assert result[0][0] == date(2026, 1, 1)


def test_empty_directory(tmp_path):
    assert list(collect(tmp_path)) == []


def test_returns_path_alongside_date(tmp_path):
    p = tmp_path / "2026-04-10.md"
    p.write_text("x")
    d, path = list(collect(tmp_path))[0]
    assert path == p


def test_duplicate_dates_in_different_directories_raise(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "imported").mkdir()
    first = tmp_path / "imported" / "2026-01-15.md"
    second = tmp_path / "old" / "2026-01-15.md"
    first.write_text("a")
    second.write_text("b")

    with pytest.raises(DuplicateNoteError) as exc_info:
        collect(tmp_path)

    assert exc_info.value.date == date(2026, 1, 15)
    assert {exc_info.value.first, exc_info.value.second} == {first, second}
    assert str(first) in str(exc_info.value)
    assert str(second) in str(exc_info.value)


def test_duplicate_report_is_stable_across_runs(tmp_path):
    for sub in ("b", "a"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "2026-01-15.md").write_text(sub)

    errors = []
    for _ in range(2):
        with pytest.raises(DuplicateNoteError) as exc_info:
            collect(tmp_path)
        errors.append((exc_info.value.first, exc_info.value.second))

    assert errors[0] == errors[1]


def test_collect_returns_a_list(tmp_path):
    (tmp_path / "2026-01-15.md").write_text("x")
    result = collect(tmp_path)
    assert isinstance(result, list)
    assert len(result) == 1
