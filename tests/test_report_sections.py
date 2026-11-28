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


def test_on_the_second_day_of_a_month_the_current_month_has_its_first_day() -> None:
    found = sections_of(fill(D(2025, 1, 1), D(2026, 12, 1)), D(2026, 12, 2))

    (current_month,) = [section for section in found if section.key == "current-month"]
    assert current_month.title == "Current month so far: 2026-12-01 .. 2026-12-01"
    assert current_month.periods[0].total == 10


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


@pytest.mark.parametrize(
    ("total", "days", "mean"),
    [
        (0, 1, 0),
        (7, 7, 1),
        (15, 30, 1),  # 0.5
        (45, 30, 2),  # 1.5
        (75, 30, 3),  # 2.5: half up, not half to even
        (10, 4, 3),  # 2.5
        (14, 4, 4),  # 3.5
        (44, 30, 1),  # 1.47
        (1100, 7, 157),
    ],
)
def test_mean_liters_rounds_half_up(total: int, days: int, mean: int) -> None:
    assert report_sections.mean_liters(total, days) == mean


def test_period_mean_counts_the_interpolated_days_and_rounds_half_up() -> None:
    # 11-17 interpolated (3), 11-22 missing: 2 + 3 + 4 + 2 + 2 + 2 = 15 liters on 6 days
    stored = {**fill(D(2026, 11, 1), D(2026, 11, 15), 2), D(2026, 11, 16): 2}
    stored.update({D(2026, 11, 18): 4, D(2026, 11, 19): 2, D(2026, 11, 20): 2})
    stored[D(2026, 11, 21)] = 2

    week = sections_of(stored, D(2026, 11, 23))[0].periods[0]

    assert (week.start, week.total, week.interpolated, week.missing) == (
        D(2026, 11, 16),
        15,
        1,
        1,
    )
    assert week.mean == 2.5
    assert report_sections.period_mean(week) == 3


def test_period_mean_without_a_day_with_a_value_is_none() -> None:
    assert report_sections.period_mean(period_with(no_data=7)) is None


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
