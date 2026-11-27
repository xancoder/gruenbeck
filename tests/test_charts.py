"""charts: the four SVG charts of the data mail"""

import datetime
import itertools
import re
import xml.etree.ElementTree as ET

import pytest

from gruenbeck import charts, report, report_html

D = datetime.date
Stored = dict[datetime.date, int | str]

SVG = "{http://www.w3.org/2000/svg}"
MONDAY = D(2026, 11, 23)
WEEK_START = D(2026, 11, 16)
DASH = "\N{EN DASH}"
CHART_NAMES = ("week", "monthly", "cumulative", "weekly")


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


def complete_data() -> Stored:
    """2022 to the day before the run, a different value for every year"""
    return {
        **fill(D(2022, 1, 1), D(2022, 12, 31), 100),
        **fill(D(2023, 1, 1), D(2023, 12, 31), 110),
        **fill(D(2024, 1, 1), D(2024, 12, 31), 120),
        **fill(D(2025, 1, 1), D(2025, 12, 31), 130),
        **fill(D(2026, 1, 1), D(2026, 11, 15), 140),
        **stored_days(WEEK_START, 100, 200, 150, 120, 300, 90, 140),
    }


def stats_of(stored: Stored, today: datetime.date = MONDAY) -> report.Report:
    return report.compute_report(stored, today)


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def find(root: ET.Element, css: str) -> list[ET.Element]:
    """the elements with a tag and a class, e.g. `path.gb-bar` (`*` for any tag)"""
    tag, _, name = css.partition(".")
    return [
        element
        for element in root.iter()
        if (tag == "*" or element.tag == SVG + tag)
        and (not name or name in element.get("class", "").split())
    ]


def texts(root: ET.Element, css: str) -> list[str]:
    return [element.text or "" for element in find(root, css)]


def legend(root: ET.Element) -> list[str]:
    """the labels of the legend (and the symbols of its marks)"""
    (group,) = find(root, "g.gb-legend")
    return [element.text or "" for element in group.iter(SVG + "text")]


def grid_lines(root: ET.Element) -> list[ET.Element]:
    (group,) = find(root, "g.gb-grid")
    return list(group.iter(SVG + "line"))


def bar_height(path: ET.Element) -> float:
    """the height of a bar: from the bottom of its path to the control point at the top"""
    points = re.findall(r"[MQ](-?[\d.]+),(-?[\d.]+)", path.get("d", ""))
    return float(points[0][1]) - float(points[1][1])


def bar_x(path: ET.Element) -> float:
    return float(re.match(r"M(-?[\d.]+),", path.get("d", "")).group(1))  # type: ignore[union-attr]


def contrast(first: str, second: str) -> float:
    """the contrast ratio of two colors #rrggbb (WCAG 2)"""

    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        red, green, blue = (
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
        )
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def with_gaps() -> Stored:
    stored = complete_data()
    # one day interpolated in the week, 6 days missing in October, the end of the data
    for day in (D(2026, 11, 19), *[D(2026, 10, n) for n in range(10, 16)], D(2026, 11, 22)):
        del stored[day]
    return stored


def build(name: str, stats: report.Report) -> str:
    return charts.CHARTS[name](stats)


# --- every chart -----------------------------------------------------------------------------

