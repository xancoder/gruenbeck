"""report_sections: the contents the text and the HTML part of the data mail share"""

import datetime

import pytest

from gruenbeck import report, report_sections

D = datetime.date
Stored = dict[datetime.date, int | str]


def fill(first: datetime.date, last: datetime.date, liters: int = 10) -> Stored:
    """every day from `first` to `last` (both included) with the same value"""
    return {
        first + datetime.timedelta(days=offset): liters for offset in range((last - first).days + 1)
    }


def sections_of(stored: Stored, today: datetime.date) -> list[report_sections.Section]:
    return report_sections.sections(report.compute_report(stored, today))


def period_with(missing: int = 0, no_data: int = 0) -> report.Period:
    return report.Period(
        year=2026,
        start=D(2026, 11, 1),
        end=D(2026, 11, 7),
        days=(),
        total=None,
        mean=None,
        minimum=None,
        maximum=None,
        measured=0,
        interpolated=0,
        missing=missing,
        no_data=no_data,
    )


def test_sections_come_in_a_fixed_order() -> None:
    stored = fill(D(2025, 1, 1), D(2026, 11, 22))

    found = sections_of(stored, D(2026, 11, 23))

    assert [section.key for section in found] == [
        "week",
        "current-month",
        "last-month",
        "year",
        "years",
    ]
    assert found[0].title == "Last week: week 47/2026, 2026-11-16 .. 2026-11-22"
    assert found[0].daily is not None
    assert [section.daily for section in found[1:]] == [None] * 4
    assert found[1].title == "Current month so far: 2026-11-01 .. 2026-11-22"
    assert found[2].title == "Last month: 2026-10-01 .. 2026-10-31"
    assert found[3].title == "Year so far: 2026-01-01 .. 2026-11-22"
    assert found[4].title == "Earlier years as a whole"


def test_there_is_no_current_month_on_the_1st_and_no_year_on_1_january() -> None:
    stored = fill(D(2025, 1, 1), D(2026, 11, 30))

    on_the_first = sections_of(stored, D(2026, 12, 1))
    on_new_year = sections_of(fill(D(2024, 1, 1), D(2025, 12, 31)), D(2026, 1, 1))

    assert "current-month" not in [section.key for section in on_the_first]
    assert "year" not in [section.key for section in on_new_year]


def test_a_section_has_the_period_of_the_run_first_then_the_earlier_years() -> None:
    found = sections_of(fill(D(2024, 1, 1), D(2026, 11, 22)), D(2026, 11, 23))

    week = found[0]
    assert [period.year for period in week.periods] == [2026, 2025, 2024]
    assert week.note is None


def test_note_if_no_earlier_year_has_enough_values() -> None:
    found = sections_of(fill(D(2026, 1, 1), D(2026, 11, 22)), D(2026, 11, 23))

    assert found[0].note == "No earlier year has enough values for this period."
    assert found[-1].note == "No earlier year has enough values."
    assert found[-1].periods == ()


@pytest.mark.parametrize(
    ("first_year", "note"),
    [
        (2020, "1 earlier year is not shown (older than the latest 5, or with values on less"),
        (2018, "3 earlier years are not shown (older than the latest 5, or with values on less"),
    ],
)
def test_note_about_the_earlier_years_that_are_left_out(first_year: int, note: str) -> None:
    found = sections_of(fill(D(first_year, 1, 1), D(2026, 11, 22)), D(2026, 11, 23))

    assert found[-1].note is not None
    assert found[-1].note.startswith(note)
    assert found[-1].note.endswith(" than half of the days).")
    assert len(found[-1].periods) == 5


@pytest.mark.parametrize(
    ("missing", "no_data", "note"),
    [
        (0, 0, None),
        (1, 0, "incomplete: 1 day missing"),
        (3, 0, "incomplete: 3 days missing"),
        (0, 1, "incomplete: 1 day without data"),
        (2, 5, "incomplete: 2 days missing, 5 days without data"),
    ],
)
def test_incomplete_note_names_the_days(missing: int, no_data: int, note: str | None) -> None:
    assert report_sections.incomplete_note(period_with(missing, no_data)) == note


def test_legend_explains_interpolated_days_only_if_a_shown_period_has_some() -> None:
    complete = fill(D(2025, 1, 1), D(2026, 11, 22))
    with_gap = {day: value for day, value in complete.items() if day != D(2026, 11, 18)}

    plain = report_sections.legend(sections_of(complete, D(2026, 11, 23)))
    explained = report_sections.legend(sections_of(with_gap, D(2026, 11, 23)))

    assert plain == [report_sections.LEGEND_BASIS]
    assert explained == [
        "* includes interpolated days: a gap of up to 3 days between measured days is filled"
        " with a straight line (whole liters), not stored in the data files.",
        report_sections.LEGEND_BASIS,
    ]
