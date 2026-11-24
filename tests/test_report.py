"""report: statistics of the yearly data files (periods, missing values, chart series)"""

import datetime
import pathlib

import pytest

from gruenbeck import config, report, storage
from gruenbeck.report import Day, DayStatus

D = datetime.date
Stored = dict[datetime.date, int | str]

MEASURED = DayStatus.MEASURED
INTERPOLATED = DayStatus.INTERPOLATED
MISSING = DayStatus.MISSING
NO_DATA = DayStatus.NO_DATA

# the run of the data collector: Monday, the week before is 2026-11-16 ... 2026-11-22 (KW 47)
MONDAY = D(2026, 11, 23)
WEEK_START = D(2026, 11, 16)


def stored_days(start: datetime.date, *values: int | str | None) -> Stored:
    """consecutive days from `start`; None leaves a day without a row"""
    return {
        start + datetime.timedelta(days=offset): value
        for offset, value in enumerate(values)
        if value is not None
    }


def fill(first: datetime.date, last: datetime.date, liters: int = 10) -> Stored:
    """every day from `first` to `last` (both included) with the same value"""
    return {
        first + datetime.timedelta(days=offset): liters for offset in range((last - first).days + 1)
    }


def tuples(period: report.Period) -> list[tuple[datetime.date, DayStatus, int | None]]:
    return [(day.date, day.status, day.liters) for day in period.days]


def counts(period: report.Period) -> tuple[int, int, int, int]:
    """measured, interpolated, missing and days without data"""
    return period.measured, period.interpolated, period.missing, period.no_data


def write_year(
    configuration: config.Configuration, year: int, rows: dict[str, int | str]
) -> pathlib.Path:
    folder = storage.check_data_folder(configuration.data_path)
    data_file = configuration.data_file
    path = storage.get_data_file(folder, data_file.prefix, year)
    storage.write_data(path, data_file.fieldnames, rows, data_file.date_pattern)
    return path


# --- week -----------------------------------------------------------------------------------


def test_complete_week_has_the_values_and_key_figures() -> None:
    stored = stored_days(WEEK_START, 100, 200, 150, 120, 300, 90, 140)

    result = report.compute_report(stored, MONDAY)

    week = result.week.current
    assert (week.year, week.start, week.end) == (2026, WEEK_START, D(2026, 11, 22))
    assert tuples(week) == [
        (WEEK_START + datetime.timedelta(days=offset), MEASURED, liters)
        for offset, liters in enumerate([100, 200, 150, 120, 300, 90, 140])
    ]
    assert week.total == 1100
    assert week.mean == pytest.approx(1100 / 7)
    assert week.minimum == Day(D(2026, 11, 21), MEASURED, 90)
    assert week.maximum == Day(D(2026, 11, 20), MEASURED, 300)
    assert counts(week) == (7, 0, 0, 0)
    assert week.complete
    assert result.week.previous == ()


def test_minimum_and_maximum_are_the_first_day_of_equal_values() -> None:
    stored = stored_days(WEEK_START, 100, 50, 300, 50, 300, 200, 200)

    week = report.compute_report(stored, MONDAY).week.current

    assert week.minimum == Day(D(2026, 11, 17), MEASURED, 50)
    assert week.maximum == Day(D(2026, 11, 18), MEASURED, 300)


@pytest.mark.parametrize(
    ("gap", "interpolated"), [(1, [300]), (2, [233, 367]), (3, [200, 300, 400])]
)
def test_gap_of_one_to_three_days_is_interpolated_and_marked(
    gap: int, interpolated: list[int]
) -> None:
    # Monday 100, then the gap, then 500 up to Sunday: a straight line from 100 to 500
    stored = stored_days(WEEK_START, 100, *[None] * gap, *[500] * (6 - gap))

    week = report.compute_report(stored, MONDAY).week.current

    assert [day.status for day in week.days] == [
        MEASURED,
        *[INTERPOLATED] * gap,
        *[MEASURED] * (6 - gap),
    ]
    assert [day.liters for day in week.days[1 : gap + 1]] == interpolated
    assert counts(week) == (7 - gap, gap, 0, 0)
    assert week.total == 100 + sum(interpolated) + 500 * (6 - gap)
    assert week.mean == pytest.approx(week.total / 7)
    assert week.complete