DATASETS = {
    "complete": complete_data(),
    "with-gaps": with_gaps(),
    "one-year": fill(D(2026, 1, 1), D(2026, 11, 22), 150),
    "nothing": {},
    "tiny": fill(D(2025, 6, 1), D(2026, 11, 22), 2),
    "huge": fill(D(2024, 6, 1), D(2026, 11, 22), 123_456_789),
}


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_chart_is_valid_svg_with_title_and_description(name: str, dataset: str) -> None:
    svg = build(name, stats_of(DATASETS[dataset]))

    root = parse(svg)
    assert root.tag == SVG + "svg"
    assert re.fullmatch(r"0 0 480 \d+", root.get("viewBox", ""))
    assert root.get("width") == "100%"
    assert "max-width:640px" in root.get("style", "")
    assert root.get("role") == "img"
    title, description = root.find(SVG + "title"), root.find(SVG + "desc")
    assert title is not None
    assert title.text
    assert description is not None
    assert description.text
    # the title and the description are named by the chart, with ids that exist
    assert root.get("aria-labelledby") == f"{title.get('id')} {description.get('id')}"
    assert title.text in texts(root, "text.gb-title")


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_chart_has_no_script_style_or_external_resource(name: str, dataset: str) -> None:
    svg = build(name, stats_of(DATASETS[dataset]))

    root = parse(svg)
    tags = {element.tag.removeprefix(SVG) for element in root.iter()}
    assert tags <= {
        "svg",
        "title",
        "desc",
        "g",
        "line",
        "path",
        "rect",
        "circle",
        "polyline",
        "text",
    }
    names = {attribute for element in root.iter() for attribute in element.attrib}
    assert not {name for name in names if name.startswith("on") or "href" in name or name == "src"}
    without_namespace = svg.replace(f'xmlns="{charts.SVG_NAMESPACE}"', "")
    assert "http" not in without_namespace
    assert "url(" not in svg
    assert "@import" not in svg
    assert not re.search(r"\b(nan|inf)\b", svg, re.IGNORECASE)


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_everything_lies_inside_the_view_box(name: str, dataset: str) -> None:
    root = parse(build(name, stats_of(DATASETS[dataset])))

    height = float(root.get("viewBox", "").split()[3])
    for element in root.iter():
        for attribute, limit in (
            ("x", charts.WIDTH),
            ("x1", charts.WIDTH),
            ("x2", charts.WIDTH),
            ("cx", charts.WIDTH),
            ("y", height),
            ("y1", height),
            ("y2", height),
            ("cy", height),
        ):
            if attribute in element.attrib:
                assert 0 <= float(element.get(attribute, "")) <= limit, (element.tag, attribute)
        for pair in element.get("points", "").split():
            x, y = map(float, pair.split(","))
            assert 0 <= x <= charts.WIDTH
            assert 0 <= y <= height


def test_ids_of_the_charts_are_unique_on_one_page() -> None:
    stats = stats_of(complete_data())

    page = "".join(build(name, stats) for name in CHART_NAMES)

    ids = re.findall(r' id="([^"]+)"', page)
    assert len(ids) == 8
    assert len(set(ids)) == 8


def test_charts_lists_the_four_charts_in_order() -> None:
    assert tuple(charts.CHARTS) == CHART_NAMES
    assert charts.CHARTS["week"] is charts.week_chart


def test_text_and_grid_follow_the_color_of_the_page() -> None:
    stats = stats_of(with_gaps())
    allowed = {"currentColor", "none", *charts.YEAR_COLORS}
    for name in CHART_NAMES:
        root = parse(build(name, stats))

        # no fixed black, white or gray: only the series have colors of their own
        colors = {
            element.get(attribute)
            for element in root.iter()
            for attribute in ("fill", "stroke")
            if attribute in element.attrib
        }
        assert colors <= allowed
        assert {line.get("stroke") for line in grid_lines(root)} == {"currentColor"}
        plain = [text for text in find(root, "text") if "gb-mark" not in text.get("class", "")]
        assert {text.get("fill") for text in plain} == {"currentColor"}


def test_years_have_the_same_color_in_every_chart() -> None:
    stats = stats_of(complete_data())
    colors = charts.year_colors([2022, 2023, 2024, 2025, 2026])
    # up to four years: the three earlier years are the latest ones
    assert colors[2026] == charts.YEAR_COLORS[0]
    assert colors[2025] == charts.YEAR_COLORS[1]

    monthly = parse(charts.monthly_chart(stats))
    cumulative = parse(charts.cumulative_chart(stats))

    assert [series.year for series in stats.monthly] == [2023, 2024, 2025, 2026]
    expected = {year: colors[year] for year in (2023, 2024, 2025, 2026)}
    (legend_group,) = find(monthly, "g.gb-legend")
    # the first swatches and labels of the legend are the years
    swatches = [rect.get("fill") for rect in legend_group.findall(SVG + "rect")][:4]
    labels = [text.text for text in legend_group.findall(SVG + "text")][:4]
    assert dict(zip(labels, swatches, strict=True)) == {str(y): c for y, c in expected.items()}
    for year, color in expected.items():
        (group,) = [
            g for g in find(cumulative, "g.gb-line") if f"gb-year-{year}" in g.get("class", "")
        ]
        assert {line.get("stroke") for line in group.iter(SVG + "polyline")} == {color}


