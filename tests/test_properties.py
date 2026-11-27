"""
properties that hold for every input (P009-S17)

hypothesis generates the inputs; a failing example is shrunk to a small one and printed.
Repeat a run with the seed of pytest-randomly (`--randomly-seed=<seed>`, see the header of the
pytest output). Where the property is about what the code does with *valid* data, the strategy
only makes valid data (e.g. dates of the years 2000 to 2100, the range of the data files).
"""

import datetime
import fractions
import itertools
import logging
import math
import pathlib
import tempfile
import xml.etree.ElementTree as ET

import hypothesis
import hypothesis.strategies as st

from gruenbeck import charts, config, device, report, storage

LITERS = st.integers(min_value=0, max_value=10**9)
DAYS = st.dates(min_value=datetime.date(2000, 1, 1), max_value=datetime.date(2100, 12, 31))


# --- report._between: the steps from one measured day to the next -------------------


@st.composite
def steps_between(draw: st.DrawFn) -> tuple[int, int, int, int]:
    """(before, after, step, steps) with 0 <= step <= steps and steps >= 2"""
    steps = draw(st.integers(min_value=2, max_value=report.MAX_INTERPOLATED_GAP + 1))
    return draw(LITERS), draw(LITERS), draw(st.integers(0, steps)), steps


@hypothesis.given(steps_between())
def test_between_stays_between_the_end_points(case: tuple[int, int, int, int]) -> None:
    before, after, step, steps = case

    assert min(before, after) <= report._between(before, after, step, steps) <= max(before, after)


@hypothesis.given(steps_between())
def test_between_starts_at_before_and_ends_at_after(case: tuple[int, int, int, int]) -> None:
    before, after, _, steps = case

    assert report._between(before, after, 0, steps) == before
    assert report._between(before, after, steps, steps) == after


@hypothesis.given(steps_between())
def test_between_never_turns_around(case: tuple[int, int, int, int]) -> None:
    before, after, _, steps = case
    values = [report._between(before, after, step, steps) for step in range(steps + 1)]

    if before <= after:
        assert values == sorted(values)
    else:
        assert values == sorted(values, reverse=True)


@hypothesis.given(steps_between())
def test_between_rounds_half_up_like_exact_fractions(case: tuple[int, int, int, int]) -> None:
    before, after, step, steps = case
    exact = fractions.Fraction(before * (steps - step) + after * step, steps)

    # x.5 goes up, whatever the direction of the steps
    assert report._between(before, after, step, steps) == math.floor(
        exact + fractions.Fraction(1, 2)
    )


# --- report._interpolate: the short gaps between measured days ----------------------


@st.composite
def stored_days(
    draw: st.DrawFn,
) -> tuple[dict[datetime.date, int], datetime.date, datetime.date]:
    """(measured days, first day, last day): a run of days, each measured or not"""
    first = draw(DAYS.filter(lambda day: day < datetime.date(2100, 1, 1)))
    flags = draw(st.lists(st.booleans(), min_size=1, max_size=30))
    values = draw(st.lists(LITERS, min_size=len(flags), max_size=len(flags)))
    measured = {
        first + datetime.timedelta(days=offset): value
        for offset, (flag, value) in enumerate(zip(flags, values, strict=True))
        if flag
    }
    return measured, first, first + datetime.timedelta(days=len(flags) - 1)


def neighbours(
    measured: dict[datetime.date, int],
    first: datetime.date,
    last: datetime.date,
    day: datetime.date,
) -> tuple[datetime.date | None, datetime.date | None]:
    """the nearest measured days before and after a day, searched day by day"""
    one_day = datetime.timedelta(days=1)
    before = day - one_day
    while before >= first and before not in measured:
        before -= one_day
    after = day + one_day
    while after <= last and after not in measured:
        after += one_day
    return (before if before in measured else None, after if after in measured else None)


@hypothesis.given(stored_days())
def test_interpolate_fills_exactly_the_short_gaps_between_measured_days(
    case: tuple[dict[datetime.date, int], datetime.date, datetime.date],
) -> None:
    measured, first, last = case

    interpolated = report._interpolate(measured, first, last)

    expected = set()
    for offset in range((last - first).days + 1):
        day = first + datetime.timedelta(days=offset)
        if day in measured:
            continue
        before, after = neighbours(measured, first, last, day)
        if (
            before is not None
            and after is not None
            and (after - before).days - 1 <= report.MAX_INTERPOLATED_GAP
        ):
            expected.add(day)
    assert set(interpolated) == expected


