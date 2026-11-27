"""
the four charts of the data mail as SVG text, made from the statistics of gruenbeck.report

- week_chart: the liters of every day of the last week (bars Monday to Sunday)
- monthly_chart: the liters per month, the current year next to up to 3 earlier years
- cumulative_chart: the liters since 1 January for the same years (a line per year)
- weekly_chart: the liters per calendar week of the last 52 weeks (line with points)

Every function takes the Report and returns one `<svg>` element as text, to be put into an
HTML page or mail as it is. Only the standard library is used (xml.etree.ElementTree builds
and escapes the markup). A chart has no script, style sheet, external font or image:

- `viewBox` and `width="100%"`, so it scales down to the width of the page (`max-width`
  640 px); every chart has a `<title>` and a `<desc>` that lists its values as text
- text, grid and axes are drawn in `currentColor`, so they follow the text color of the
  page and stay readable on a light and on a dark background; only the series use fixed
  colors (YEAR_COLORS: the current year strong, the earlier years muted), the same color for
  a year in every chart
- marks: a value made by interpolation is light (bars) or a ring (lines) and has a `*`, a
  missing day is a gap with a dash, an incomplete month is only an outline, an incomplete
  week a hollow point

as_image() makes the SVG of a chart a document of its own, as an `<img>` needs it (a mail
program that removes inline SVG may still show an image): a fixed width and height instead of
`width="100%"`, and a `<style>` with the text color, light and for a dark color scheme
(IMAGE_TEXT_COLOR, IMAGE_TEXT_COLOR_DARK), because an image does not inherit the text color
of the page. Only the image has a `<style>`; everything else stays as in the chart.

The class names (`gb-chart`, `gb-bar`, `gb-interpolated`, `gb-incomplete`, ...) are for tests
and for styling by the page; the charts look right without any style.
"""

import collections.abc
import dataclasses
import datetime
import math
import xml.etree.ElementTree as ET

from gruenbeck import report

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
WIDTH = 480
MAX_DISPLAY_WIDTH = 640
FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
# Colors of the years, the current year first. Each has a contrast of at least 3:1 to white
# and to near black (tests/test_charts.py), so the series are visible on both backgrounds.
YEAR_COLORS = ("#2563eb", "#c27a2c", "#4f9d92", "#9575b8")
# The text color (currentColor) of a chart as image: the colors of the text of the card of the
# HTML mail (gruenbeck.report_html), light and for a dark color scheme.
IMAGE_TEXT_COLOR = "#1f2937"
IMAGE_TEXT_COLOR_DARK = "#e5e7eb"
IMAGE_STYLE = (
    f"svg {{ color: {IMAGE_TEXT_COLOR}; }}"
    f" @media (prefers-color-scheme: dark) {{ svg {{ color: {IMAGE_TEXT_COLOR_DARK}; }} }}"
)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# a year without a leap day: the position of the months on the axis of the year
MONTH_STARTS = tuple(
    datetime.date(2001, month, 1).timetuple().tm_yday - 1 for month in range(1, 13)
)
MAX_TICK_INTERVALS = 5
# the mark of a day without a value
DASH = "\N{EN DASH}"

MARGIN = 14.0
TITLE_Y = 20.0
PLOT_TOP = 54.0
PLOT_HEIGHT = 168.0
LEGEND_ROW_HEIGHT = 17.0


def year_colors(years: collections.abc.Iterable[int]) -> dict[int, str]:
    """the color of every year: the latest year gets the first color of YEAR_COLORS, ..."""
    ranked = sorted(set(years), reverse=True)
    return {year: YEAR_COLORS[rank % len(YEAR_COLORS)] for rank, year in enumerate(ranked)}


