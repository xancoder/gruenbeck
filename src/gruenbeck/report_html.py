"""
the statistics as HTML document for the data mail

format_html() draws the sections of report_sections as tables of inline CSS;
format_failure_html() is the document without statistics. The plain text part is report_text.
"""

import collections.abc
import re
from html import escape

from gruenbeck import report, report_sections
from gruenbeck.report import Day, DayStatus, Period, Report

HTML_WIDTH = 640
HTML_FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
# The colors are inline, so a mail program without style sheets shows the light variant. The
# style sheet only switches them for a dark color scheme.
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
TABLE_COLUMNS = (
    ("Year", "left"),
    ("Period", "left"),
    ("Total", "right"),
    ("Mean", "right"),
    ("Min", "right"),
    ("Max", "right"),
)


def format_html(stats: Report, notes: collections.abc.Sequence[str] = ()) -> str:
    """
    the statistics as HTML document for the data mail: the tables of format_text()

    The layout is a table of at most HTML_WIDTH pixels with inline CSS, so it works in mail
    programs; a style sheet in the head only adds the colors for a dark color scheme.
    :param notes: texts for the top of the page (e.g. that no data files are attached)
    """
    sections = report_sections.sections(stats)
    body = [_html_heading(f"in liters, run on {stats.today.isoformat()}")]
    body += [_html_paragraph(note) for note in notes]
    for section in sections:
        body.append(_html_section(section))
    legend = report_sections.legend(sections)
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


def _html_section(section: report_sections.Section) -> str:
    heading = '<h2 style="margin:24px 0 8px;font-size:16px;line-height:1.3;">'
    # a date is not broken at its hyphens on a narrow screen
    title = DATE.sub(
        lambda date: f'<span style="white-space:nowrap;">{date[0]}</span>', escape(section.title)
    )
    parts = [f"{heading}{title}</h2>"]
    if section.daily is not None:
        parts.append(_html_days(section.daily))
    if section.periods:
        parts.append(_html_table(section.periods))
    if section.note:
        parts.append(
            f'<p class="gb-muted" style="margin:6px 0;font-size:12px;{HTML_MUTED}">'
            f"{escape(section.note)}</p>"
        )
    return "".join(parts)


def _html_days(week: Period) -> str:
    heads = []
    cells = []
    for day in week.days:
        name = report.WEEKDAYS[day.date.weekday()]
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
        note = report_sections.incomplete_note(period)
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