def test_interpolated_day_counts_for_the_total_but_not_for_minimum_and_maximum() -> None:
    # Monday lies between Sunday the 15th (outside of the week) and Tuesday
    stored = {D(2026, 11, 15): 50, **stored_days(D(2026, 11, 17), *[400] * 6)}

    week = report.compute_report(stored, MONDAY).week.current

    assert week.days[0] == Day(WEEK_START, INTERPOLATED, 225)
    assert week.total == 225 + 6 * 400
    assert week.minimum == Day(D(2026, 11, 17), MEASURED, 400)
    assert week.maximum == Day(D(2026, 11, 17), MEASURED, 400)


def test_interpolated_values_are_rounded_half_up() -> None:
    stored = stored_days(WEEK_START, 100, None, 101, 200, None, None, 203)

    week = report.compute_report(stored, MONDAY).week.current

    # 100.5 -> 101; 200 + 1 = 201, 202 exactly
    assert [day.liters for day in week.days] == [100, 101, 101, 200, 201, 202, 203]


def test_gap_of_four_days_stays_missing_and_the_period_is_incomplete() -> None:
    stored = stored_days(WEEK_START, 100, None, None, None, None, 500, 500)

    week = report.compute_report(stored, MONDAY).week.current

    assert [(day.status, day.liters) for day in week.days[1:5]] == [(MISSING, None)] * 4
    assert counts(week) == (3, 0, 4, 0)
    # total and mean cover the days with a value
    assert week.total == 1100
    assert week.mean == pytest.approx(1100 / 3)
    assert not week.complete


@pytest.mark.parametrize("sunday", [None, "-"])
def test_gap_at_the_end_of_the_data_stays_missing(sunday: str | None) -> None:
    # no value for yesterday: no row, or a value that is not a number
    stored = stored_days(WEEK_START, 100, 100, 100, 100, 100, 100, sunday)

    week = report.compute_report(stored, MONDAY).week.current

    assert week.days[-1] == Day(D(2026, 11, 22), MISSING, None)
    assert counts(week) == (6, 0, 1, 0)
    assert week.total == 600
    assert not week.complete


def test_gap_at_the_start_of_the_data_stays_missing() -> None:
    stored = stored_days(WEEK_START, "-", 200, 200, 200, 200, 200, 200)

    week = report.compute_report(stored, MONDAY).week.current

    assert week.days[0] == Day(WEEK_START, MISSING, None)
    assert counts(week) == (6, 0, 1, 0)
    assert not week.complete


def test_days_before_the_first_stored_day_are_no_data_not_missing() -> None:
    stored = stored_days(D(2026, 11, 18), 100, 100, 100, 100, 100)

    result = report.compute_report(stored, MONDAY)

    week = result.week.current
    assert [day.status for day in week.days[:2]] == [NO_DATA, NO_DATA]
    assert counts(week) == (5, 0, 0, 2)
    assert week.total == 500
    assert week.mean == pytest.approx(100)
    assert not week.complete
    # the year so far: the days from 1 January to the 17th of November
    year = result.year_to_date
    assert year is not None
    assert counts(year.current) == (5, 0, 0, 321)


def test_week_without_any_value() -> None:
    result = report.compute_report({}, MONDAY)

    week = result.week.current
    assert counts(week) == (0, 0, 0, 7)
    assert (week.total, week.mean, week.minimum, week.maximum) == (None, None, None, None)
    assert result.week.previous == ()


@pytest.mark.parametrize(
    ("today", "start"),
    [
        (D(2026, 11, 23), D(2026, 11, 16)),  # Monday
        (D(2026, 11, 24), D(2026, 11, 16)),  # Tuesday
        (D(2026, 11, 26), D(2026, 11, 16)),  # Thursday
        (D(2026, 11, 22), D(2026, 11, 9)),  # Sunday: the week of today is not complete
    ],
)
def test_run_on_another_weekday_gives_the_last_complete_week(
    today: datetime.date, start: datetime.date
) -> None:
    stored = fill(D(2026, 11, 1), today - datetime.timedelta(days=1))

    result = report.compute_report(stored, today)

    week = result.week.current
    assert (week.start, week.end) == (start, start + datetime.timedelta(days=6))
    assert week.start.weekday() == 0
    assert week.complete
    month = result.current_month
    assert month is not None
    assert month.current.end == today - datetime.timedelta(days=1)