def week_chart(stats: report.Report) -> str:
    """the liters of every day of the last complete week"""
    week = stats.week.current
    iso_year, iso_week, _ = week.start.isocalendar()
    values = [day.liters for day in week.days]
    plot = _plot(max((value for value in values if value is not None), default=None))
    color = YEAR_COLORS[0]
    legend = _Legend(
        [
            _LegendItem("measured", "bar", color),
            _LegendItem("interpolated *", "bar-light", color),
            _LegendItem("missing", "mark", symbol=DASH),
        ]
    )
    title = f"Daily consumption, week {iso_week}/{iso_year}"
    parts = []
    for day in week.days:
        name = report.WEEKDAYS[day.date.weekday()]
        if day.liters is None:
            parts.append(f"{name} {day.status.value}")
        else:
            mark = " (interpolated)" if day.status is report.DayStatus.INTERPOLATED else ""
            parts.append(f"{name} {day.liters}{mark}")
    description = (
        f"Liters per day from {week.start.isoformat()} to {week.end.isoformat()}: "
        + ", ".join(parts)
        + "."
    )
    canvas = _Canvas("gb-week", plot.bottom + 44 + legend.height, title, description)
    canvas.title(title)
    _draw_axis(canvas, plot)

    column = (plot.right - plot.left) / len(week.days)
    bar_width = min(column * 0.62, 38.0)
    # long values (7 digits and more) get a smaller font, so the labels do not touch
    longest = max((len(f"{value}*") for value in values if value is not None), default=1)
    value_size = min(11.0, column * 0.92 / (0.58 * longest))
    bars = canvas.group("gb-bars")
    labels = canvas.group("gb-labels")
    for index, day in enumerate(week.days):
        center = plot.left + (index + 0.5) * column
        canvas.text(
            labels,
            center,
            plot.bottom + 15,
            report.WEEKDAYS[day.date.weekday()],
            cls="gb-day",
        )
        canvas.text(
            labels,
            center,
            plot.bottom + 28,
            f"{day.date:%m-%d}",
            size=9.5,
            opacity=0.65,
            cls="gb-date",
        )
        if day.liters is None:
            canvas.text(
                bars,
                center,
                plot.bottom - 7,
                DASH,
                size=15,
                opacity=0.6,
                cls=f"gb-missing gb-{day.status.name.lower().replace('_', '-')}",
            )
            continue
        interpolated = day.status is report.DayStatus.INTERPOLATED
        top = plot.y(day.liters)
        if day.liters > 0:
            _bar(
                canvas,
                bars,
                center - bar_width / 2,
                bar_width,
                top,
                plot.bottom,
                color,
                "gb-bar gb-interpolated" if interpolated else "gb-bar",
                light=interpolated,
            )
        canvas.text(
            labels,
            center,
            top - 5,
            f"{day.liters}{'*' if interpolated else ''}",
            size=value_size,
            cls="gb-value",
        )
    legend.draw(canvas, plot.bottom + 44)
    return canvas.render()


def monthly_chart(stats: report.Report) -> str:
    """the liters per month for the current year and up to 3 earlier years"""
    colors = year_colors(series.year for series in stats.monthly)
    totals = [
        month.total
        for series in stats.monthly
        for month in series.months
        if month.total is not None
    ]
    plot = _plot(max(totals, default=None))
    legend = _Legend(
        [_LegendItem(str(series.year), "bar", colors[series.year]) for series in stats.monthly]
        + [
            _LegendItem("outline: incomplete month", "bar-outline", "currentColor"),
            _LegendItem("interpolated days", "mark", symbol="*"),
        ]
    )
    title = "Monthly consumption by year"
    description = "Liters per month. " + " ".join(
        f"{series.year}: "
        + ", ".join(
            f"{MONTHS[number]} "
            + ("-" if month.total is None else f"{month.total}{_period_note(month)}")
            for number, month in enumerate(series.months)
        )
        + "."
        for series in stats.monthly
    )
    canvas = _Canvas("gb-monthly", plot.bottom + 34 + legend.height, title, description)
    canvas.title(title)
    _draw_axis(canvas, plot)

    group = (plot.right - plot.left) / 12
    count = len(stats.monthly)
    gap = 1.5
    inner = group * 0.8
    bar_width = (inner - (count - 1) * gap) / count
    bars = canvas.group("gb-bars")
    labels = canvas.group("gb-labels")
    for number in range(12):
        start = plot.left + number * group
        canvas.text(labels, start + group / 2, plot.bottom + 15, MONTHS[number], cls="gb-month")
        for position, series in enumerate(stats.monthly):
            month = series.months[number]
            if month.total is None:
                continue
            x = start + (group - inner) / 2 + position * (bar_width + gap)
            top = plot.y(month.total)
            color = colors[series.year]
            classes = "gb-bar" + ("" if month.complete else " gb-incomplete")
            if month.interpolated:
                classes += " gb-interpolated"
            _bar(
                canvas,
                bars,
                x,
                bar_width,
                top,
                plot.bottom,
                color,
                classes,
                outline=not month.complete,
            )
            if month.interpolated:
                canvas.text(
                    labels, x + bar_width / 2, top - 3, "*", color=color, size=12, cls="gb-mark"
                )
    legend.draw(canvas, plot.bottom + 34)
    return canvas.render()


