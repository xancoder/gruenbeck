"""
the sections of the data mail: what the text and the HTML part both show

sections() turns a Report into the parts of the mail (the week with every day, the tables of
the periods with the same period of the earlier years, the earlier years as a whole), with the
notes and the legend. The text (report_text) and the HTML (report_html) only differ in how
they draw them, so the contents exist once, here.
"""

import dataclasses

from gruenbeck.report import (
    MAX_COMPARED_YEARS,
    MAX_INTERPOLATED_GAP,
    Comparison,
    Period,
    Report,
)

NO_EARLIER_YEAR_TEXT = "No earlier year has enough values for this period."
NO_EARLIER_YEARS_TEXT = "No earlier year has enough values."
# keep "half" in step with MIN_COVERAGE
OMITTED_YEARS_TEXT = (
    "{count} earlier {years} not shown (older than the latest {latest},"
    " or with values on less than half of the days)."
)
LEGEND_INTERPOLATED = (
    "* includes interpolated days: a gap of up to {gap} days between measured days is filled"
    " with a straight line (whole liters), not stored in the data files."
)
LEGEND_BASIS = "Mean: liters per day with a value. Min and Max: measured days only."


@dataclasses.dataclass(frozen=True)
class Section:
    """
    a part of the statistics: the period of the run and the same period of earlier years

    :param key: week, current-month, last-month, year or years (where charts belong)
    :param periods: the period of the run first, then the earlier years; the earlier years
        as a whole in the section "years"
    :param daily: the week with every day
    :param note: a note below the table; the only content if there are no periods
    """

    key: str
    title: str
    periods: tuple[Period, ...]
    daily: Period | None = None
    note: str | None = None


def sections(report: Report) -> list[Section]:
    """the sections of the data mail, in order; the same for the text and the HTML part"""
    week = report.week.current
    iso_year, iso_week, _ = week.start.isocalendar()
    parts = [
        _comparison_section(
            "week", f"Last week: week {iso_week}/{iso_year}, {_range(week)}", report.week, week
        )
    ]
    if report.current_month is not None:
        title = f"Current month so far: {_range(report.current_month.current)}"
        parts.append(_comparison_section("current-month", title, report.current_month))
    title = f"Last month: {_range(report.last_month.current)}"
    parts.append(_comparison_section("last-month", title, report.last_month))
    if report.year_to_date is not None:
        title = f"Year so far: {_range(report.year_to_date.current)}"
        parts.append(_comparison_section("year", title, report.year_to_date))
    parts.append(
        Section(
            "years",
            "Earlier years as a whole",
            report.previous_years,
            note=_earlier_years_note(
                bool(report.previous_years), report.omitted_previous_years, NO_EARLIER_YEARS_TEXT
            ),
        )
    )
    return parts


def _comparison_section(
    key: str, title: str, comparison: Comparison, daily: Period | None = None
) -> Section:
    return Section(
        key,
        title,
        (comparison.current, *comparison.previous),
        daily,
        _earlier_years_note(bool(comparison.previous), comparison.omitted, NO_EARLIER_YEAR_TEXT),
    )


def _earlier_years_note(shown: bool, omitted: int, nothing_to_show: str) -> str | None:
    """
    the note below a table about the earlier years that are not in it
    :param shown: the table has earlier years
    :param omitted: the number of earlier years with values that are left out
    :param nothing_to_show: the note if the table has no earlier year
    """
    if not shown:
        return nothing_to_show
    if omitted:
        return OMITTED_YEARS_TEXT.format(
            count=omitted,
            years="year is" if omitted == 1 else "years are",
            latest=MAX_COMPARED_YEARS,
        )
    return None


def _range(period: Period) -> str:
    return f"{period.start.isoformat()} .. {period.end.isoformat()}"


def incomplete_note(period: Period) -> str | None:
    parts = []
    if period.missing:
        parts.append(f"{_days(period.missing)} missing")
    if period.no_data:
        parts.append(f"{_days(period.no_data)} without data")
    return f"incomplete: {', '.join(parts)}" if parts else None


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def _interpolated_legend() -> str:
    return LEGEND_INTERPOLATED.format(gap=MAX_INTERPOLATED_GAP)


def legend(parts: list[Section]) -> list[str]:
    """the lines of the legend below the tables: the one about interpolated days only if needed"""
    lines = [LEGEND_BASIS]
    if any(period.interpolated for section in parts for period in section.periods):
        lines.insert(0, _interpolated_legend())
    return lines