# --- calendar weeks and years ---------------------------------------------------------------


def test_week_is_compared_with_the_same_calendar_week_of_the_earlier_years() -> None:
    stored = {
        **fill(D(2024, 1, 1), D(2024, 12, 31), 10),
        **fill(D(2025, 1, 1), D(2025, 12, 31), 20),
        **fill(D(2026, 1, 1), D(2026, 11, 22), 30),
    }

    comparison = report.compute_report(stored, MONDAY).week

    assert comparison.current.total == 7 * 30
    assert [(p.year, p.start, p.total) for p in comparison.previous] == [
        (2025, D(2025, 11, 17), 7 * 20),
        (2024, D(2024, 11, 18), 7 * 10),
    ]
    assert all(p.start.isocalendar().week == 47 for p in comparison.previous)


def test_week_over_the_new_year_belongs_to_the_year_of_its_number() -> None:
    # 2026-12-28 ... 2027-01-03 is calendar week 53 of 2026; only 2020 had a week 53 before,
    # the other years have values around the turn of the year too
    today = D(2027, 1, 4)
    stored = {
        **fill(D(2020, 12, 20), D(2021, 1, 10), 10),
        **fill(D(2024, 12, 15), D(2025, 1, 10), 20),
        **fill(D(2025, 12, 15), D(2026, 1, 10), 30),
        # the 31st and the 1st are missing: a straight line from 100 to 400
        **stored_days(D(2026, 12, 15), *[100] * 16, None, None, 400, 400),
    }

    comparison = report.compute_report(stored, today).week

    week = comparison.current
    assert (week.year, week.start, week.end) == (2026, D(2026, 12, 28), D(2027, 1, 3))
    assert tuples(week)[3:5] == [
        (D(2026, 12, 31), INTERPOLATED, 200),
        (D(2027, 1, 1), INTERPOLATED, 300),
    ]
    assert week.total == 3 * 100 + 200 + 300 + 2 * 400
    assert [(p.year, p.start, p.end) for p in comparison.previous] == [
        (2020, D(2020, 12, 28), D(2021, 1, 3))
    ]


def test_week_one_starting_in_the_old_year_belongs_to_the_new_year() -> None:
    # 2024-12-30 ... 2025-01-05 is calendar week 1 of 2025, run on Monday 2025-01-06
    stored = fill(D(2023, 1, 1), D(2025, 1, 5), 10)

    comparison = report.compute_report(stored, D(2025, 1, 6)).week

    assert (comparison.current.year, comparison.current.start) == (2025, D(2024, 12, 30))
    assert [(p.year, p.start) for p in comparison.previous] == [
        (2024, D(2024, 1, 1)),
        (2023, D(2023, 1, 2)),
    ]
    assert all(p.complete for p in (comparison.current, *comparison.previous))


def test_earlier_year_without_values_in_the_period_is_not_compared() -> None:
    stored = {
        **fill(D(2024, 1, 1), D(2024, 12, 31), 10),
        **fill(D(2025, 12, 1), D(2025, 12, 31), 20),  # 2025 starts after the periods
        **fill(D(2026, 1, 1), D(2026, 11, 22), 30),
    }

    result = report.compute_report(stored, MONDAY)

    # 2025 has no value in any of these periods: it is not an earlier year to report
    assert [p.year for p in result.week.previous] == [2024]
    assert result.current_month is not None
    assert [p.year for p in result.current_month.previous] == [2024]
    assert [p.year for p in result.last_month.previous] == [2024]
    assert result.year_to_date is not None
    assert [p.year for p in result.year_to_date.previous] == [2024]
    assert counts(result.year_to_date.previous[0]) == (327, 0, 0, 0)
    comparisons = (result.week, result.current_month, result.last_month, result.year_to_date)
    assert [comparison.omitted for comparison in comparisons] == [0, 0, 0, 0]
    # as a whole, 2025 has values, but on 31 of 365 days only: it is counted as left out
    assert [p.year for p in result.previous_years] == [2024]
    assert result.omitted_previous_years == 1


# --- limits of the comparisons with earlier years (P008-S6) ---------------------------------


def test_coverage_counts_the_measured_and_the_interpolated_days() -> None:
    # Tuesday is interpolated, Friday to Sunday are missing (no measured day after them)
    stored = stored_days(WEEK_START, 100, None, 100, 100)

    week = report.compute_report(stored, MONDAY).week.current

    assert counts(week) == (3, 1, 3, 0)
    assert week.coverage == 4 / 7


