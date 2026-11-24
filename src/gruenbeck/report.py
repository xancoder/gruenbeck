"""
consumption statistics of the yearly data files, for the data mail

compute_report() classifies every day of the stored values and builds the periods of a run
on a given day: the last complete week, the current and the last complete month, the year
so far, each with the same period of the earlier years, plus the series for the charts.
build_report() reads the yearly files first. The result is plain data (dataclasses); text
and charts are made from it elsewhere. Only the standard library is needed, and the yearly
files are never changed.

Every day has one status (DayStatus):

- measured: the file holds a whole number for the day
- missing: no value although one is expected, i.e. no row or a value that is not a number
  (e.g. "-" of older runs), from the first stored day to the day before the run
- interpolated: a missing day of a gap of up to MAX_INTERPOLATED_GAP days with a measured
  day on both sides, linear and rounded to whole liters (half up). The value is made up for
  the statistics and the charts only; it is never written to a file.
- no data: before the first stored day (the collector did not run yet) and from the day of
  the run on

A period counts its days by status. Total and mean per day cover the measured and the
interpolated days; minimum and maximum only the measured ones. A period is complete if
none of its days is missing or without data.
"""

import calendar
import collections
import collections.abc
import dataclasses
import datetime
import enum
import os
import re
import textwrap
from html import escape

from gruenbeck import analysis, config, storage

ONE_DAY = datetime.timedelta(days=1)
ONE_WEEK = datetime.timedelta(days=7)
# gaps of more days stay missing
MAX_INTERPOLATED_GAP = 3
# the charts show the current year and up to this many earlier years with values
CHART_EARLIER_YEARS = 3
CHART_WEEKS = 52


class DayStatus(enum.StrEnum):
    MEASURED = "measured"
    INTERPOLATED = "interpolated"
    MISSING = "missing"
    NO_DATA = "no data"


@dataclasses.dataclass(frozen=True)
class Day:
    """one day; liters is None for a missing day and for a day without data"""

    date: datetime.date
    status: DayStatus
    liters: int | None


@dataclasses.dataclass(frozen=True)
class Period:
    """
    the days from start to end (both included) and their key figures

    :param year: year the period belongs to; for a week the ISO year (the week of
        2024-12-30 belongs to 2025)
    :param total: liters of the measured and interpolated days, None without such a day
    :param mean: liters per day over the same days, None without such a day
    :param minimum: measured day with the least liters (the first one on a tie)
    :param maximum: measured day with the most liters (the first one on a tie)
    """

    year: int
    start: datetime.date
    end: datetime.date
    days: tuple[Day, ...]
    total: int | None
    mean: float | None
    minimum: Day | None
    maximum: Day | None
    measured: int
    interpolated: int
    missing: int
    no_data: int

    @property
    def complete(self) -> bool:
        """no day is missing or without data (interpolated days do not count as such)"""
        return self.missing == 0 and self.no_data == 0


@dataclasses.dataclass(frozen=True)
class Comparison:
    """
    a period of the run and the same period of the earlier years

    :param previous: one period per earlier year that has at least one value in it, the
        latest year first; empty if there is none
    """

    current: Period
    previous: tuple[Period, ...]


@dataclasses.dataclass(frozen=True)
class YearMonths:
    """the 12 calendar months of a year, January first; a month of the future has no data"""

    year: int
    months: tuple[Period, ...]


@dataclasses.dataclass(frozen=True)
class CumulativePoint:
    """
    the consumption of the year from 1 January up to and including `date`

    cumulative is None for a missing day and a day without data: the line of the chart
    breaks there. The missing liters are not added later, so the line after a gap is
    lower than the real consumption.
    """

    date: datetime.date
    status: DayStatus
    cumulative: int | None


@dataclasses.dataclass(frozen=True)
class YearCumulative:
    """one point for every day of the year, from 1 January to 31 December"""

    year: int
    points: tuple[CumulativePoint, ...]


