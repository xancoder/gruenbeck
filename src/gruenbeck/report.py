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