def test_comparisons_show_at_most_the_five_latest_earlier_years() -> None:
    # a single day of 2016, then every day up to yesterday
    stored = fill(D(2016, 12, 31), D(2026, 11, 22))

    result = report.compute_report(stored, MONDAY)

    latest = [2025, 2024, 2023, 2022, 2021]
    assert result.current_month is not None
    assert result.year_to_date is not None
    comparisons = (result.week, result.current_month, result.last_month, result.year_to_date)
    for comparison in comparisons:
        assert [p.year for p in comparison.previous] == latest
        # 2017 to 2020; 2016 has no value in these periods and is no earlier year to report
        assert comparison.omitted == 4
    assert [p.year for p in result.previous_years] == latest
    # 2016 has a value in the year as a whole, but on 1 of 366 days
    assert result.omitted_previous_years == 5


def test_a_year_with_few_values_does_not_take_a_place_of_the_five_years() -> None:
    # 2024 has 62 of 366 days: it is skipped, the five latest years with enough values show
    stored = {
        **fill(D(2020, 1, 1), D(2023, 12, 31)),
        **fill(D(2024, 1, 1), D(2024, 3, 2)),
        **fill(D(2025, 1, 1), D(2026, 11, 22)),
    }

    result = report.compute_report(stored, MONDAY)

    assert [p.year for p in result.previous_years] == [2025, 2023, 2022, 2021, 2020]
    assert result.omitted_previous_years == 1


@pytest.mark.parametrize(("days", "shown"), [(4, True), (3, False)], ids=["4-of-7", "3-of-7"])
def test_earlier_week_needs_values_on_half_of_its_days(days: int, shown: bool) -> None:
    # week 47 of 2025 is 2025-11-17 ... 2025-11-23
    stored = {
        **fill(D(2025, 11, 17), D(2025, 11, 16) + datetime.timedelta(days=days)),
        **fill(D(2026, 1, 1), D(2026, 11, 22)),
    }

    week = report.compute_report(stored, MONDAY).week

    assert [p.year for p in week.previous] == ([2025] if shown else [])
    assert week.omitted == (0 if shown else 1)
    assert week.current.complete


@pytest.mark.parametrize(
    ("year", "days", "shown"),
    [(2024, 183, True), (2024, 182, False), (2025, 183, True), (2025, 182, False)],
    ids=["leap-year-183-of-366", "leap-year-182-of-366", "183-of-365", "182-of-365"],
)
def test_earlier_year_needs_values_on_half_of_its_days(year: int, days: int, shown: bool) -> None:
    stored = {
        **fill(D(year, 1, 1), D(year, 1, 1) + datetime.timedelta(days=days - 1)),
        **fill(D(2026, 1, 1), D(2026, 11, 22)),
    }

    result = report.compute_report(stored, MONDAY)

    assert [p.year for p in result.previous_years] == ([year] if shown else [])
    assert result.omitted_previous_years == (0 if shown else 1)


def test_period_of_the_run_is_shown_with_few_values() -> None:
    stored = {**fill(D(2025, 1, 1), D(2025, 12, 31)), D(2026, 11, 22): 10}

    result = report.compute_report(stored, MONDAY)

    assert result.current_month is not None
    assert result.year_to_date is not None
    comparisons = (result.week, result.current_month, result.last_month, result.year_to_date)
    assert [c.current.total for c in comparisons] == [10, 10, None, 10]
    assert [c.current.coverage < report.MIN_COVERAGE for c in comparisons] == [True] * 4
    # the earlier year is complete in these periods
    assert [[p.year for p in c.previous] for c in comparisons] == [[2025]] * 4
    # nothing but the day of the run: no earlier year to compare with is no reason to hide it
    alone = report.compute_report({D(2026, 11, 22): 10}, MONDAY)
    assert alone.week.current.total == 10
    assert (alone.week.previous, alone.week.omitted) == ((), 0)


def test_periods_without_enough_values_are_counted_as_left_out_not_shown() -> None:
    stored = {**fill(D(2025, 6, 1), D(2025, 6, 10)), **fill(D(2026, 1, 1), D(2026, 11, 22))}

    result = report.compute_report(stored, MONDAY)

    # June 2025 has values, but the periods of the run do not reach them: only the year does
    assert result.week.previous == () and result.week.omitted == 0
    assert result.previous_years == () and result.omitted_previous_years == 1