@dataclasses.dataclass(frozen=True)
class Report:
    """
    the statistics of the run on the day `today`

    :param week: the last complete calendar week (Monday to Sunday) before `today`
    :param current_month: the current month up to yesterday, None on the 1st of a month
    :param last_month: the last complete month before the month of `today`
    :param year_to_date: the current year up to yesterday, None on 1 January
    :param previous_years: the earlier years as a whole that have at least one value, the
        latest year first
    :param monthly: the months of the current year and of up to CHART_EARLIER_YEARS earlier
        years with values, the current year last
    :param cumulative: the same years, the current year last
    :param weekly: the last CHART_WEEKS complete weeks, the last week last
    """

    today: datetime.date
    week: Comparison
    current_month: Comparison | None
    last_month: Comparison
    year_to_date: Comparison | None
    previous_years: tuple[Period, ...]
    monthly: tuple[YearMonths, ...]
    cumulative: tuple[YearCumulative, ...]
    weekly: tuple[Period, ...]


def read_stored_days(
    data_path: str | os.PathLike[str], data_file: config.DataFile
) -> dict[datetime.date, int | str]:
    """
    the stored values of all yearly files <prefix>_<year>.csv in the data folder
    :param data_path: data folder (dataPath)
    :param data_file: dataFile of the configuration (prefix, column names, date format)
    :return: dictionary of day and value (int if numeric, else the text); empty without files
    :raises storage.StorageError: a column is missing, or a date does not match the pattern
    """
    stored: dict[datetime.date, int | str] = {}
    # a missing data folder is no file either
    for file in analysis.get_data_files(data_path, data_file.prefix):
        rows = storage.read_data_file(file, data_file.fieldnames, data_file.date_pattern)
        for text, value in rows.items():
            stored[storage.date_of(text, data_file.date_pattern)] = value
    return stored


def build_report(
    data_path: str | os.PathLike[str], data_file: config.DataFile, today: datetime.date
) -> Report:
    """
    the statistics of the run on `today` from the yearly files in the data folder
    :param today: day of the run; the values are stored up to the day before
    :raises storage.StorageError: see read_stored_days()
    """
    return compute_report(read_stored_days(data_path, data_file), today)


def compute_report(
    stored: collections.abc.Mapping[datetime.date, int | str], today: datetime.date
) -> Report:
    """
    the statistics of the run on `today`
    :param stored: dictionary of day and stored value (int if numeric, else a text)
    :param today: day of the run; the values are stored up to the day before
    """
    series = _Series(stored, today)
    yesterday = today - ONE_DAY

    last_week = today - datetime.timedelta(days=today.weekday()) - ONE_WEEK
    week = Comparison(_week(series, last_week), _earlier_weeks(series, last_week))

    current_month = None
    if today.day > 1:
        first = today.replace(day=1)
        current_month = Comparison(
            _period(series, today.year, first, yesterday),
            _with_values(
                _month(series, year, today.month, through_day=yesterday.day)
                for year in _earlier_years(series, today.year)
            ),
        )
    month_end = today.replace(day=1) - ONE_DAY
    last_month = Comparison(
        _month(series, month_end.year, month_end.month),
        _with_values(
            _month(series, year, month_end.month) for year in _earlier_years(series, month_end.year)
        ),
    )

    year_to_date = None
    if yesterday.year == today.year:
        year_to_date = Comparison(
            _period(series, today.year, datetime.date(today.year, 1, 1), yesterday),
            _with_values(
                _period(series, year, datetime.date(year, 1, 1), _same_day(yesterday, year))
                for year in _earlier_years(series, today.year)
            ),
        )
    previous_years = _with_values(
        _year(series, year) for year in _earlier_years(series, today.year)
    )

    chart_years = _chart_years(series, today.year)
    return Report(
        today=today,
        week=week,
        current_month=current_month,
        last_month=last_month,
        year_to_date=year_to_date,
        previous_years=previous_years,
        monthly=tuple(
            YearMonths(year, tuple(_month(series, year, month) for month in range(1, 13)))
            for year in chart_years
        ),
        cumulative=tuple(_cumulative(series, year) for year in chart_years),
        weekly=tuple(_week(series, last_week - n * ONE_WEEK) for n in reversed(range(CHART_WEEKS))),
    )


