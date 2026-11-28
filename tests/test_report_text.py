"""report_text: the statistics as plain text of the data mail"""

import datetime
import re

import pytest

from gruenbeck import report, report_text

D = datetime.date
Stored = dict[datetime.date, int | str]

MONDAY = D(2026, 11, 23)
WEEK_START = D(2026, 11, 16)
LEGEND_INTERPOLATED = (
    "* includes interpolated days: a gap of up to 3 days between measured days is\n"
    "  filled with a straight line (whole liters), not stored in the data files."
)
LEGEND_BASIS = "Mean: liters per day with a value. Min and Max: measured days only."


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


def text_of(stored: Stored, today: datetime.date = MONDAY) -> str:
    return report_text.format_text(report.compute_report(stored, today))


def full_data() -> Stored:
    """2025 and 2026 up to the 15th of November with 20 and 30 l per day, then a week of values"""
    return {
        **fill(D(2025, 1, 1), D(2025, 12, 31), 20),
        **fill(D(2026, 1, 1), D(2026, 11, 15), 30),
        **stored_days(WEEK_START, 100, 200, 150, 120, 300, 90, 140),
    }


def test_text_with_complete_data() -> None:
    assert (
        text_of(full_data())
        == """\
Water consumption in liters, run on 2026-11-23

Last week: week 47/2026, 2026-11-16 .. 2026-11-22

  Mon 2026-11-16      100
  Tue 2026-11-17      200
  Wed 2026-11-18      150
  Thu 2026-11-19      120
  Fri 2026-11-20      300
  Sat 2026-11-21       90
  Sun 2026-11-22      140

Year  Period          Total    Mean          Min          Max
----  ------------  --------  -----  -----------  -----------
2026  11-16..11-22     1100     157     90 11-21    300 11-20
2025  11-17..11-23      140      20     20 11-17     20 11-17

Current month so far: 2026-11-01 .. 2026-11-22

Year  Period          Total    Mean          Min          Max
----  ------------  --------  -----  -----------  -----------
2026  11-01..11-22     1550      70     30 11-01    300 11-20
2025  11-01..11-22      440      20     20 11-01     20 11-01

Last month: 2026-10-01 .. 2026-10-31

Year  Period          Total    Mean          Min          Max
----  ------------  --------  -----  -----------  -----------
2026  10-01..10-31      930      30     30 10-01     30 10-01
2025  10-01..10-31      620      20     20 10-01     20 10-01

Year so far: 2026-01-01 .. 2026-11-22

Year  Period          Total    Mean          Min          Max
----  ------------  --------  -----  -----------  -----------
2026  01-01..11-22    10670      33     30 01-01    300 11-20
2025  01-01..11-22     6520      20     20 01-01     20 01-01

Earlier years as a whole

Year  Period          Total    Mean          Min          Max
----  ------------  --------  -----  -----------  -----------
2025  01-01..12-31     7300      20     20 01-01     20 01-01

Mean: liters per day with a value. Min and Max: measured days only.
"""
    )


def test_interpolated_days_are_marked_and_explained() -> None:
    # Tuesday is a value that is not a number: between 100 and 300
    text = text_of(stored_days(WEEK_START, 100, "-", 300, 300, 300, 300, 300))

    lines = text.splitlines()
    assert "  Mon 2026-11-16      100" in lines
    assert "  Tue 2026-11-17      200*" in lines
    assert "  Wed 2026-11-18      300" in lines
    # the total of the period has the mark, minimum and maximum are measured days
    assert "2026  11-16..11-22     1800*    257    100 11-16    300 11-18" in lines
    assert text.endswith(f"{LEGEND_INTERPOLATED}\n{LEGEND_BASIS}\n")


def test_without_interpolated_days_there_is_no_mark_and_no_legend_of_it() -> None:
    text = text_of(full_data())

    assert "*" not in text
    assert text.endswith(f"\n\n{LEGEND_BASIS}\n")