# --- month and year -------------------------------------------------------------------------


def test_months_and_year_up_to_yesterday() -> None:
    stored = fill(D(2025, 1, 1), D(2026, 11, 22), 10)

    result = report.compute_report(stored, MONDAY)

    current = result.current_month
    assert current is not None
    assert (current.current.year, current.current.start, current.current.end) == (
        2026,
        D(2026, 11, 1),
        D(2026, 11, 22),
    )
    assert current.current.total == 220
    assert [(p.year, p.start, p.end) for p in current.previous] == [
        (2025, D(2025, 11, 1), D(2025, 11, 22))
    ]
    last = result.last_month
    assert (last.current.start, last.current.end) == (D(2026, 10, 1), D(2026, 10, 31))
    assert last.current.total == 310
    assert [(p.year, p.start, p.end) for p in last.previous] == [
        (2025, D(2025, 10, 1), D(2025, 10, 31))
    ]
    year = result.year_to_date
    assert year is not None
    assert (year.current.start, year.current.end) == (D(2026, 1, 1), D(2026, 11, 22))
    assert year.current.total == 3260
    assert [(p.year, p.start, p.end, p.total) for p in year.previous] == [
        (2025, D(2025, 1, 1), D(2025, 11, 22), 3260)
    ]
    # the earlier year as a whole
    assert [(p.year, p.start, p.end, p.total) for p in result.previous_years] == [
        (2025, D(2025, 1, 1), D(2025, 12, 31), 3650)
    ]
    assert result.previous_years[0].mean == pytest.approx(10)


def test_no_current_month_on_the_first_of_a_month() -> None:
    stored = fill(D(2026, 1, 1), D(2026, 11, 30), 10)

    result = report.compute_report(stored, D(2026, 12, 1))

    assert result.current_month is None
    assert (result.last_month.current.start, result.last_month.current.end) == (
        D(2026, 11, 1),
        D(2026, 11, 30),
    )
    assert result.last_month.current.complete
    assert result.year_to_date is not None


def test_no_year_so_far_on_the_first_of_january() -> None:
    stored = fill(D(2025, 1, 1), D(2026, 12, 31), 10)

    result = report.compute_report(stored, D(2027, 1, 1))

    assert result.year_to_date is None
    assert result.current_month is None
    assert (result.week.current.start, result.week.current.end) == (
        D(2026, 12, 21),
        D(2026, 12, 27),
    )
    assert (result.last_month.current.year, result.last_month.current.start) == (
        2026,
        D(2026, 12, 1),
    )
    assert [p.year for p in result.last_month.previous] == [2025]
    assert [(p.year, p.total) for p in result.previous_years] == [(2026, 3650), (2025, 3650)]


def test_leap_day_counts_only_in_leap_years() -> None:
    # run on 1 March 2028: yesterday is 29 February, which 2027 and 2026 do not have
    stored = fill(D(2026, 1, 1), D(2028, 2, 29), 10)

    result = report.compute_report(stored, D(2028, 3, 1))

    year = result.year_to_date
    assert year is not None
    assert (year.current.end, year.current.total) == (D(2028, 2, 29), 600)
    assert [(p.year, p.end, p.total) for p in year.previous] == [
        (2027, D(2027, 2, 28), 590),
        (2026, D(2026, 2, 28), 590),
    ]
    assert result.last_month.current.total == 290
    assert [(p.year, p.total) for p in result.last_month.previous] == [(2027, 280), (2026, 280)]


def test_leap_day_of_an_earlier_year_is_not_part_of_the_same_period() -> None:
    # run on 1 March 2027: the year up to 28 February is 59 days, 2024 gets no 29 February
    stored = fill(D(2023, 1, 1), D(2027, 2, 28), 10)

    result = report.compute_report(stored, D(2027, 3, 1))

    year = result.year_to_date
    assert year is not None
    assert (year.current.end, year.current.total) == (D(2027, 2, 28), 590)
    assert [(p.year, p.end, p.total) for p in year.previous] == [
        (2026, D(2026, 2, 28), 590),
        (2025, D(2025, 2, 28), 590),
        (2024, D(2024, 2, 28), 590),
        (2023, D(2023, 2, 28), 590),
    ]
    # a complete month is compared with the complete month: February 2024 has 29 days
    assert result.last_month.current.total == 280
    assert [(p.year, p.total) for p in result.last_month.previous] == [
        (2026, 280),
        (2025, 280),
        (2024, 290),
        (2023, 280),
    ]