class _Series:
    """the stored days, classified; short gaps are interpolated"""

    def __init__(
        self, stored: collections.abc.Mapping[datetime.date, int | str], today: datetime.date
    ):
        self.measured = {day: value for day, value in stored.items() if isinstance(value, int)}
        # missing days are possible from the first stored day to the day before the run
        # (or the last stored day, if that is later)
        self.first = min(stored, default=None)
        self.last = max(max(stored, default=today), today - ONE_DAY)
        self.interpolated = _interpolate(self.measured, self.first, self.last)

    def day(self, day: datetime.date) -> Day:
        if day in self.measured:
            return Day(day, DayStatus.MEASURED, self.measured[day])
        if day in self.interpolated:
            return Day(day, DayStatus.INTERPOLATED, self.interpolated[day])
        if self.first is not None and self.first <= day <= self.last:
            return Day(day, DayStatus.MISSING, None)
        return Day(day, DayStatus.NO_DATA, None)

    def years_with_values(self) -> set[int]:
        return {day.year for day in (*self.measured, *self.interpolated)}


def _interpolate(
    measured: collections.abc.Mapping[datetime.date, int],
    first: datetime.date | None,
    last: datetime.date,
) -> dict[datetime.date, int]:
    """the values of the gaps of up to MAX_INTERPOLATED_GAP days between measured days"""
    values: dict[datetime.date, int] = {}
    if first is None:
        return values
    day = first
    while day <= last:
        if day in measured:
            day += ONE_DAY
            continue
        # a gap: the days up to the next measured day, or up to `last`
        end = day
        while end + ONE_DAY <= last and end + ONE_DAY not in measured:
            end += ONE_DAY
        length = (end - day).days + 1
        before, after = day - ONE_DAY, end + ONE_DAY
        # no measured day on one side: a gap at the border of the data stays missing
        if length <= MAX_INTERPOLATED_GAP and before in measured and after in measured:
            for step in range(1, length + 1):
                values[day + (step - 1) * ONE_DAY] = _between(
                    measured[before], measured[after], step, length + 1
                )
        day = end + ONE_DAY
    return values


def _between(before: int, after: int, step: int, steps: int) -> int:
    """the value `step` of `steps` equal steps from before to after, in whole liters (half up)"""
    return (2 * (before * (steps - step) + after * step) + steps) // (2 * steps)


def _period(series: _Series, year: int, start: datetime.date, end: datetime.date) -> Period:
    days = tuple(
        series.day(start + datetime.timedelta(days=offset))
        for offset in range((end - start).days + 1)
    )
    counts = collections.Counter(day.status for day in days)
    valued = [day.liters for day in days if day.liters is not None]
    measured = [
        (day.liters, day)
        for day in days
        if day.status is DayStatus.MEASURED and day.liters is not None
    ]
    # min() and max() give the first of equal days
    minimum = min(measured, key=lambda item: item[0])[1] if measured else None
    maximum = max(measured, key=lambda item: item[0])[1] if measured else None
    return Period(
        year=year,
        start=start,
        end=end,
        days=days,
        total=sum(valued) if valued else None,
        mean=sum(valued) / len(valued) if valued else None,
        minimum=minimum,
        maximum=maximum,
        measured=counts[DayStatus.MEASURED],
        interpolated=counts[DayStatus.INTERPOLATED],
        missing=counts[DayStatus.MISSING],
        no_data=counts[DayStatus.NO_DATA],
    )


def _week(series: _Series, monday: datetime.date) -> Period:
    return _period(series, monday.isocalendar().year, monday, monday + datetime.timedelta(days=6))


def _month(series: _Series, year: int, month: int, through_day: int | None = None) -> Period:
    """the whole month, or its days 1 to `through_day` (the month may be shorter)"""
    length = calendar.monthrange(year, month)[1]
    end = datetime.date(year, month, min(through_day or length, length))
    return _period(series, year, datetime.date(year, month, 1), end)


def _year(series: _Series, year: int) -> Period:
    return _period(series, year, datetime.date(year, 1, 1), datetime.date(year, 12, 31))


def _same_day(day: datetime.date, year: int) -> datetime.date:
    """the same month and day in `year`; 29 February in a year without it gives 28 February"""
    try:
        return day.replace(year=year)
    except ValueError:
        return datetime.date(year, 2, 28)