@pytest.mark.parametrize("color", charts.YEAR_COLORS)
def test_palette_is_readable_on_light_and_on_dark_backgrounds(color: str) -> None:
    assert contrast(color, "#ffffff") >= 3
    assert contrast(color, "#111827") >= 3


def test_year_colors_start_with_the_latest_year_and_repeat_after_the_palette() -> None:
    assert charts.year_colors([2026, 2025]) == {
        2026: charts.YEAR_COLORS[0],
        2025: charts.YEAR_COLORS[1],
    }
    many = charts.year_colors(range(2020, 2027))
    assert many[2026] == many[2022] == charts.YEAR_COLORS[0]


# --- axes ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("maximum", "ticks"),
    [
        (0, (0, 1)),
        (1, (0, 1)),
        (3, (0, 1, 2, 3)),
        (5, (0, 1, 2, 3, 4, 5)),
        (7, (0, 2, 4, 6, 8)),
        (99, (0, 20, 40, 60, 80, 100)),
        (100, (0, 20, 40, 60, 80, 100)),
        (101, (0, 50, 100, 150)),
        (1100, (0, 500, 1000, 1500)),
        (6000, (0, 2000, 4000, 6000)),
        (123_456_789, (0, 50_000_000, 100_000_000, 150_000_000)),
    ],
)
def test_ticks_are_round_numbers_up_to_the_maximum(maximum: int, ticks: tuple[int, ...]) -> None:
    assert charts.nice_ticks(maximum) == ticks


def test_ticks_for_any_maximum_are_at_most_5_intervals_with_steps_of_1_2_or_5() -> None:
    for maximum in [*range(3000), *range(3000, 10**7, 99_991), 10**12 + 7]:
        ticks = charts.nice_ticks(maximum)
        step = ticks[1] - ticks[0]
        assert ticks[0] == 0
        assert ticks[-1] >= maximum
        assert ticks[-1] - step < max(maximum, 1) or maximum == 0
        assert 1 <= len(ticks) - 1 <= charts.MAX_TICK_INTERVALS
        assert all(b - a == step for a, b in itertools.pairwise(ticks))
        assert re.fullmatch(r"[125]0*", str(step))


def test_axis_of_very_small_values_has_whole_liters() -> None:
    stored = stored_days(WEEK_START, 1, 3, 2, 1, 3, 2, 1)

    root = parse(charts.week_chart(stats_of(stored)))

    assert texts(root, "text.gb-tick") == ["0", "1", "2", "3"]
    assert texts(root, "text.gb-value") == ["1", "3", "2", "1", "3", "2", "1"]


def test_axis_of_very_large_values_makes_room_for_its_labels() -> None:
    root = parse(charts.week_chart(stats_of(stored_days(WEEK_START, *[123_456_789] * 7))))

    ticks = find(root, "text.gb-tick")
    assert [tick.text for tick in ticks] == ["0", "50000000", "100000000", "150000000"]
    for tick in ticks:
        # right-aligned at the axis: the longest label starts inside the chart
        assert float(tick.get("x", "")) - len(tick.text or "") * 6.3 >= 0
    # the value labels get smaller instead of touching each other
    sizes = {float(value.get("font-size", "")) for value in find(root, "text.gb-value")}
    assert len(sizes) == 1
    (size,) = sizes
    assert size < 11
    plot_left = float(ticks[0].get("x", "")) + 6
    assert 9 * 0.58 * size <= (charts.WIDTH - 14 - plot_left) / 7