def test_gap_over_the_turn_of_the_year_is_interpolated_in_both_years() -> None:
    # 31 December to 2 January are missing: a straight line from 100 to 400 in four steps
    stored = {
        **fill(D(2025, 1, 1), D(2025, 12, 30), 100),
        **fill(D(2026, 1, 3), D(2026, 1, 9), 400),
    }

    result = report.compute_report(stored, D(2026, 1, 12))

    year_2025, year_2026 = result.cumulative
    assert (year_2025.year, year_2026.year) == (2025, 2026)
    assert (year_2025.points[-1].date, year_2025.points[-1].status) == (
        D(2025, 12, 31),
        INTERPOLATED,
    )
    assert year_2025.points[-1].cumulative == 364 * 100 + 175
    assert [(p.date.day, p.status, p.cumulative) for p in year_2026.points[:3]] == [
        (1, INTERPOLATED, 250),
        (2, INTERPOLATED, 575),
        (3, MEASURED, 975),
    ]


# --- files ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["-", "", "n/a", "1.5", "-5"])
def test_value_that_is_not_a_number_is_a_missing_day(
    loaded_config: config.Configuration, text: str
) -> None:
    write_year(
        loaded_config,
        2026,
        {
            "2026-11-16": 100,
            "2026-11-17": text,
            "2026-11-18": 300,
            "2026-11-19": 300,
            "2026-11-20": 300,
            "2026-11-21": 300,
            "2026-11-22": 300,
        },
    )

    week = report.build_report(
        loaded_config.data_path, loaded_config.data_file, MONDAY
    ).week.current

    assert week.days[1] == Day(D(2026, 11, 17), INTERPOLATED, 200)
    assert counts(week) == (6, 1, 0, 0)


def test_four_values_that_are_not_numbers_stay_missing(loaded_config: config.Configuration) -> None:
    write_year(
        loaded_config,
        2026,
        {
            "2026-11-16": 100,
            "2026-11-17": "-",
            "2026-11-18": "",
            "2026-11-19": "n/a",
            "2026-11-20": "-",
            "2026-11-21": 300,
            "2026-11-22": 300,
        },
    )

    week = report.build_report(
        loaded_config.data_path, loaded_config.data_file, MONDAY
    ).week.current

    assert counts(week) == (3, 0, 4, 0)
    assert week.total == 700
    assert not week.complete


def test_build_report_reads_all_years_of_the_prefix_with_the_configured_format(
    tmp_path: pathlib.Path,
) -> None:
    data_file = config.DataFile(
        date_pattern="%d.%m.%Y",
        fieldnames=config.FieldNames(date="Datum", value="Liter"),
        prefix="water",
        first_date=None,
    )
    for name, rows in {
        "water_2025.csv": "Datum,Liter\n29.12.2025,10\n30.12.2025,20\n31.12.2025,30\n",
        "water_2026.csv": (
            "Datum,Liter\n01.01.2026,40\n02.01.2026,50\n03.01.2026,60\n04.01.2026,70\n"
        ),
        # other files: not the data of this prefix
        "other_2026.csv": "Datum,Liter\n01.01.2026,1000\n",
        "water_2026.csv.bak": "Datum,Liter\n01.01.2026,2000\n",
    }.items():
        (tmp_path / name).write_text(rows, encoding="utf-8")

    result = report.build_report(tmp_path, data_file, D(2026, 1, 5))

    week = result.week.current
    assert (week.year, week.start, week.end) == (2026, D(2025, 12, 29), D(2026, 1, 4))
    assert week.total == 280
    assert counts(week) == (7, 0, 0, 0)


def test_build_report_without_data_files_has_no_values(
    loaded_config: config.Configuration, tmp_path: pathlib.Path
) -> None:
    for folder in (loaded_config.data_path, tmp_path / "missing"):
        result = report.build_report(folder, loaded_config.data_file, MONDAY)

        assert counts(result.week.current) == (0, 0, 0, 7)
        assert result.week.previous == ()
        assert result.previous_years == ()
        assert [series.year for series in result.monthly] == [2026]
        assert len(result.weekly) == 52