def _earlier_years(series: _Series, year: int) -> range:
    """the years before `year` down to the one before the first stored day, latest first"""
    if series.first is None:
        return range(0)
    # one more than the first year: its ISO weeks reach into the year before
    return range(year - 1, series.first.year - 2, -1)


def _earlier_weeks(series: _Series, monday: datetime.date) -> tuple[Period, ...]:
    """the calendar week with the same number in the earlier years that have such a week"""
    iso_year, iso_week, _ = monday.isocalendar()
    periods = []
    for year in _earlier_years(series, iso_year):
        try:
            periods.append(_week(series, datetime.date.fromisocalendar(year, iso_week, 1)))
        except ValueError:  # week 53 only exists in some years
            continue
    return _with_values(periods)


def _with_values(periods: collections.abc.Iterable[Period]) -> tuple[Period, ...]:
    """the periods with at least one measured or interpolated day"""
    return tuple(period for period in periods if period.total is not None)


def _chart_years(series: _Series, year: int) -> tuple[int, ...]:
    """up to CHART_EARLIER_YEARS earlier years with values, then the current year"""
    earlier = sorted(y for y in series.years_with_values() if y < year)
    return (*earlier[-CHART_EARLIER_YEARS:], year)


def _cumulative(series: _Series, year: int) -> YearCumulative:
    points = []
    running = 0
    for day in _year(series, year).days:
        if day.liters is None:
            points.append(CumulativePoint(day.date, day.status, None))
        else:
            running += day.liters
            points.append(CumulativePoint(day.date, day.status, running))
    return YearCumulative(year, tuple(points))


# --- text of the data mail ------------------------------------------------------------------

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# the columns of a table are this wide whatever the values are (up to 7 digits of liters)
TABLE_ROW = "{year:<4}  {period:<12}  {total:>8}  {mean:>5}  {minimum:>11}  {maximum:>11}"
TABLE_HEADER = TABLE_ROW.format(
    year="Year", period="Period", total="Total ", mean="Mean", minimum="Min", maximum="Max"
)
TABLE_RULE = TABLE_ROW.format(
    year="-" * 4, period="-" * 12, total="-" * 8, mean="-" * 5, minimum="-" * 11, maximum="-" * 11
)
# a note about an incomplete period is indented to the column "Period"
NOTE_INDENT = " " * 6
NO_EARLIER_YEAR_TEXT = "No earlier year has values for this period."
LEGEND_INTERPOLATED = (
    "* includes interpolated days: a gap of up to {gap} days between measured days is filled"
    " with a straight line (whole liters), not stored in the data files."
)
LEGEND_BASIS = "Mean: liters per day with a value. Min and Max: measured days only."


@dataclasses.dataclass(frozen=True)
class _Section:
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


def _sections(report: Report) -> list[_Section]:
    """the sections of the data mail, in order; the same for the text and the HTML part"""
    week = report.week.current
    iso_year, iso_week, _ = week.start.isocalendar()
    sections = [
        _comparison_section(
            "week", f"Last week: week {iso_week}/{iso_year}, {_range(week)}", report.week, week
        )
    ]
    if report.current_month is not None:
        title = f"Current month so far: {_range(report.current_month.current)}"
        sections.append(_comparison_section("current-month", title, report.current_month))
    title = f"Last month: {_range(report.last_month.current)}"
    sections.append(_comparison_section("last-month", title, report.last_month))
    if report.year_to_date is not None:
        title = f"Year so far: {_range(report.year_to_date.current)}"
        sections.append(_comparison_section("year", title, report.year_to_date))
    sections.append(
        _Section(
            "years",
            "Earlier years as a whole",
            report.previous_years,
            note=None if report.previous_years else "No earlier year has values.",
        )
    )
    return sections


def _comparison_section(
    key: str, title: str, comparison: Comparison, daily: Period | None = None
) -> _Section:
    return _Section(
        key,
        title,
        (comparison.current, *comparison.previous),
        daily,
        None if comparison.previous else NO_EARLIER_YEAR_TEXT,
    )