def test_axis_without_any_value_has_a_default_scale() -> None:
    for name in CHART_NAMES:
        root = parse(build(name, stats_of({})))

        assert texts(root, "text.gb-tick") == ["0", "20", "40", "60", "80", "100"]


# --- week ------------------------------------------------------------------------------------


def test_week_chart_has_a_bar_and_a_label_for_every_day() -> None:
    stored = stored_days(WEEK_START, 100, 200, 150, 120, 300, 90, 140)

    root = parse(charts.week_chart(stats_of(stored)))

    bars = find(root, "path.gb-bar")
    assert len(bars) == 7
    assert texts(root, "text.gb-value") == ["100", "200", "150", "120", "300", "90", "140"]
    assert texts(root, "text.gb-day") == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert texts(root, "text.gb-date") == [f"11-{day}" for day in range(16, 23)]
    assert find(root, "path.gb-interpolated") == []
    assert find(root, "text.gb-missing") == []
    # the bars are as high as the values: 200 l is twice 100 l
    assert bar_height(bars[1]) == pytest.approx(2 * bar_height(bars[0]), abs=0.2)
    assert bar_height(bars[4]) == max(bar_height(bar) for bar in bars)
    assert [bar_x(bar) for bar in bars] == sorted(bar_x(bar) for bar in bars)
    assert "Daily consumption, week 47/2026" in texts(root, "text.gb-title")


def test_week_chart_marks_an_interpolated_day() -> None:
    stored = stored_days(WEEK_START, 100, "-", 300, 100, 100, 100, 100)

    root = parse(charts.week_chart(stats_of(stored)))

    (light,) = find(root, "path.gb-interpolated")
    assert light.get("fill-opacity") == "0.4"
    assert light.get("stroke-dasharray")
    assert len(find(root, "path.gb-bar")) == 7
    assert texts(root, "text.gb-value")[:3] == ["100", "200*", "300"]
    assert "interpolated *" in legend(root)
    description = root.find(SVG + "desc")
    assert description is not None
    assert "Tue 200 (interpolated)" in (description.text or "")


def test_week_chart_shows_missing_days_as_gaps_with_a_dash() -> None:
    # data from Wednesday to Friday: Monday and Tuesday are before it, the weekend is missing
    stored = stored_days(D(2026, 11, 18), 100, 100, 100)

    root = parse(charts.week_chart(stats_of(stored)))

    assert len(find(root, "path.gb-bar")) == 3
    assert texts(root, "text.gb-missing") == [DASH] * 4
    assert [text.get("class") for text in find(root, "text.gb-missing")] == [
        "gb-missing gb-no-data",
        "gb-missing gb-no-data",
        "gb-missing gb-missing",
        "gb-missing gb-missing",
    ]
    assert texts(root, "text.gb-value") == ["100", "100", "100"]
    description = root.find(SVG + "desc")
    assert description is not None
    assert "Mon no data, Tue no data, Wed 100" in (description.text or "")
    assert "Sat missing, Sun missing" in (description.text or "")


def test_week_chart_without_any_value_is_valid() -> None:
    root = parse(charts.week_chart(stats_of({})))

    assert find(root, "path.gb-bar") == []
    assert texts(root, "text.gb-missing") == [DASH] * 7
    assert texts(root, "text.gb-value") == []
    assert texts(root, "text.gb-day") == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def test_week_chart_shows_a_day_without_consumption_as_zero_without_a_bar() -> None:
    root = parse(
        charts.week_chart(stats_of(stored_days(WEEK_START, 0, 100, 100, 100, 100, 100, 100)))
    )

    assert len(find(root, "path.gb-bar")) == 6
    assert texts(root, "text.gb-value")[0] == "0"


# --- months ----------------------------------------------------------------------------------