def test_build_report_does_not_change_the_data_files(loaded_config: config.Configuration) -> None:
    path = write_year(
        loaded_config,
        2026,
        {"2026-11-16": 100, "2026-11-17": "-", "2026-11-18": 300, "2026-11-19": 300},
    )
    before = path.read_bytes()
    folder = sorted(item.name for item in path.parent.iterdir())

    result = report.build_report(loaded_config.data_path, loaded_config.data_file, MONDAY)

    assert result.week.current.interpolated == 1
    assert path.read_bytes() == before
    assert sorted(item.name for item in path.parent.iterdir()) == folder


def test_build_report_gives_the_error_of_an_unusable_data_file(
    loaded_config: config.Configuration,
) -> None:
    folder = storage.check_data_folder(loaded_config.data_path)
    storage.get_data_file(folder, loaded_config.data_file.prefix, 2026).write_text(
        "date,liters\n2026-11-16,100\n", encoding="utf-8"
    )

    with pytest.raises(storage.StorageError, match="no column 'value'"):
        report.build_report(loaded_config.data_path, loaded_config.data_file, MONDAY)


# --- series for the charts ------------------------------------------------------------------


def test_monthly_series_has_the_current_year_and_up_to_three_earlier_years_with_values() -> None:
    stored = fill(D(2021, 1, 1), D(2026, 11, 22), 10)

    result = report.compute_report(stored, MONDAY)

    assert [series.year for series in result.monthly] == [2023, 2024, 2025, 2026]
    for series in result.monthly:
        assert [month.start for month in series.months] == [
            D(series.year, m, 1) for m in range(1, 13)
        ]
    totals_2024 = [month.total for month in result.monthly[1].months]
    assert totals_2024 == [310, 290, 310, 300, 310, 300, 310, 310, 300, 310, 300, 310]
    assert all(month.complete for month in result.monthly[1].months)
    current = result.monthly[-1].months
    assert [month.complete for month in current] == [True] * 10 + [False, False]
    # November is not over yet; December has no data at all
    assert (current[10].total, counts(current[10])) == (220, (22, 0, 0, 8))
    assert (current[11].total, counts(current[11])) == (None, (0, 0, 0, 31))


def test_monthly_series_leaves_out_earlier_years_with_few_values() -> None:
    # 30 days of 365 in 2021: no year of the charts
    stored = {**fill(D(2021, 6, 1), D(2021, 6, 30)), **fill(D(2025, 1, 1), D(2026, 11, 22))}

    result = report.compute_report(stored, MONDAY)

    assert [series.year for series in result.monthly] == [2025, 2026]
    assert [series.year for series in result.cumulative] == [2025, 2026]


@pytest.mark.parametrize(
    ("year", "days", "shown"),
    [(2024, 183, True), (2024, 182, False), (2025, 183, True), (2025, 182, False)],
    ids=["leap-year-183-of-366", "leap-year-182-of-366", "183-of-365", "182-of-365"],
)
def test_chart_year_needs_values_on_half_of_its_days(year: int, days: int, shown: bool) -> None:
    stored = {
        **fill(D(year, 1, 1), D(year, 1, 1) + datetime.timedelta(days=days - 1)),
        **fill(D(2026, 1, 1), D(2026, 11, 22)),
    }

    result = report.compute_report(stored, MONDAY)

    expected = [year, 2026] if shown else [2026]
    assert [series.year for series in result.monthly] == expected
    assert [series.year for series in result.cumulative] == expected


def test_chart_years_skip_years_with_few_values_and_always_have_the_current_year() -> None:
    stored = {
        **fill(D(2022, 1, 1), D(2022, 12, 31)),
        **fill(D(2023, 1, 1), D(2023, 3, 2)),
        **fill(D(2024, 1, 1), D(2024, 12, 31)),
        **fill(D(2025, 1, 1), D(2025, 12, 31)),
        **fill(D(2026, 11, 20), D(2026, 11, 22)),
    }

    result = report.compute_report(stored, MONDAY)

    # three earlier years with enough values at most, and 2026 with its 3 days of 365
    assert [series.year for series in result.monthly] == [2022, 2024, 2025, 2026]
    assert [series.year for series in result.cumulative] == [2022, 2024, 2025, 2026]
    # a year of the charts is not a year of the tables: those have their own limit
    assert [p.year for p in result.previous_years] == [2025, 2024, 2022]
    nothing = report.compute_report({D(2025, 1, 1): 10}, MONDAY)
    assert [series.year for series in nothing.monthly] == [2026]


