"""
the statistics as plain text for the data mail (ASCII, at most 78 characters per line)

format_text() draws the sections of report_sections as tables; the HTML part is report_html.
"""

import collections.abc
import textwrap

from gruenbeck import report, report_sections
from gruenbeck.report import Day, DayStatus, Period, Report

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


def format_text(stats: Report) -> str:
    """
    the statistics as plain text for the data mail (ASCII, at most 78 characters per line)

    The last week with every day, then tables of the week, the current and the last month
    and the year so far, each with the same period of the earlier years, and the earlier
    years as a whole. A period with missing days or days without data is marked as
    incomplete with their number; a total with interpolated days has a `*`.
    """
    sections = report_sections.sections(stats)
    parts = [f"Water consumption in liters, run on {stats.today.isoformat()}"]
    parts += [_text_section(section) for section in sections]
    # only the legend of the interpolated days is longer than a line
    legend = [
        textwrap.fill(line, 78, subsequent_indent="  ") for line in report_sections.legend(sections)
    ]
    parts.append("\n".join(legend))
    return "\n\n".join(parts) + "\n"


def _text_section(section: report_sections.Section) -> str:
    lines = [section.title, ""]
    if section.daily is not None:
        lines += [_day_line(day) for day in section.daily.days]
        lines.append("")
    if section.periods:
        lines += _table(section.periods)
        if section.note:
            lines += ["", textwrap.fill(section.note, 78)]
    elif section.note:
        lines.append(textwrap.fill(section.note, 78))
    return "\n".join(lines)


def _day_line(day: Day) -> str:
    label = f"  {report.WEEKDAYS[day.date.weekday()]} {day.date.isoformat()}"
    if day.liters is None:
        note = "  missing" if day.status is DayStatus.MISSING else "  no data"
        return f"{label}  {'-':>7} {note}"
    mark = "*" if day.status is DayStatus.INTERPOLATED else " "
    return f"{label}  {day.liters:>7}{mark}".rstrip()


def _table(periods: collections.abc.Sequence[Period]) -> list[str]:
    lines = [TABLE_HEADER, TABLE_RULE]
    for period in periods:
        lines.append(_table_row(period).rstrip())
        note = report_sections.incomplete_note(period)
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