def test_monthly_chart_has_grouped_bars_for_the_current_year_and_three_earlier_years() -> None:
    stats = stats_of(complete_data())

    root = parse(charts.monthly_chart(stats))

    assert [series.year for series in stats.monthly] == [2023, 2024, 2025, 2026]
    bars = find(root, "path.gb-bar")
    # 3 complete years of 12 months, 2026 up to November (December has no data)
    assert len(bars) == 3 * 12 + 11
    assert texts(root, "text.gb-month") == list(charts.MONTHS)
    # within a month the years follow from the oldest to the current one, left to right
    first_group = [bar_x(bar) for bar in bars[:4]]
    assert first_group == sorted(first_group)
    assert [bar.get("fill") for bar in bars[:4]] == [
        charts.year_colors([2023, 2024, 2025, 2026])[year] for year in (2023, 2024, 2025, 2026)
    ]


def test_monthly_chart_shows_an_incomplete_month_only_as_an_outline() -> None:
    root = parse(charts.monthly_chart(stats_of(with_gaps())))

    outlines = find(root, "path.gb-incomplete")
    # October (6 missing days) and November (the month is not over) of the current year
    assert len(outlines) == 2
    for outline in outlines:
        assert outline.get("fill-opacity") == "0.12"
        assert outline.get("stroke") == charts.YEAR_COLORS[0]
    complete = [
        bar for bar in find(root, "path.gb-bar") if "gb-incomplete" not in bar.get("class", "")
    ]
    assert all(bar.get("fill-opacity") is None for bar in complete)
    assert "outline: incomplete month" in legend(root)


def test_monthly_chart_marks_months_with_interpolated_days() -> None:
    root = parse(charts.monthly_chart(stats_of(with_gaps())))

    # the 19th of November is interpolated
    (star,) = find(root, "text.gb-mark")
    assert star.text == "*"
    assert star.get("fill") == charts.YEAR_COLORS[0]
    assert len(find(root, "path.gb-interpolated")) == 1


def test_monthly_chart_of_a_single_year_has_one_bar_per_month() -> None:
    stats = stats_of(fill(D(2026, 1, 1), D(2026, 11, 22), 150))

    root = parse(charts.monthly_chart(stats))

    assert [series.year for series in stats.monthly] == [2026]
    assert len(find(root, "path.gb-bar")) == 11
    labels = legend(root)
    assert "2026" in labels
    assert not any(label in labels for label in ("2025", "2024", "2023"))


# --- cumulative ------------------------------------------------------------------------------


def test_cumulative_chart_has_a_line_for_every_year_and_marks_the_run_day() -> None:
    stats = stats_of(complete_data())

    root = parse(charts.cumulative_chart(stats))

    lines = find(root, "g.gb-line")
    assert [line.get("class") for line in lines] == [
        f"gb-line gb-year-{year}" for year in (2023, 2024, 2025, 2026)
    ]
    assert all(len(line.findall(SVG + "polyline")) == 1 for line in lines)
    assert len(find(root, "polyline")[0].get("points", "").split()) == 365
    assert len(find(root, "polyline")[1].get("points", "").split()) == 366  # 2024
    # the run day is a dashed line at 23 November (day 327 of 366 positions) with its label
    (marker,) = find(root, "line.gb-run-day")
    plot_left = float(grid_lines(root)[0].get("x1", ""))
    plot_right = float(grid_lines(root)[0].get("x2", ""))
    expected = plot_left + 326 / 365 * (plot_right - plot_left)
    assert float(marker.get("x1", "")) == pytest.approx(expected, abs=0.1)
    assert marker.get("stroke-dasharray")
    assert texts(root, "text.gb-run-label") == ["run day"]
    assert texts(root, "text.gb-month") == list(charts.MONTHS)
    # the current year ends with a dot at the last day with a value
    (end,) = find(root, "circle.gb-end")
    assert end.get("fill") == charts.YEAR_COLORS[0]