def format_text(report: Report) -> str:
    """
    the statistics as plain text for the data mail (ASCII, at most 78 characters per line)

    The last week with every day, then tables of the week, the current and the last month
    and the year so far, each with the same period of the earlier years, and the earlier
    years as a whole. A period with missing days or days without data is marked as
    incomplete with their number; a total with interpolated days has a `*`.
    """
    sections = _sections(report)
    shown = [period for section in sections for period in section.periods]
    parts = [f"Water consumption in liters, run on {report.today.isoformat()}"]
    parts += [_text_section(section) for section in sections]
    legend = [LEGEND_BASIS]
    if any(period.interpolated for period in shown):
        legend.insert(0, textwrap.fill(_interpolated_legend(), 78, subsequent_indent="  "))
    parts.append("\n".join(legend))
    return "\n\n".join(parts) + "\n"


def _range(period: Period) -> str:
    return f"{period.start.isoformat()} .. {period.end.isoformat()}"


def _text_section(section: _Section) -> str:
    lines = [section.title, ""]
    if section.daily is not None:
        lines += [_day_line(day) for day in section.daily.days]
        lines.append("")
    if section.periods:
        lines += _table(section.periods)
        if section.note:
            lines += ["", section.note]
    elif section.note:
        lines.append(section.note)
    return "\n".join(lines)


def _day_line(day: Day) -> str:
    if day.liters is None:
        note = "  missing" if day.status is DayStatus.MISSING else "  no data"
        return f"  {WEEKDAYS[day.date.weekday()]} {day.date.isoformat()}  {'-':>7} {note}"
    mark = "*" if day.status is DayStatus.INTERPOLATED else " "
    return (
        f"  {WEEKDAYS[day.date.weekday()]} {day.date.isoformat()}  {day.liters:>7}{mark}".rstrip()
    )


def _table(periods: collections.abc.Sequence[Period]) -> list[str]:
    lines = [TABLE_HEADER, TABLE_RULE]
    for period in periods:
        lines.append(_table_row(period).rstrip())
        note = _incomplete_note(period)
        if note:
            lines.append(NOTE_INDENT + note)
    return lines


def _table_row(period: Period) -> str:
    if period.total is None or period.mean is None:
        total, mean = f"{'-':>7} ", "-"
    else:
        total = f"{period.total:>7}{'*' if period.interpolated else ' '}"
        mean = f"{period.mean:.0f}"
    return TABLE_ROW.format(
        year=period.year,
        period=f"{period.start:%m-%d}..{period.end:%m-%d}",
        total=total,
        mean=mean,
        minimum=_extreme(period.minimum),
        maximum=_extreme(period.maximum),
    )


def _extreme(day: Day | None) -> str:
    if day is None or day.liters is None:
        return "-"
    return f"{day.liters:>5} {day.date:%m-%d}"


def _incomplete_note(period: Period) -> str | None:
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


# --- HTML part of the data mail -------------------------------------------------------------

HTML_WIDTH = 640
HTML_FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
# The colors are inline, so a mail program without style sheets shows the light variant. The
# style sheet only switches them for a dark color scheme; the charts follow the text color.
HTML_DARK_STYLE = (
    "@media (prefers-color-scheme: dark) {"
    " .gb-page { background: #0b1220 !important; }"
    " .gb-card { background: #111827 !important; color: #e5e7eb !important; }"
    " .gb-muted { color: #9ca3af !important; }"
    " .gb-warn { color: #fbbf24 !important; }"
    " .gb-rule { border-color: #374151 !important; }"
    " .gb-head { background: #1f2937 !important; }"
    " }"
)
HTML_HEAD = (
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="color-scheme" content="light dark">'
    '<meta name="supported-color-schemes" content="light dark">'
    "<title>Water consumption</title>"
    f"<style>{HTML_DARK_STYLE}</style>"
)
NBSP = "\N{NO-BREAK SPACE}"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
HTML_MUTED = "color:#6b7280;"
HTML_RULE = "border-bottom:1px solid #e5e7eb;"
# the charts (keys of gruenbeck.charts.CHARTS) before and after the tables of a section
HTML_CHARTS_BEFORE = {"week": ("week",), "year": ("cumulative",)}
HTML_CHARTS_AFTER = {"week": ("weekly",), "last-month": ("monthly",)}
TABLE_COLUMNS = (
    ("Year", "left"),
    ("Period", "left"),
    ("Total", "right"),
    ("Mean", "right"),
    ("Min", "right"),
    ("Max", "right"),
)