def test_missing_days_are_listed_and_the_period_is_incomplete() -> None:
    # Wednesday to Sunday: no value, a gap of 5 days at the end of the data
    text = text_of(stored_days(WEEK_START, 100, "-", 300))

    lines = text.splitlines()
    assert "  Thu 2026-11-19        -   missing" in lines
    assert "  Sun 2026-11-22        -   missing" in lines
    assert lines[
        lines.index("2026  11-16..11-22      600*    200    100 11-16    300 11-18") + 1
    ] == ("      incomplete: 4 days missing")


def test_one_missing_day_is_not_plural() -> None:
    text = text_of(stored_days(WEEK_START, 100, 100, 100, 100, 100, 100, "-"))

    assert "      incomplete: 1 day missing" in text.splitlines()


def test_days_before_the_first_stored_day_are_no_data() -> None:
    text = text_of(stored_days(D(2026, 11, 18), 100, 100, 100, 100, 100))

    lines = text.splitlines()
    assert "  Mon 2026-11-16        -   no data" in lines
    assert "  Tue 2026-11-17        -   no data" in lines
    assert "      incomplete: 2 days without data" in lines
    # the year so far starts with the 321 days before the first stored day
    assert "      incomplete: 321 days without data" in lines


def test_missing_days_and_days_without_data_are_both_named() -> None:
    # data from Wednesday to Friday: Monday and Tuesday are before it, the weekend after it
    text = text_of(stored_days(D(2026, 11, 18), 100, 100, 100))

    assert "      incomplete: 2 days missing, 2 days without data" in text.splitlines()


def test_without_an_earlier_year_every_table_says_so() -> None:
    text = text_of(fill(D(2026, 1, 1), D(2026, 11, 22)))

    assert text.count("No earlier year has enough values for this period.") == 4
    assert "\nNo earlier year has enough values.\n" in text
    assert "2025" not in text


def test_long_history_has_at_most_five_earlier_years_per_table() -> None:
    text = text_of(fill(D(2016, 12, 31), D(2026, 11, 22)))

    lines = text.splitlines()
    assert all(len(line) <= 78 for line in lines)
    years = [line[:4] for line in lines if re.match(r"\d{4}  \d\d-\d\d\.\.", line)]
    five = ["2025", "2024", "2023", "2022", "2021"]
    # the week, the two months and the year so far with the year of the run, then the years
    assert years == ["2026", *five] * 4 + five
    assert "2016" not in text
    assert "2017" not in text
    # the note is wrapped and says how many years are left out
    flat = " ".join(text.split())
    note = "earlier years are not shown (older than the latest 5, or with values on less than half"
    assert flat.count(f"4 {note} of the days).") == 4
    assert flat.count(f"5 {note} of the days).") == 1
    assert "\n4 earlier years are not shown (older than the latest 5, or with values on less\n" in (
        text
    )


def test_one_earlier_year_that_is_left_out_is_named_in_the_singular() -> None:
    text = text_of(fill(D(2020, 1, 1), D(2026, 11, 22)))

    flat = " ".join(text.split())
    assert flat.count("1 earlier year is not shown (") == 5
    assert "earlier years are not shown" not in flat
    assert "2020" not in text


def test_no_note_if_every_earlier_year_with_values_is_shown() -> None:
    text = text_of(fill(D(2021, 1, 1), D(2026, 11, 22)))

    assert "not shown" not in text
    assert "2021" in text


def test_earlier_years_without_enough_values_are_not_listed_and_say_so() -> None:
    # 2025 has 10 values in June only: not enough for the year, no value in the other periods
    text = text_of({**fill(D(2025, 6, 1), D(2025, 6, 10)), **fill(D(2026, 1, 1), D(2026, 11, 22))})

    assert text.count("No earlier year has enough values for this period.") == 4
    assert "\nNo earlier year has enough values.\n" in text
    assert "2025" not in text
    assert "not shown" not in text


def test_the_period_of_the_run_is_listed_with_few_values() -> None:
    text = text_of(stored_days(D(2026, 11, 20), 100, 100, 100))

    lines = text.splitlines()
    assert "2026  11-16..11-22      300     100    100 11-20    100 11-20" in lines
    assert "      incomplete: 4 days without data" in lines
    assert text.count("No earlier year has enough values for this period.") == 4