def test_cumulative_chart_breaks_the_line_at_missing_days() -> None:
    root = parse(charts.cumulative_chart(stats_of(with_gaps())))

    (current,) = [g for g in find(root, "g.gb-line") if "gb-year-2026" in g.get("class", "")]
    # the 6 missing days of October and the missing Sunday after the interpolated Thursday
    assert len(current.findall(SVG + "polyline")) == 2
    (earlier, *_) = [g for g in find(root, "g.gb-line") if "gb-year-2023" in g.get("class", "")]
    assert len(earlier.findall(SVG + "polyline")) == 1


def test_cumulative_chart_explains_the_gaps_only_if_there_are_any() -> None:
    with_gap = parse(charts.cumulative_chart(stats_of(with_gaps())))
    without = parse(charts.cumulative_chart(stats_of(complete_data())))

    assert "missing days (not added)" in legend(with_gap)
    assert "missing days (not added)" not in legend(without)
    description = with_gap.find(SVG + "desc")
    assert description is not None
    assert "A missing day breaks the line; its liters are not added." in (description.text or "")


def test_cumulative_chart_marks_interpolated_days_with_a_ring() -> None:
    root = parse(charts.cumulative_chart(stats_of(with_gaps())))

    (ring,) = find(root, "circle.gb-interpolated")
    assert ring.get("fill") == "none"
    assert ring.get("stroke") == charts.YEAR_COLORS[0]
    assert "interpolated day" in legend(root)


def test_cumulative_chart_draws_a_single_day_between_gaps_as_a_dot() -> None:
    # 1 January, then 5 missing days, 7 January, 5 missing days and the rest of the year
    stored = {
        D(2026, 1, 1): 10,
        D(2026, 1, 7): 10,
        **fill(D(2026, 1, 13), D(2026, 11, 22), 10),
    }

    root = parse(charts.cumulative_chart(stats_of(stored)))

    assert len(find(root, "circle.gb-dot")) == 2
    assert len(find(root, "polyline")) == 1


def test_cumulative_chart_of_a_year_without_values_has_only_the_run_day() -> None:
    root = parse(charts.cumulative_chart(stats_of({})))

    assert find(root, "polyline") == []
    assert find(root, "circle.gb-end") == []
    assert len(find(root, "line.gb-run-day")) == 1


def test_run_label_stays_inside_the_chart_at_the_end_of_the_year() -> None:
    root = parse(
        charts.cumulative_chart(stats_of(fill(D(2026, 1, 1), D(2026, 12, 29)), D(2026, 12, 30)))
    )

    (label,) = find(root, "text.gb-run-label")
    assert label.get("text-anchor") == "end"


# --- weeks -----------------------------------------------------------------------------------


def test_weekly_chart_has_a_point_for_every_week_and_a_line_through_them() -> None:
    stats = stats_of(complete_data())

    root = parse(charts.weekly_chart(stats))

    points = find(root, "circle.gb-point")
    assert len(points) == 52
    assert find(root, "circle.gb-incomplete") == []
    assert all(point.get("fill") == charts.YEAR_COLORS[0] for point in points)
    (line,) = find(root, "polyline")
    assert len(line.get("points", "").split()) == 52
    # the value of the last week is written next to its point
    assert texts(root, "text.gb-value") == ["1100"]
    assert "Weekly consumption, last 52 weeks" in texts(root, "text.gb-title")


def test_weekly_chart_shows_incomplete_weeks_as_hollow_points() -> None:
    root = parse(charts.weekly_chart(stats_of(with_gaps())))

    hollow = find(root, "circle.gb-incomplete")
    # the weeks of the 5th to the 18th of October have missing days; the last week has one
    # more (Sunday, the last day of the data); November the 19th is interpolated, not missing
    assert len(hollow) == 3
    assert all(point.get("fill") == "none" for point in hollow)
    assert all(point.get("stroke") == charts.YEAR_COLORS[0] for point in hollow)
    assert len(find(root, "circle.gb-point")) == 52
    assert "incomplete week" in legend(root)