def cumulative_chart(stats: report.Report) -> str:
    """the liters since 1 January for the current year and up to 3 earlier years"""
    colors = year_colors(series.year for series in stats.cumulative)
    plot = _plot(
        max(
            (
                point.cumulative
                for series in stats.cumulative
                for point in series.points
                if point.cumulative is not None
            ),
            default=None,
        )
    )
    items = [
        _LegendItem(str(series.year), "line", colors[series.year]) for series in stats.cumulative
    ]
    items += [
        _LegendItem("interpolated day", "dot-hollow", "currentColor"),
        _LegendItem("run day", "dash", "currentColor"),
    ]
    # the line breaks at a missing day and goes on lower: the liters are not made up
    has_gap = any(
        point.status is report.DayStatus.MISSING
        for series in stats.cumulative
        for point in series.points
    )
    if has_gap:
        items.append(_LegendItem("missing days (not added)", "line-gap", "currentColor"))
    legend = _Legend(items)
    title = "Cumulative consumption since 1 January"
    description = (
        "Liters since 1 January up to the end of each day. A missing day breaks the line;"
        " its liters are not added. "
        + " ".join(_cumulative_description(series) for series in stats.cumulative)
    )
    description += f" The day of the run is {stats.today.isoformat()}."
    canvas = _Canvas("gb-cumulative", plot.bottom + 34 + legend.height, title, description)
    canvas.title(title)
    _draw_axis(canvas, plot)

    def x_of(day: datetime.date) -> float:
        index = (day - datetime.date(day.year, 1, 1)).days
        return plot.left + min(index, 365) / 365 * (plot.right - plot.left)

    labels = canvas.group("gb-labels")
    ticks = canvas.group("gb-ticks")
    for number, start in enumerate(MONTH_STARTS):
        x = plot.left + start / 365 * (plot.right - plot.left)
        end = MONTH_STARTS[number + 1] if number < 11 else 365
        middle = plot.left + (start + end) / 2 / 365 * (plot.right - plot.left)
        canvas.el(
            ticks,
            "line",
            x1=x,
            x2=x,
            y1=plot.bottom,
            y2=plot.bottom + 4,
            stroke="currentColor",
            stroke_opacity=0.35,
        )
        canvas.text(labels, middle, plot.bottom + 17, MONTHS[number], cls="gb-month")

    # the run day: a dashed line through the plot, over the lines of the years
    run_x = x_of(stats.today)
    lines = canvas.group("gb-lines")
    for series in stats.cumulative:
        color = colors[series.year]
        group = canvas.group(f"gb-line gb-year-{series.year}", parent=lines)
        segment: list[tuple[float, float]] = []
        segments = [segment]
        for point in series.points:
            if point.cumulative is None:
                if segment:
                    segment = []
                    segments.append(segment)
                continue
            segment.append((x_of(point.date), plot.y(point.cumulative)))
            if point.status is report.DayStatus.INTERPOLATED:
                canvas.el(
                    group,
                    "circle",
                    cls="gb-interpolated",
                    cx=segment[-1][0],
                    cy=segment[-1][1],
                    r=2.4,
                    fill="none",
                    stroke=color,
                    stroke_width=1.2,
                )
        for segment in segments:
            _draw_segment(canvas, group, segment, color)
        known = [(p.date, p.cumulative) for p in series.points if p.cumulative is not None]
        if series.year == stats.today.year and known:
            canvas.el(
                group,
                "circle",
                cls="gb-end",
                cx=x_of(known[-1][0]),
                cy=plot.y(known[-1][1]),
                r=3.2,
                fill=color,
            )
    canvas.el(
        lines,
        "line",
        cls="gb-run-day",
        x1=run_x,
        x2=run_x,
        y1=plot.top - 6,
        y2=plot.bottom,
        stroke="currentColor",
        stroke_opacity=0.55,
        stroke_width=1,
        stroke_dasharray="3 3",
    )
    canvas.text(
        labels,
        run_x,
        plot.top - 10,
        "run day",
        anchor="end" if run_x > plot.right - 40 else "middle",
        size=9.5,
        opacity=0.7,
        cls="gb-run-label",
    )
    legend.draw(canvas, plot.bottom + 34)
    return canvas.render()