@hypothesis.given(stored_days())
def test_interpolate_leaves_the_measured_days_alone(
    case: tuple[dict[datetime.date, int], datetime.date, datetime.date],
) -> None:
    measured, first, last = case
    before = dict(measured)

    interpolated = report._interpolate(measured, first, last)

    assert measured == before
    assert not set(interpolated) & set(measured)


@hypothesis.given(stored_days())
def test_interpolated_values_lie_between_the_neighbouring_measured_values(
    case: tuple[dict[datetime.date, int], datetime.date, datetime.date],
) -> None:
    measured, first, last = case

    for day, value in report._interpolate(measured, first, last).items():
        before, after = neighbours(measured, first, last, day)
        assert before is not None
        assert after is not None
        low, high = sorted((measured[before], measured[after]))
        assert low <= value <= high


@hypothesis.given(stored_days())
def test_interpolation_ends_where_the_data_ends(
    case: tuple[dict[datetime.date, int], datetime.date, datetime.date],
) -> None:
    measured, first, last = case

    interpolated = report._interpolate(measured, first, last)

    # no value before the first or after the last measured day: nothing to interpolate from
    if measured:
        assert all(min(measured) < day < max(measured) for day in interpolated)
    else:
        assert interpolated == {}


# --- storage: write_data and read_data_file ----------------------------------------