def test_weekly_chart_leaves_out_weeks_without_values_and_breaks_the_line() -> None:
    # the data starts 10 weeks ago and has a gap of 3 weeks
    stored = {
        **fill(MONDAY - datetime.timedelta(weeks=10), MONDAY - datetime.timedelta(weeks=7, days=1)),
        **fill(MONDAY - datetime.timedelta(weeks=4), MONDAY - datetime.timedelta(days=1)),
    }

    root = parse(charts.weekly_chart(stats_of(stored)))

    assert len(find(root, "circle.gb-point")) == 3 + 4
    assert len(find(root, "polyline")) == 2


def test_weekly_chart_marks_a_week_with_an_interpolated_day() -> None:
    stored = stored_days(WEEK_START, 100, "-", 300, 100, 100, 100, 100)

    root = parse(charts.weekly_chart(stats_of({**fill(D(2025, 1, 1), D(2026, 11, 15)), **stored})))

    (star,) = find(root, "text.gb-mark")
    assert star.text == "*"


def test_weekly_chart_labels_the_months_and_the_years() -> None:
    stats = stats_of(complete_data())

    labels = texts(parse(charts.weekly_chart(stats)), "text.gb-month")

    # the 52 weeks start on 2025-11-24, December follows after one week: no label for
    # November; the first label and every January have the year
    assert stats.weekly[0].start == D(2025, 11, 24)
    assert labels == [
        "Dec 25",
        "Jan 26",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
    ]


def test_weekly_chart_labels_the_first_month_if_the_next_one_is_far_enough() -> None:
    # the first week starts on 2025-12-01: January follows after 5 weeks
    stats = stats_of(fill(D(2025, 1, 1), D(2026, 11, 29)), D(2026, 11, 30))

    labels = texts(parse(charts.weekly_chart(stats)), "text.gb-month")

    assert stats.weekly[0].start == D(2025, 12, 1)
    assert labels[:3] == ["Dec 25", "Jan 26", "Feb"]


def test_all_charts_of_the_report_together_are_small_enough_for_a_mail() -> None:
    stats = stats_of(complete_data())

    sizes = {name: len(build(name, stats)) for name in CHART_NAMES}

    assert sum(sizes.values()) < 80_000, sizes
    assert all(size > 1000 for size in sizes.values())


# --- a chart as image ------------------------------------------------------------------------


def image_of(name: str, dataset: str) -> tuple[str, str]:
    """(the chart, the chart as image)"""
    svg = build(name, stats_of(DATASETS[dataset]))
    return svg, charts.as_image(svg)


def elements(root: ET.Element) -> list[tuple[str, dict[str, str], str | None, str | None]]:
    """every element below the root in document order: tag, attributes, text and tail"""
    return [
        (element.tag, dict(element.attrib), element.text, element.tail)
        for element in root.iter()
        if element is not root
    ]


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_image_has_the_size_of_its_view_box_and_no_relative_size(name: str, dataset: str) -> None:
    _, image = image_of(name, dataset)

    root = parse(image)
    assert root.tag == SVG + "svg"
    _, _, width, height = root.get("viewBox", "").split()
    assert root.get("width") == width == str(charts.WIDTH)
    assert root.get("height") == height
    assert height.isdigit()
    assert "style" not in root.attrib
    assert "max-width" not in image
    assert not [
        (element.tag, value)
        for element in root.iter()
        for value in element.attrib.values()
        if "%" in value
    ]


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_image_has_one_style_as_first_child_with_both_text_colors(name: str, dataset: str) -> None:
    _, image = image_of(name, dataset)

    root = parse(image)
    styles = list(root.iter(SVG + "style"))
    assert styles == [root[0]]
    css = styles[0].text or ""
    assert f"svg {{ color: {charts.IMAGE_TEXT_COLOR}; }}" in css
    dark = css.partition("@media (prefers-color-scheme: dark)")[2]
    assert f"svg {{ color: {charts.IMAGE_TEXT_COLOR_DARK}; }}" in dark
    assert charts.IMAGE_TEXT_COLOR_DARK not in css.partition("@media")[0]


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_image_keeps_everything_else_of_the_chart(name: str, dataset: str) -> None:
    svg, image = image_of(name, dataset)

    chart, picture = parse(svg), parse(image)
    # the elements in the same order with the same attributes and texts, only the style is new
    assert elements(picture)[1:] == elements(chart)
    # the attributes of the root: the same apart from the size
    unchanged = {key: value for key, value in chart.attrib.items() if key not in {"width", "style"}}
    assert {k: v for k, v in picture.attrib.items() if k not in {"width", "height"}} == unchanged
    # the namespace of the chart, written as in the chart (no prefix)
    assert image.startswith(f'<svg xmlns="{charts.SVG_NAMESPACE}" ')
    assert "ns0" not in image
    # after the start tag and the style, the text is the one of the chart, character by character
    _, style, rest = image.partition(f"<style>{charts.IMAGE_STYLE}</style>")
    assert style
    assert rest == svg.partition(">")[2]