def weekly_chart(stats: report.Report) -> str:
    """the liters per calendar week of the last 52 complete weeks"""
    weeks = stats.weekly
    plot = _plot(max((week.total for week in weeks if week.total is not None), default=None))
    color = YEAR_COLORS[0]
    legend = _Legend(
        [
            _LegendItem("complete week", "dot", color),
            _LegendItem("incomplete week", "dot-hollow", color),
            _LegendItem("interpolated days", "mark", symbol="*"),
        ]
    )
    title = f"Weekly consumption, last {len(weeks)} weeks"
    description = "Liters per calendar week, oldest week first. " + ", ".join(
        f"{week.start:%m-%d} "
        + ("-" if week.total is None else f"{week.total}{_period_note(week)}")
        for week in weeks
    )
    description += "."
    canvas = _Canvas("gb-weekly", plot.bottom + 34 + legend.height, title, description)
    canvas.title(title)
    _draw_axis(canvas, plot)

    column = (plot.right - plot.left) / max(len(weeks), 1)

    def x_of(index: int) -> float:
        return plot.left + (index + 0.5) * column

    labels = canvas.group("gb-labels")
    changes = [
        index
        for index, week in enumerate(weeks)
        if index > 0 and week.start.month != weeks[index - 1].start.month
    ]
    # the first week is labelled too, if the label of the next month is not too close
    shown = ([0] if not changes or changes[0] >= 5 else []) + changes
    for index in shown:
        start = weeks[index].start
        text = MONTHS[start.month - 1]
        if index == shown[0] or start.month == 1:
            text += f" {start:%y}"
        canvas.text(labels, x_of(index), plot.bottom + 15, text, size=10, cls="gb-month")
        canvas.el(
            labels,
            "line",
            x1=x_of(index),
            x2=x_of(index),
            y1=plot.bottom,
            y2=plot.bottom + 4,
            stroke="currentColor",
            stroke_opacity=0.35,
        )

    line = canvas.group("gb-line")
    segment: list[tuple[float, float]] = []
    segments = [segment]
    for index, week in enumerate(weeks):
        if week.total is None:
            if segment:
                segment = []
                segments.append(segment)
            continue
        segment.append((x_of(index), plot.y(week.total)))
    for segment in segments:
        _draw_segment(canvas, line, segment, color)
    points = canvas.group("gb-points")
    last_index = max((i for i, week in enumerate(weeks) if week.total is not None), default=None)
    for index, week in enumerate(weeks):
        if week.total is None:
            continue
        x, y = x_of(index), plot.y(week.total)
        if week.complete:
            canvas.el(points, "circle", cls="gb-point", cx=x, cy=y, r=3, fill=color)
        else:
            canvas.el(
                points,
                "circle",
                cls="gb-point gb-incomplete",
                cx=x,
                cy=y,
                r=3,
                fill="none",
                stroke=color,
                stroke_width=1.5,
            )
        if week.interpolated:
            canvas.text(points, x, y - 6, "*", color=color, size=12, cls="gb-mark")
        if index == last_index:
            canvas.text(
                points,
                x,
                y - (14 if week.interpolated else 8),
                str(week.total),
                anchor="end" if x > plot.right - 20 else "middle",
                cls="gb-value",
            )
    legend.draw(canvas, plot.bottom + 34)
    return canvas.render()


CHARTS: dict[str, collections.abc.Callable[[report.Report], str]] = {
    "week": week_chart,
    "monthly": monthly_chart,
    "cumulative": cumulative_chart,
    "weekly": weekly_chart,
}


