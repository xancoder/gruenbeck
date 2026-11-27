"""report_html: the statistics as HTML document of the data mail (P007-S4)"""

import collections
import datetime
import html.parser
import re

import pytest

from gruenbeck import report, report_html, report_text

D = datetime.date
Stored = dict[datetime.date, int | str]

MONDAY = D(2026, 11, 23)
WEEK_START = D(2026, 11, 16)
NBSP = "\N{NO-BREAK SPACE}"
DASH = "\N{EN DASH}"
VOID_TAGS = {"meta", "br"}


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


def full_data() -> Stored:
    return {
        **fill(D(2025, 1, 1), D(2025, 12, 31), 20),
        **fill(D(2026, 1, 1), D(2026, 11, 15), 30),
        **stored_days(WEEK_START, 100, 200, 150, 120, 300, 90, 140),
    }


def with_gaps() -> Stored:
    stored = {**fill(D(2024, 3, 1), D(2026, 11, 22), 99), **stored_days(WEEK_START, 100, 200)}
    # a day interpolated, 5 days missing in the middle of the data and the last day
    for day in (D(2026, 11, 19), D(2026, 11, 22), *[D(2025, 7, n) for n in range(10, 15)]):
        del stored[day]
    return stored


def stats_of(stored: Stored, today: datetime.date = MONDAY) -> report.Report:
    return report.compute_report(stored, today)