def format_html(
    report: Report,
    charts: collections.abc.Mapping[str, str] | None = None,
    notes: collections.abc.Sequence[str] = (),
) -> str:
    """
    the statistics as HTML document for the data mail: the tables of format_text() and the charts

    The layout is a table of at most HTML_WIDTH pixels with inline CSS, so it works in mail
    programs; a style sheet in the head only adds the colors for a dark color scheme.
    :param charts: the SVG of the charts by name (gruenbeck.charts.CHARTS), put in the section
        they belong to; a chart that is not there is left out
    :param notes: texts for the top of the page (e.g. that no data files are attached)
    """
    charts = charts or {}
    sections = _sections(report)
    shown = [period for section in sections for period in section.periods]
    body = [_html_heading(f"in liters, run on {report.today.isoformat()}")]
    body += [_html_paragraph(note) for note in notes]
    for section in sections:
        body.append(_html_section(section, charts))
    legend = [LEGEND_BASIS]
    if any(period.interpolated for period in shown):
        legend.insert(0, _interpolated_legend())
    body.append(
        f'<p class="gb-muted" style="margin:20px 0 0;font-size:12px;{HTML_MUTED}">'
        + "<br>".join(escape(line) for line in legend)
        + "</p>"
    )
    return _html_document("".join(body))


def format_failure_html(message: str, notes: collections.abc.Sequence[str] = ()) -> str:
    """the HTML document of a data mail whose statistics could not be calculated"""
    body = [_html_heading("statistics not available")]
    body += [_html_paragraph(note) for note in notes]
    body.append(_html_paragraph(message))
    return _html_document("".join(body))


def _html_document(body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en"><head>{HTML_HEAD}</head>\n'
        '<body class="gb-page" style="margin:0;padding:0;background:#f3f4f6;">'
        '<table role="presentation" class="gb-page" width="100%" cellpadding="0"'
        ' cellspacing="0" border="0" style="background:#f3f4f6;"><tr>'
        '<td align="center" style="padding:16px 8px;">'
        f'<table role="presentation" width="{HTML_WIDTH}" cellpadding="0" cellspacing="0"'
        f' border="0" style="width:100%;max-width:{HTML_WIDTH}px;"><tr>'
        '<td class="gb-card" style="padding:20px 16px;background:#ffffff;color:#1f2937;'
        f"font-family:{HTML_FONT};font-size:14px;line-height:1.45;border-radius:12px;"
        f'">{body}</td></tr></table></td></tr></table></body></html>\n'
    )


def _html_heading(subtitle: str) -> str:
    return (
        '<h1 style="margin:0;font-size:20px;line-height:1.3;">Water consumption</h1>'
        f'<p class="gb-muted" style="margin:2px 0 12px;font-size:13px;{HTML_MUTED}">'
        f"{escape(subtitle)}</p>"
    )


def _html_paragraph(text: str) -> str:
    """a paragraph of plain text (a line break stays one)"""
    return f'<p style="margin:8px 0;font-size:13px;">{escape(text).replace(chr(10), "<br>")}</p>'


def _html_section(section: _Section, charts: collections.abc.Mapping[str, str]) -> str:
    heading = '<h2 style="margin:24px 0 8px;font-size:16px;line-height:1.3;">'
    # a date is not broken at its hyphens on a narrow screen
    title = DATE.sub(
        lambda date: f'<span style="white-space:nowrap;">{date[0]}</span>', escape(section.title)
    )
    parts = [f"{heading}{title}</h2>"]
    parts += _html_charts(HTML_CHARTS_BEFORE.get(section.key, ()), charts)
    if section.daily is not None:
        parts.append(_html_days(section.daily))
    if section.periods:
        parts.append(_html_table(section.periods))
    if section.note:
        parts.append(
            f'<p class="gb-muted" style="margin:6px 0;font-size:12px;{HTML_MUTED}">'
            f"{escape(section.note)}</p>"
        )
    parts += _html_charts(HTML_CHARTS_AFTER.get(section.key, ()), charts)
    return "".join(parts)