def test_monthly_series_marks_interpolated_and_missing_values() -> None:
    stored = {
        **fill(D(2026, 1, 1), D(2026, 1, 9), 10),
        # the 10th is interpolated, the 20th to the 25th is missing
        **fill(D(2026, 1, 11), D(2026, 1, 19), 10),
        **fill(D(2026, 1, 26), D(2026, 11, 22), 10),
    }

    result = report.compute_report(stored, MONDAY)

    january = result.monthly[-1].months[0]
    assert counts(january) == (24, 1, 6, 0)
    assert january.total == 250
    assert not january.complete


def test_cumulative_series_has_a_point_for_every_day_of_the_year() -> None:
    stored = fill(D(2023, 1, 1), D(2026, 11, 22), 10)

    result = report.compute_report(stored, MONDAY)

    assert [series.year for series in result.cumulative] == [2023, 2024, 2025, 2026]
    assert [len(series.points) for series in result.cumulative] == [365, 366, 365, 365]
    year_2024 = result.cumulative[1].points
    assert (year_2024[0].date, year_2024[0].cumulative) == (D(2024, 1, 1), 10)
    assert (year_2024[-1].date, year_2024[-1].cumulative) == (D(2024, 12, 31), 3660)
    current = result.cumulative[-1].points
    assert [point.cumulative for point in current if point.date == D(2026, 11, 22)] == [3260]
    # no value from the day of the run on: the line ends
    after = [point for point in current if point.date >= MONDAY]
    assert {(point.status, point.cumulative) for point in after} == {(NO_DATA, None)}


def test_cumulative_series_breaks_at_missing_days_and_marks_interpolated_ones() -> None:
    stored = {
        **fill(D(2026, 1, 1), D(2026, 1, 2), 10),
        # the 3rd is interpolated (10), the 6th to the 9th is missing
        **fill(D(2026, 1, 4), D(2026, 1, 5), 10),
        **fill(D(2026, 1, 10), D(2026, 11, 22), 10),
    }

    points = report.compute_report(stored, MONDAY).cumulative[-1].points

    assert [(p.date.day, p.status, p.cumulative) for p in points[:11]] == [
        (1, MEASURED, 10),
        (2, MEASURED, 20),
        (3, INTERPOLATED, 30),
        (4, MEASURED, 40),
        (5, MEASURED, 50),
        (6, MISSING, None),
        (7, MISSING, None),
        (8, MISSING, None),
        (9, MISSING, None),
        (10, MEASURED, 60),
        (11, MEASURED, 70),
    ]


def test_weekly_series_has_the_last_52_complete_weeks() -> None:
    stored = fill(D(2024, 1, 1), D(2026, 11, 22), 10)

    result = report.compute_report(stored, MONDAY)

    weekly = result.weekly
    assert len(weekly) == 52
    assert weekly[-1] == result.week.current
    assert weekly[0].start == WEEK_START - datetime.timedelta(weeks=51)
    assert [week.start for week in weekly] == sorted(week.start for week in weekly)
    assert all(week.start.weekday() == 0 and week.total == 70 for week in weekly)
    assert all(week.complete for week in weekly)


def test_weekly_series_marks_incomplete_weeks_and_weeks_without_data() -> None:
    # the data starts on Wednesday of the second to last week
    stored = fill(D(2026, 11, 11), D(2026, 11, 22), 10)

    weekly = report.compute_report(stored, MONDAY).weekly

    assert [(week.total, week.complete) for week in weekly[:50]] == [(None, False)] * 50
    assert (weekly[-2].total, counts(weekly[-2])) == (50, (5, 0, 0, 2))
    assert (weekly[-1].total, weekly[-1].complete) == (70, True)


def test_series_of_a_year_without_earlier_years() -> None:
    stored = fill(D(2026, 1, 1), D(2026, 11, 22), 10)

    result = report.compute_report(stored, MONDAY)

    assert [series.year for series in result.monthly] == [2026]
    assert [series.year for series in result.cumulative] == [2026]
    assert result.previous_years == ()