def as_image(svg: str) -> str:
    """
    the SVG text of a chart as a document of its own for an `<img>`

    The width and the height are the ones of the `viewBox` (whole pixels, rounded up), the
    `style` attribute (`max-width`) is left out: the `<img>` scales the image. A `<style>` as
    the first child sets the text color, light and for a dark color scheme. All the rest
    (title, description, classes, elements, texts) is the one of the chart.
    :raises ValueError: the text is not an `<svg>` element with a `viewBox` of 4 numbers
    :raises xml.etree.ElementTree.ParseError: the text is not XML
    """
    namespace = f"{{{SVG_NAMESPACE}}}"
    root = ET.fromstring(svg)
    if root.tag != f"{namespace}svg":
        raise ValueError(f"not an SVG element: {root.tag}")
    try:
        _, _, width, height = (float(number) for number in root.get("viewBox", "").split())
    except ValueError:
        raise ValueError(f"no viewBox of 4 numbers: {root.get('viewBox')!r}") from None
    # the tags without the namespace and `xmlns` as the first attribute, as _Canvas makes them
    # (ElementTree cannot write a default namespace with attributes that have none)
    for element in root.iter():
        element.tag = element.tag.removeprefix(namespace)
    attributes = {"xmlns": SVG_NAMESPACE, **root.attrib}
    attributes["width"] = str(math.ceil(width))
    attributes["height"] = str(math.ceil(height))
    attributes.pop("style", None)
    root.attrib.clear()
    root.attrib.update(attributes)
    style = ET.Element("style")
    style.text = IMAGE_STYLE
    root.insert(0, style)
    return ET.tostring(root, encoding="unicode")


def _period_note(period: report.Period) -> str:
    notes = []
    if period.interpolated:
        notes.append("interpolated")
    if not period.complete:
        notes.append("incomplete")
    return f" ({', '.join(notes)})" if notes else ""


def _cumulative_description(series: report.YearCumulative) -> str:
    known = [point for point in series.points if point.cumulative is not None]
    if not known:
        return f"{series.year}: no values."
    last = known[-1]
    gaps = sum(1 for point in series.points if point.status is report.DayStatus.MISSING)
    text = f"{series.year}: {last.cumulative} liters on {last.date.isoformat()}"
    return text + (f", {gaps} days missing." if gaps else ".")


def nice_ticks(maximum: int) -> tuple[int, ...]:
    """
    the ticks of the axis of liters: 0 and round steps (1, 2, 5 times a power of 10) up to
    the first one that is not less than the maximum, at most MAX_TICK_INTERVALS intervals
    """
    maximum = max(maximum, 1)
    exponent = 0
    while True:
        for factor in (1, 2, 5):
            step = factor * 10**exponent
            if math.ceil(maximum / step) <= MAX_TICK_INTERVALS:
                return tuple(range(0, math.ceil(maximum / step) * step + 1, step))
        exponent += 1


@dataclasses.dataclass(frozen=True)
class _Plot:
    """the area of the bars and lines and the axis of liters"""

    left: float
    right: float
    top: float
    bottom: float
    ticks: tuple[int, ...]

    def y(self, liters: float) -> float:
        """vertical position of a value; the top tick is the top of the plot"""
        return self.bottom - liters / self.ticks[-1] * (self.bottom - self.top)


def _plot(maximum: int | None) -> _Plot:
    """a plot whose axis reaches the maximum (None: no value at all, an empty axis)"""
    ticks = nice_ticks(100 if maximum is None else maximum)
    label_width = max(len(str(tick)) for tick in ticks) * 6.3
    return _Plot(
        left=round(MARGIN + label_width + 8, 1),
        right=WIDTH - MARGIN,
        top=PLOT_TOP,
        bottom=PLOT_TOP + PLOT_HEIGHT,
        ticks=ticks,
    )