@pytest.mark.parametrize(
    ("low", "high", "total", "mean"),
    [(1, 2, "45", "2"), (2, 3, "75", "3")],
    ids=["1.5", "2.5"],
)
def test_a_mean_of_exactly_half_a_liter_is_rounded_up(
    low: int, high: int, total: str, mean: str
) -> None:
    # September 2026 has 30 days: 15 days with `low` and 15 with `high` liters
    text = text_of(stored_days(D(2026, 9, 1), *[low, high] * 15), D(2026, 10, 5))

    (row,) = [
        re.split(r"\s{2,}", line.strip())
        for line in text.splitlines()
        if line.startswith("2026  09-01..09-30")
    ]
    assert row[2:4] == [total, mean]


def test_a_period_without_values_has_dashes() -> None:
    text = text_of({})

    lines = text.splitlines()
    assert "  Sun 2026-11-22        -   no data" in lines
    assert "2026  11-16..11-22        -       -            -            -" in lines
    assert "      incomplete: 7 days without data" in lines


def test_no_current_month_on_the_first_of_a_month() -> None:
    text = text_of(fill(D(2026, 1, 1), D(2026, 11, 30)), D(2026, 12, 1))

    assert "Current month" not in text
    assert "Last month: 2026-11-01 .. 2026-11-30" in text
    assert "Year so far: 2026-01-01 .. 2026-11-30" in text


def test_no_year_so_far_on_the_first_of_january() -> None:
    text = text_of(fill(D(2025, 1, 1), D(2026, 12, 31)), D(2027, 1, 1))

    assert "Current month" not in text
    assert "Year so far" not in text
    assert "Last week: week 52/2026, 2026-12-21 .. 2026-12-27" in text
    assert "Last month: 2026-12-01 .. 2026-12-31" in text
    assert "2026  01-01..12-31     3650      10     10 01-01     10 01-01" in text.splitlines()


def test_week_over_the_new_year_is_named_by_its_calendar_week() -> None:
    text = text_of(fill(D(2026, 1, 1), D(2027, 1, 3)), D(2027, 1, 4))

    assert "Last week: week 53/2026, 2026-12-28 .. 2027-01-03" in text
    assert "2026  12-28..01-03       70      10     10 12-28     10 12-28" in text.splitlines()


def with_gaps() -> Stored:
    stored = fill(D(2024, 3, 1), D(2026, 11, 22), 999)
    # gaps of 1 and 2 days (interpolated), of 5 days (missing) and the end of the data
    for day in (D(2026, 11, 18), D(2026, 11, 19), D(2026, 10, 3), D(2025, 6, 1), D(2026, 11, 22)):
        del stored[day]
    for offset in range(5):
        del stored[D(2025, 7, 10) + datetime.timedelta(days=offset)]
    return stored


@pytest.mark.parametrize(
    "stored",
    [{}, full_data(), with_gaps(), fill(D(2025, 1, 1), D(2026, 11, 22), 10000)],
    ids=["empty", "complete", "with-gaps", "seven-digit-totals"],
)
def test_text_is_ascii_with_short_lines_and_aligned_columns(stored: Stored) -> None:
    text = text_of(stored)

    lines = text.splitlines()
    assert text.isascii()
    assert text.endswith("\n")
    assert all(len(line) <= 78 for line in lines)
    rows = [line for line in lines if re.match(r"\d{4}  \d\d-\d\d\.\.", line)]
    assert rows
    # no row is wider than the rule below the header (a dash for the maximum ends it earlier)
    assert all(len(line) <= len(report_text.TABLE_RULE) for line in rows)
    assert all(
        len(line) == len(report_text.TABLE_RULE) for line in lines if line.startswith("Year  ")
    )
    assert all(
        len(line) == len(report_text.TABLE_RULE) for line in lines if line.startswith("----")
    )