@pytest.mark.parametrize("name", CHART_NAMES)
def test_image_leaves_the_chart_as_it_is_and_is_the_same_every_time(name: str) -> None:
    stats = stats_of(with_gaps())
    svg = build(name, stats)

    image = charts.as_image(svg)

    assert svg == build(name, stats)
    assert charts.as_image(svg) == image
    assert image != svg


@pytest.mark.parametrize("name", CHART_NAMES)
@pytest.mark.parametrize("dataset", DATASETS)
def test_image_has_no_script_or_external_resource(name: str, dataset: str) -> None:
    _, image = image_of(name, dataset)

    root = parse(image)
    tags = {element.tag.removeprefix(SVG) for element in root.iter()}
    assert "style" in tags
    assert not tags & {"script", "image", "foreignObject", "a", "use"}
    without_namespace = image.replace(f'xmlns="{charts.SVG_NAMESPACE}"', "")
    assert "http" not in without_namespace
    assert "url(" not in image
    assert "@import" not in image


def test_image_has_the_text_colors_of_the_card_of_the_mail() -> None:
    # light: the inline style of the card; dark: the rule of the card in the style sheet
    document = report_html.format_failure_html("no statistics")
    (card,) = re.findall(r'<td class="gb-card" style="([^"]*)"', document)
    (light,) = re.findall(r"(?:^|;)color:(#[0-9a-f]{6})", card)
    (rule,) = re.findall(r"\.gb-card \{([^}]*)\}", report_html.HTML_DARK_STYLE)
    (dark,) = re.findall(r"(?<![-\w])color: (#[0-9a-f]{6})", rule)

    assert light == charts.IMAGE_TEXT_COLOR
    assert dark == charts.IMAGE_TEXT_COLOR_DARK


def test_image_text_colors_are_readable_on_the_card() -> None:
    assert contrast(charts.IMAGE_TEXT_COLOR, "#ffffff") >= 4.5
    assert contrast(charts.IMAGE_TEXT_COLOR_DARK, "#111827") >= 4.5


def test_image_of_a_view_box_with_fractions_is_rounded_up_to_whole_pixels() -> None:
    svg = f'<svg xmlns="{charts.SVG_NAMESPACE}" viewBox="0 0 480.2 100.5" width="100%"/>'

    root = parse(charts.as_image(svg))

    assert (root.get("width"), root.get("height")) == ("481", "101")
    assert root.get("viewBox") == "0 0 480.2 100.5"


@pytest.mark.parametrize(
    ("svg", "message"),
    [
        ('<svg viewBox="0 0 480 100"/>', "not an SVG element"),
        (f'<html xmlns="{charts.SVG_NAMESPACE}"/>', "not an SVG element"),
        (f'<svg xmlns="{charts.SVG_NAMESPACE}"/>', "no viewBox"),
        (f'<svg xmlns="{charts.SVG_NAMESPACE}" viewBox="0 0 480"/>', "no viewBox"),
        (f'<svg xmlns="{charts.SVG_NAMESPACE}" viewBox="0 0 wide high"/>', "no viewBox"),
    ],
)
def test_image_of_a_text_that_is_not_a_chart_is_an_error(svg: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        charts.as_image(svg)