class Page(html.parser.HTMLParser):
    """the HTML of the mail: checks the nesting, collects headings and the cells of tables"""

    def __init__(self, document: str):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []
        self.tags: collections.Counter[str] = collections.Counter()
        self.headings: list[str] = []
        self.tables: list[list[list[str]]] = []
        self.rows: list[tuple[list[str], bool]] = []
        self.classes: set[str] = set()
        self._text: list[str] | None = None
        self._cell: list[str] | None = None
        self.feed(document)
        self.close()
        if self.stack:
            self.problems.append(f"not closed: {self.stack}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags[tag] += 1
        self.classes.update((dict(attrs).get("class") or "").split())
        if tag == "br":
            self.handle_data(" ")
        if tag not in VOID_TAGS:
            self.stack.append(tag)
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self.tables[-1].append([])
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "h2":
            self._text = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags[tag] += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            self.problems.append(f"unexpected </{tag}>")
        if tag in ("td", "th") and self._cell is not None:
            text = "".join(self._cell).replace(NBSP, " ")
            self.tables[-1][-1].append(" ".join(text.split()))
            self._cell = None
        elif tag == "h2" and self._text is not None:
            self.headings.append(" ".join("".join(self._text).split()))
            self._text = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        if self._text is not None:
            self._text.append(data)

    def rows_of(self, columns: int) -> list[list[str]]:
        """the rows with this number of cells of all tables"""
        return [row for table in self.tables for row in table if len(row) == columns]


def page_of(stored: Stored, today: datetime.date = MONDAY) -> tuple[Page, report.Report]:
    stats = stats_of(stored, today)
    return Page(report_html.format_html(stats)), stats


# --- document --------------------------------------------------------------------------------


@pytest.mark.parametrize("stored", [full_data(), with_gaps(), {}], ids=["full", "gaps", "empty"])
def test_document_is_well_formed_html_with_inline_css_and_no_external_resource(
    stored: Stored,
) -> None:
    document = report_html.format_html(stats_of(stored))

    page = Page(document)
    assert page.problems == []
    assert document.startswith('<!DOCTYPE html>\n<html lang="en"><head>')
    assert '<meta charset="utf-8">' in document
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in document
    assert '<meta name="color-scheme" content="light dark">' in document
    assert page.tags["script"] == 0
    assert page.tags["style"] == 1
    assert not re.search(r"\b(?:src|href)=|url\(|@import|<link|<img", document)
    # the layout is a table of at most 640 px, every element has its style inline
    assert 'width="640"' in document
    assert "max-width:640px" in document
    assert 'role="presentation"' in document
    assert 'style="' in document
    assert document.count("<table") == document.count("</table>")


def test_head_style_only_switches_the_colors_for_a_dark_color_scheme() -> None:
    # with a period that is not complete, so the class of its note is used
    document = report_html.format_html(stats_of(with_gaps()))

    (style,) = re.findall(r"<style>(.*?)</style>", document)
    assert style.startswith("@media (prefers-color-scheme: dark) {")
    classes = set(re.findall(r"\.(gb-[a-z]+)", style))
    assert classes == {"gb-page", "gb-card", "gb-muted", "gb-warn", "gb-rule", "gb-head"}
    # every class of the style sheet is used, and every class of the page has a rule
    page = Page(document)
    assert classes <= page.classes
    assert page.classes <= classes
    # the colors are in the elements too: the page is complete without the style sheet
    assert "background:#ffffff;color:#1f2937" in document


# --- headings and tables ---------------------------------------------------------------------


def test_sections_are_the_ones_of_the_text() -> None:
    page, _ = page_of(full_data())

    assert page.headings == [
        "Last week: week 47/2026, 2026-11-16 .. 2026-11-22",
        "Current month so far: 2026-11-01 .. 2026-11-22",
        "Last month: 2026-10-01 .. 2026-10-31",
        "Year so far: 2026-01-01 .. 2026-11-22",
        "Earlier years as a whole",
    ]


def test_tables_of_the_run_and_the_earlier_years() -> None:
    page, _ = page_of(full_data())

    rows = page.rows_of(6)
    assert rows[0] == ["Year", "Period", "Total", "Mean", "Min", "Max"]
    assert rows[1:3] == [
        ["2026", "11-16 \N{EN DASH} 11-22", "1100", "157", "90 11-21", "300 11-20"],
        ["2025", "11-17 \N{EN DASH} 11-23", "140", "20", "20 11-17", "20 11-17"],
    ]
    # the earlier years as a whole
    assert ["2025", "01-01 \N{EN DASH} 12-31", "7300", "20", "20 01-01", "20 01-01"] in rows


def test_days_of_the_week_are_a_table_of_seven_columns() -> None:
    page, _ = page_of(full_data())

    heads, values = page.rows_of(7)
    assert heads == [
        f"{name} 11-{day}" for name, day in zip(report.WEEKDAYS, range(16, 23), strict=True)
    ]
    assert values == ["100", "200", "150", "120", "300", "90", "140"]


@pytest.mark.parametrize(
    "stored",
    [
        full_data(),
        with_gaps(),
        fill(D(2026, 1, 1), D(2026, 11, 22)),
        fill(D(2016, 12, 31), D(2026, 11, 22)),
        {},
    ],
)
def test_html_has_the_rows_and_the_notes_of_the_text(stored: Stored) -> None:
    stats = stats_of(stored)
    text = report_text.format_text(stats)
    page = Page(report_html.format_html(stats))

    text_rows = [
        re.split(r"\s{2,}", line.strip())
        for line in text.splitlines()
        if re.match(r"\d{4}  \d\d-\d\d\.\.", line)
    ]
    html_rows = [
        [row[0], row[1].replace(f" {DASH} ", ".."), *row[2:]]
        for row in page.rows_of(6)
        if re.fullmatch(r"\d{4}", row[0])
    ]
    # the text writes a dash for no value, the HTML an en dash
    text_rows = [
        [cell.replace("-", DASH) if cell == "-" else cell for cell in r] for r in text_rows
    ]
    assert html_rows == text_rows
    assert len(html_rows) >= 4
    notes = [line.strip() for line in text.splitlines() if line.strip().startswith("incomplete:")]
    html_notes = [row[0] for row in page.rows_of(1) if row[0].startswith("incomplete:")]
    assert html_notes == notes
    # the notes about the earlier years that are left out (the text wraps them)
    hints = r"\d+ earlier years? (?:is|are) not shown \([^)]*\)\."
    assert re.findall(hints, report_html.format_html(stats)) == re.findall(
        hints, " ".join(text.split())
    )


def test_interpolated_values_are_marked_and_explained() -> None:
    stored = stored_days(WEEK_START, 100, "-", 300, 300, 300, 300, 300)

    document = report_html.format_html(stats_of(stored))

    page = Page(document)
    _, values = page.rows_of(7)
    assert values[:3] == ["100", "200*", "300"]
    assert page.rows_of(6)[1][2:] == ["1800*", "257", "100 11-16", "300 11-18"]
    assert "* includes interpolated days: a gap of up to 3 days between measured days" in document
    assert "Mean: liters per day with a value. Min and Max: measured days only." in document


def test_legend_of_interpolated_days_is_only_there_if_needed() -> None:
    document = report_html.format_html(stats_of(full_data()))

    assert "*" not in document
    assert "includes interpolated" not in document
    assert "Mean: liters per day with a value." in document


def test_missing_days_and_incomplete_periods_are_named() -> None:
    # data from Wednesday to Friday: Monday and Tuesday are before it, the weekend is missing
    stored = stored_days(D(2026, 11, 18), 100, 100, 100)

    page, _ = page_of(stored)

    _, values = page.rows_of(7)
    assert values == [
        f"{DASH} no data",
        f"{DASH} no data",
        "100",
        "100",
        "100",
        f"{DASH} missing",
        f"{DASH} missing",
    ]
    assert "incomplete: 2 days missing, 2 days without data" in [r[0] for r in page.rows_of(1)]
    assert "gb-warn" in page.classes


def test_period_without_values_has_dashes() -> None:
    page, _ = page_of({})

    assert page.rows_of(6)[1] == ["2026", "11-16 \N{EN DASH} 11-22", DASH, DASH, DASH, DASH]


def test_without_an_earlier_year_every_table_says_so() -> None:
    document = report_html.format_html(stats_of(fill(D(2026, 1, 1), D(2026, 11, 22))))

    assert document.count("No earlier year has enough values for this period.") == 4
    assert "No earlier year has enough values." in document
    assert "2025" not in document


def test_long_history_has_at_most_five_earlier_years_per_table_and_says_what_is_left_out() -> None:
    page, stats = page_of(fill(D(2016, 12, 31), D(2026, 11, 22)))

    years = [row[0] for row in page.rows_of(6) if re.fullmatch(r"\d{4}", row[0])]
    five = ["2025", "2024", "2023", "2022", "2021"]
    assert years == ["2026", *five] * 4 + five
    document = report_html.format_html(stats)
    note = "earlier years are not shown (older than the latest 5, or with values on less than half"
    assert document.count(f"4 {note} of the days).") == 4
    assert document.count(f"5 {note} of the days).") == 1


def test_one_earlier_year_that_is_left_out_is_named_in_the_singular() -> None:
    document = report_html.format_html(stats_of(fill(D(2020, 1, 1), D(2026, 11, 22))))

    assert document.count("1 earlier year is not shown (") == 5
    assert "earlier years are not shown" not in document


def test_no_current_month_on_the_first_of_a_month_and_no_year_on_the_first_of_january() -> None:
    first_of_month, _ = page_of(fill(D(2026, 1, 1), D(2026, 11, 30)), today=D(2026, 12, 1))
    first_of_year, _ = page_of(fill(D(2025, 1, 1), D(2026, 12, 31)), today=D(2027, 1, 1))

    assert [h.split(":")[0] for h in first_of_month.headings] == [
        "Last week",
        "Last month",
        "Year so far",
        "Earlier years as a whole",
    ]
    assert [h.split(":")[0] for h in first_of_year.headings] == [
        "Last week",
        "Last month",
        "Earlier years as a whole",
    ]


def test_dates_in_a_heading_do_not_break_at_their_hyphens() -> None:
    document = report_html.format_html(stats_of(full_data()))

    assert (
        '<span style="white-space:nowrap;">2026-11-16</span> .. '
        '<span style="white-space:nowrap;">2026-11-22</span>' in document
    )


# --- no charts (P012-S1) ---------------------------------------------------------------------


@pytest.mark.parametrize("stored", [full_data(), with_gaps(), {}], ids=["full", "gaps", "empty"])
def test_document_has_no_image_and_no_address(stored: Stored) -> None:
    document = report_html.format_html(stats_of(stored), ["No data files found to attach."])

    assert "<svg" not in document
    assert "<img" not in document
    assert "http" not in document


# --- notes and failure -----------------------------------------------------------------------


def test_notes_are_paragraphs_at_the_top_and_escaped() -> None:
    document = report_html.format_html(stats_of(full_data()), notes=["No <data> & files"])

    assert "<p" in document
    assert "No &lt;data&gt; &amp; files" in document
    assert "No <data>" not in document
    assert document.index("No &lt;data") < document.index("Last week")


def test_failure_document_has_the_note_and_no_statistics() -> None:
    message = (
        "The statistics could not be calculated: bad <file> & \"x\" 'y'\n"
        "Details are in the log file."
    )

    document = report_html.format_failure_html(message, ["No data files found to attach."])

    page = Page(document)
    assert page.problems == []
    assert (
        "bad &lt;file&gt; &amp; &quot;x&quot; &#x27;y&#x27;<br>Details are in the log file."
        in document
    )
    assert "<file>" not in document
    assert "No data files found to attach." in document
    assert page.tags["th"] == 0
    assert page.headings == []
    assert "statistics not available" in document
    assert "<style>@media (prefers-color-scheme: dark)" in document


def test_cells_of_the_tables_have_no_markup_of_their_own() -> None:
    document = report_html.format_html(stats_of(with_gaps()))

    # all texts come from numbers and dates: no value can bring its own markup
    cells = [cell for table in Page(document).tables for row in table for cell in row]
    assert not [cell for cell in cells if "<" in cell or ">" in cell or "&" in cell]