def _draw_axis(canvas: "_Canvas", plot: _Plot) -> None:
    grid = canvas.group("gb-grid")
    for tick in plot.ticks:
        y = plot.y(tick)
        canvas.el(
            grid,
            "line",
            x1=plot.left,
            x2=plot.right,
            y1=y,
            y2=y,
            stroke="currentColor",
            stroke_opacity=0.4 if tick == 0 else 0.14,
            stroke_width=1,
        )
        canvas.text(
            grid, plot.left - 6, y + 3.5, str(tick), anchor="end", opacity=0.7, cls="gb-tick"
        )
    canvas.text(
        canvas.root, WIDTH - MARGIN, TITLE_Y, "liters", anchor="end", opacity=0.7, cls="gb-unit"
    )


def _bar(
    canvas: "_Canvas",
    parent: ET.Element,
    x: float,
    width: float,
    top: float,
    bottom: float,
    color: str,
    classes: str,
    light: bool = False,
    outline: bool = False,
) -> None:
    """a bar with rounded top corners; light is interpolated, outline is incomplete"""
    height = max(bottom - top, 1.0)
    top = bottom - height
    radius = min(3.0, width / 2, height)
    path = (
        f"M{_n(x)},{_n(bottom)} V{_n(top + radius)} Q{_n(x)},{_n(top)} {_n(x + radius)},{_n(top)}"
        f" H{_n(x + width - radius)} Q{_n(x + width)},{_n(top)} {_n(x + width)},{_n(top + radius)}"
        f" V{_n(bottom)} Z"
    )
    if outline:
        canvas.el(
            parent,
            "path",
            cls=classes,
            d=path,
            fill=color,
            fill_opacity=0.12,
            stroke=color,
            stroke_width=1.3,
        )
    elif light:
        canvas.el(
            parent,
            "path",
            cls=classes,
            d=path,
            fill=color,
            fill_opacity=0.4,
            stroke=color,
            stroke_width=1,
            stroke_dasharray="3 2",
        )
    else:
        canvas.el(parent, "path", cls=classes, d=path, fill=color)


def _draw_segment(
    canvas: "_Canvas", parent: ET.Element, segment: list[tuple[float, float]], color: str
) -> None:
    """a line through the points, or a dot for a single point (nothing for none)"""
    if len(segment) == 1:
        canvas.el(
            parent, "circle", cls="gb-dot", cx=segment[0][0], cy=segment[0][1], r=1.8, fill=color
        )
    elif segment:
        canvas.el(
            parent,
            "polyline",
            points=" ".join(f"{_n(x)},{_n(y)}" for x, y in segment),
            fill="none",
            stroke=color,
            stroke_width=1.8,
            stroke_linejoin="round",
            stroke_linecap="round",
        )


@dataclasses.dataclass(frozen=True)
class _LegendItem:
    """kind: bar, bar-light, bar-outline, line, line-gap, dot, dot-hollow, dash or mark"""

    label: str
    kind: str
    color: str = "currentColor"
    symbol: str = ""