DATE_PATTERNS = ["%Y-%m-%d", "%d.%m.%Y", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%j", "%y-%m-%d"]
# the values of the files: litres, or any text that is not made of digits only ("-", "")
TEXT_VALUES = st.text(st.characters(blacklist_categories=["Cs"])).filter(
    lambda text: not text.isdecimal()
)
VALUES = st.one_of(LITERS, TEXT_VALUES)


@st.composite
def stored_files(
    draw: st.DrawFn,
) -> tuple[str, dict[str, int | str], config.FieldNames]:
    """(date pattern, {date text: value}, column names)"""
    pattern = draw(st.sampled_from(DATE_PATTERNS))
    days = draw(st.lists(DAYS, max_size=15, unique=True))
    values = draw(st.lists(VALUES, min_size=len(days), max_size=len(days)))
    names = draw(st.sampled_from([("date", "value"), ("day", "litres"), ("Datum", "Liter")]))
    data = {day.strftime(pattern): value for day, value in zip(days, values, strict=True)}
    return pattern, data, config.FieldNames(date=names[0], value=names[1])


@hypothesis.given(stored_files())
def test_what_is_written_is_read_back_unchanged(
    case: tuple[str, dict[str, int | str], config.FieldNames],
) -> None:
    pattern, data, names = case
    # one folder per example: tmp_path would be shared by all of them
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "data.csv"

        storage.write_data(path, names, data, pattern)
        read = storage.read_data_file(path, names, pattern)

    assert read == data
    assert all(type(read[text]) is type(value) for text, value in data.items())


@hypothesis.given(stored_files())
def test_the_file_is_written_sorted_by_date(
    case: tuple[str, dict[str, int | str], config.FieldNames],
) -> None:
    pattern, data, names = case
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "data.csv"

        storage.write_data(path, names, data, pattern)
        read = storage.read_data_file(path, names, pattern)

    days = [storage.date_of(text, pattern) for text in read]
    assert days == sorted(days)


# --- device.check_device_clock -----------------------------------------------------


class _Records(logging.Handler):
    """the records of one logger, for a test that must not use the caplog fixture"""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def check_clock(device_minutes: int, local_minutes: int) -> tuple[int | None, list[str]]:
    """the deviation that check_device_clock returns and the warnings it logs"""
    now = datetime.datetime(2026, 11, 23, local_minutes // 60, local_minutes % 60)
    handler = _Records()
    logger = logging.getLogger(device.__name__)
    logger.addHandler(handler)
    try:
        deviation = device.check_device_clock(
            f"{device_minutes // 60:02d}:{device_minutes % 60:02d}", now
        )
    finally:
        logger.removeHandler(handler)
    return deviation, [record.getMessage() for record in handler.records]


MINUTES = st.integers(min_value=0, max_value=device.MINUTES_PER_DAY - 1)


@hypothesis.given(MINUTES, MINUTES)
def test_clock_deviation_is_the_shortest_way_round_the_clock(
    device_minutes: int, local_minutes: int
) -> None:
    deviation, _ = check_clock(device_minutes, local_minutes)

    assert deviation is not None
    # within (-12 h, +12 h]: exactly 12 h is +12 h
    assert -device.MINUTES_PER_DAY // 2 < deviation <= device.MINUTES_PER_DAY // 2
    # the same time of the day after the deviation is added to the local time
    assert (local_minutes + deviation) % device.MINUTES_PER_DAY == device_minutes


# every deviation of (-12 h, +12 h]; the edges (the tolerance and half a day) are drawn
# often, because two random times of the day are almost never exactly 15 minutes or 12 h apart
EDGES = [-719, -16, -15, -14, -1, 0, 1, 14, 15, 16, 719, 720]
DEVIATIONS = st.one_of(st.integers(min_value=-719, max_value=720), st.sampled_from(EDGES))


@hypothesis.given(MINUTES, DEVIATIONS)
def test_clock_that_is_off_by_a_known_amount_gives_that_deviation(
    local_minutes: int, off: int
) -> None:
    deviation, _ = check_clock((local_minutes + off) % device.MINUTES_PER_DAY, local_minutes)

    # also across midnight; exactly half a day is +12 h, never -12 h
    assert deviation == off


@hypothesis.given(MINUTES, DEVIATIONS)
def test_clock_warns_exactly_when_the_deviation_exceeds_the_tolerance(
    local_minutes: int, off: int
) -> None:
    _, warnings = check_clock((local_minutes + off) % device.MINUTES_PER_DAY, local_minutes)

    # 15 minutes off is still fine, 16 is not; one warning at most
    assert len(warnings) == (1 if abs(off) > device.CLOCK_TOLERANCE_MINUTES else 0)


# --- charts.nice_ticks ---------------------------------------------------------------


@hypothesis.given(st.integers(min_value=-10, max_value=10**12))
def test_ticks_start_at_zero_and_go_up_by_equal_steps(maximum: int) -> None:
    ticks = charts.nice_ticks(maximum)

    assert ticks[0] == 0
    steps = {later - earlier for earlier, later in itertools.pairwise(ticks)}
    assert len(steps) == 1
    assert steps.pop() > 0


@hypothesis.given(st.integers(min_value=-10, max_value=10**12))
def test_ticks_cover_the_maximum_without_a_needless_step(maximum: int) -> None:
    ticks = charts.nice_ticks(maximum)
    step = ticks[1] - ticks[0]

    assert ticks[-1] >= max(maximum, 1)
    # the last tick is the first multiple of the step that covers the maximum
    assert ticks[-1] - step < max(maximum, 1)


@hypothesis.given(st.integers(min_value=-10, max_value=10**12))
def test_ticks_have_at_most_the_allowed_intervals(maximum: int) -> None:
    ticks = charts.nice_ticks(maximum)

    assert 1 <= len(ticks) - 1 <= charts.MAX_TICK_INTERVALS


@hypothesis.given(st.integers(min_value=-10, max_value=10**12))
def test_tick_step_is_1_2_or_5_times_a_power_of_10(maximum: int) -> None:
    ticks = charts.nice_ticks(maximum)
    step = ticks[1] - ticks[0]

    assert str(step).rstrip("0") in {"1", "2", "5"}


# --- charts.as_image: a chart as image ----------------------------------------------


@st.composite
def reports(draw: st.DrawFn) -> report.Report:
    """
    the report of a run on any day: runs of days with the same value or without a row (at most
    2000 days, so the data start in 2000 at the earliest)
    """
    today = draw(st.dates(datetime.date(2006, 1, 1), datetime.date(2100, 12, 31)))
    runs = draw(
        st.lists(st.tuples(st.integers(1, 200), st.none() | LITERS), min_size=1, max_size=10)
    )
    day = today - datetime.timedelta(days=sum(length for length, _ in runs))
    stored: dict[datetime.date, int | str] = {}
    for length, liters in runs:
        for _ in range(length):
            if liters is not None:
                stored[day] = liters
            day += datetime.timedelta(days=1)
    return report.compute_report(stored, today)


def svg_elements(svg: str) -> list[tuple[str, dict[str, str], str | None, str | None]]:
    """every element below the root of an SVG text: tag, attributes, text and tail"""
    root = ET.fromstring(svg)
    return [
        (element.tag, dict(element.attrib), element.text, element.tail)
        for element in root.iter()
        if element is not root
    ]


@hypothesis.given(reports())
def test_image_of_every_chart_is_the_chart_with_a_size_and_a_style(stats: report.Report) -> None:
    for chart in charts.CHARTS.values():
        svg = chart(stats)

        image = charts.as_image(svg)

        root = ET.fromstring(image)
        _, _, width, height = root.get("viewBox", "").split()
        assert (root.get("width"), root.get("height")) == (width, height)
        assert "style" not in root.attrib
        assert "%" not in "".join(v for element in root.iter() for v in element.attrib.values())
        assert list(root.iter(f"{{{charts.SVG_NAMESPACE}}}style")) == [root[0]]
        assert root[0].text == charts.IMAGE_STYLE
        assert svg_elements(image)[1:] == svg_elements(svg)
        # the same chart gives the same image
        assert charts.as_image(svg) == image