def _html_charts(
    names: collections.abc.Iterable[str], charts: collections.abc.Mapping[str, str]
) -> list[str]:
    """the charts of these names that exist; the SVG is made by gruenbeck.charts"""
    return [
        f'<div style="margin:8px 0 12px;">{charts[name]}</div>' for name in names if name in charts
    ]


def _html_days(week: Period) -> str:
    heads = []
    cells = []
    for day in week.days:
        name = WEEKDAYS[day.date.weekday()]
        heads.append(
            f'<th class="gb-head gb-rule" align="center" style="{_th_style("center")}">'
            f"{name}<br>{_muted(f'{day.date:%m-%d}', weight=400)}</th>"
        )
        if day.liters is None:
            reason = "missing" if day.status is DayStatus.MISSING else "no data"
            value = f"\N{EN DASH}<br>{_muted(reason, size=11)}"
        else:
            value = f"{day.liters}{'*' if day.status is DayStatus.INTERPOLATED else ''}"
        cells.append(
            f'<td class="gb-rule" align="center" style="{_td_style("center")}">{value}</td>'
        )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="border-collapse:collapse;margin:4px 0 12px;table-layout:fixed;">'
        f"<tr>{''.join(heads)}</tr><tr>{''.join(cells)}</tr></table>"
    )


def _html_table(periods: collections.abc.Sequence[Period]) -> str:
    heads = "".join(
        f'<th class="gb-head gb-rule" align="{align}" style="{_th_style(align)}">{name}</th>'
        for name, align in TABLE_COLUMNS
    )
    rows = []
    for index, period in enumerate(periods):
        note = _incomplete_note(period)
        # the period of the run is bold; the note of an incomplete one sits right below it
        weight = "font-weight:600;" if index == 0 else ""
        rule = "" if note else HTML_RULE
        total = mean = "\N{EN DASH}"
        if period.total is not None and period.mean is not None:
            total = f"{period.total}{'*' if period.interpolated else ''}"
            mean = f"{period.mean:.0f}"
        values = [
            str(period.year),
            f"{period.start:%m-%d}{NBSP}\N{EN DASH}{NBSP}{period.end:%m-%d}",
            total,
            mean,
            _html_extreme(period.minimum),
            _html_extreme(period.maximum),
        ]
        cells = "".join(
            f'<td class="gb-rule" align="{align}" style="{_td_style(align)}{weight}{rule}">'
            f"{value}</td>"
            for (_, align), value in zip(TABLE_COLUMNS, values, strict=True)
        )
        rows.append(f"<tr>{cells}</tr>")
        if note:
            rows.append(
                f'<tr><td class="gb-rule gb-warn" colspan="{len(TABLE_COLUMNS)}"'
                f' style="padding:0 4px 6px;font-size:12px;color:#b45309;{HTML_RULE}">'
                f"{escape(note)}</td></tr>"
            )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        f' style="border-collapse:collapse;margin:4px 0;"><tr>{heads}</tr>{"".join(rows)}</table>'
    )


def _html_extreme(day: Day | None) -> str:
    if day is None or day.liters is None:
        return "\N{EN DASH}"
    return f"{day.liters} {_muted(f'{day.date:%m-%d}', size=11)}"


def _muted(text: str, size: int | None = None, weight: int | None = None) -> str:
    """text (already escaped) in the muted color"""
    style = (f"font-size:{size}px;" if size else "") + (f"font-weight:{weight};" if weight else "")
    return f'<span class="gb-muted" style="{style}{HTML_MUTED}">{text}</span>'


def _th_style(align: str) -> str:
    return (
        f"padding:6px 4px;font-size:12px;font-weight:600;text-align:{align};"
        f"background:#f9fafb;{HTML_RULE}"
    )


def _td_style(align: str) -> str:
    return f"padding:6px 4px;font-size:13px;line-height:1.3;text-align:{align};{HTML_RULE}"