class _Legend:
    """the items in rows below the chart, as many rows as the width needs"""

    def __init__(self, items: list[_LegendItem]):
        self.rows: list[list[tuple[_LegendItem, float]]] = [[]]
        x = MARGIN
        for item in items:
            width = 18 + len(item.label) * 5.9
            if x + width > WIDTH - MARGIN and self.rows[-1]:
                self.rows.append([])
                x = MARGIN
            self.rows[-1].append((item, x))
            x += width + 12

    @property
    def height(self) -> float:
        return len(self.rows) * LEGEND_ROW_HEIGHT

    def draw(self, canvas: "_Canvas", top: float) -> None:
        group = canvas.group("gb-legend")
        for number, row in enumerate(self.rows):
            y = top + number * LEGEND_ROW_HEIGHT
            for item, x in row:
                self._swatch(canvas, group, item, x, y)
                canvas.text(group, x + 16, y + 4, item.label, anchor="start", size=10.5)

    @staticmethod
    def _swatch(
        canvas: "_Canvas", parent: ET.Element, item: _LegendItem, x: float, y: float
    ) -> None:
        color = item.color
        if item.kind == "bar":
            canvas.el(parent, "rect", x=x, y=y - 5, width=10, height=10, rx=2.5, fill=color)
        elif item.kind == "bar-light":
            canvas.el(
                parent,
                "rect",
                x=x,
                y=y - 5,
                width=10,
                height=10,
                rx=2.5,
                fill=color,
                fill_opacity=0.4,
                stroke=color,
                stroke_dasharray="3 2",
            )
        elif item.kind == "bar-outline":
            canvas.el(
                parent,
                "rect",
                x=x,
                y=y - 5,
                width=10,
                height=10,
                rx=2.5,
                fill="none",
                stroke=color,
                stroke_width=1.3,
                stroke_opacity=0.8,
            )
        elif item.kind == "line":
            canvas.el(
                parent,
                "line",
                x1=x,
                x2=x + 11,
                y1=y,
                y2=y,
                stroke=color,
                stroke_width=2.4,
                stroke_linecap="round",
            )
        elif item.kind == "dot":
            canvas.el(parent, "circle", cx=x + 5, cy=y, r=3.4, fill=color)
        elif item.kind == "dot-hollow":
            canvas.el(
                parent, "circle", cx=x + 5, cy=y, r=3.2, fill="none", stroke=color, stroke_width=1.5
            )
        elif item.kind == "line-gap":
            for start, end in ((0, 4), (7, 11)):
                canvas.el(
                    parent,
                    "line",
                    x1=x + start,
                    x2=x + end,
                    y1=y,
                    y2=y,
                    stroke=color,
                    stroke_width=2.4,
                    stroke_linecap="round",
                )
        elif item.kind == "dash":
            canvas.el(
                parent,
                "line",
                x1=x + 5,
                x2=x + 5,
                y1=y - 6,
                y2=y + 6,
                stroke=color,
                stroke_opacity=0.7,
                stroke_dasharray="3 2",
            )
        else:
            canvas.text(parent, x + 5, y + 4.5, item.symbol, size=13, opacity=0.8)


class _Canvas:
    """the `<svg>` element of a chart with its title and description"""

    def __init__(self, chart_id: str, height: float, title: str, description: str):
        self.chart_id = chart_id
        self.root = ET.Element(
            "svg",
            {
                "xmlns": SVG_NAMESPACE,
                "class": f"gb-chart {chart_id}",
                "viewBox": f"0 0 {WIDTH} {_n(math.ceil(height))}",
                "width": "100%",
                "style": f"max-width:{MAX_DISPLAY_WIDTH}px;height:auto",
                "role": "img",
                "aria-labelledby": f"{chart_id}-title {chart_id}-desc",
                "font-family": FONT_FAMILY,
                "font-size": "11",
            },
        )
        self.el(self.root, "title", id=f"{chart_id}-title").text = title
        self.el(self.root, "desc", id=f"{chart_id}-desc").text = description

    def el(self, parent: ET.Element, tag: str, **attributes: float | str) -> ET.Element:
        """a child element; `cls` is the class, an underscore in a name is a hyphen"""
        return ET.SubElement(
            parent,
            tag,
            {
                "class" if name == "cls" else name.replace("_", "-"): _value(value)
                for name, value in attributes.items()
            },
        )

    def group(self, classes: str, parent: ET.Element | None = None) -> ET.Element:
        return self.el(self.root if parent is None else parent, "g", cls=classes)

    def text(
        self,
        parent: ET.Element,
        x: float,
        y: float,
        content: str,
        anchor: str = "middle",
        size: float | None = None,
        opacity: float | None = None,
        color: str = "currentColor",
        cls: str = "",
    ) -> ET.Element:
        attributes: dict[str, float | str] = {"x": x, "y": y, "text-anchor": anchor, "fill": color}
        if size is not None:
            attributes["font-size"] = size
        if opacity is not None:
            attributes["fill-opacity"] = opacity
        if cls:
            attributes["cls"] = cls
        element = self.el(parent, "text", **attributes)
        element.text = content
        return element

    def title(self, content: str) -> None:
        """the visible heading of the chart"""
        self.text(self.root, MARGIN, TITLE_Y, content, anchor="start", size=13, cls="gb-title").set(
            "font-weight", "600"
        )

    def render(self) -> str:
        return ET.tostring(self.root, encoding="unicode")


def _n(value: float, digits: int = 1) -> str:
    """a number with at most `digits` decimals and no trailing zeros"""
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _value(value: float | str) -> str:
    """the value of an attribute: a text as it is, a number with up to 2 decimals (opacity)"""
    return value if isinstance(value, str) else _n(value, 2)
