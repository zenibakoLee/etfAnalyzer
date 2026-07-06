import io
import logging
import os
import re
import tempfile
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable, KeepTogether,
)

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")

_FONT_FILES = {
    "Pretendard": "Pretendard-Regular.ttf",
    "Pretendard-Bold": "Pretendard-Bold.ttf",
    "Pretendard-SemiBold": "Pretendard-SemiBold.ttf",
    "Pretendard-Medium": "Pretendard-Medium.ttf",
    "Pretendard-Light": "Pretendard-Light.ttf",
}

_fonts_registered = False


def _register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    for name, filename in _FONT_FILES.items():
        path = os.path.join(_ASSETS, filename)
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont(name, path))
    pdfmetrics.registerFontFamily(
        "Pretendard",
        normal="Pretendard",
        bold="Pretendard-Bold",
    )
    _fonts_registered = True

    mpl_font = os.path.join(_ASSETS, "Pretendard-Regular.ttf")
    if os.path.exists(mpl_font):
        fm.fontManager.addfont(mpl_font)
        prop = fm.FontProperties(fname=mpl_font)
        matplotlib.rcParams["font.family"] = prop.get_name()
    matplotlib.rcParams["axes.unicode_minus"] = False


# ── Colors ───────────────────────────────────────────────────────────────────

_BG_DARK = colors.HexColor("#111111")
_BG_CARD = colors.HexColor("#1a1a1a")
_BG_CARD_ALT = colors.HexColor("#222222")
_BG_HEADER = colors.HexColor("#0d1117")
_TEXT_PRIMARY = colors.HexColor("#e6e6e6")
_TEXT_SECONDARY = colors.HexColor("#999999")
_TEXT_MUTED = colors.HexColor("#666666")
_GREEN = colors.HexColor("#34d399")
_GREEN_DIM = colors.HexColor("#065f46")
_RED = colors.HexColor("#f87171")
_RED_DIM = colors.HexColor("#7f1d1d")
_BLUE = colors.HexColor("#60a5fa")
_YELLOW = colors.HexColor("#fbbf24")
_ACCENT = colors.HexColor("#818cf8")
_DIVIDER = colors.HexColor("#2a2a2a")
_TABLE_HEADER_BG = colors.HexColor("#1e293b")
_TABLE_ROW_BG = colors.HexColor("#151515")
_TABLE_ROW_ALT = colors.HexColor("#1c1c1c")
_WHITE = colors.HexColor("#ffffff")

# ── Styles ───────────────────────────────────────────────────────────────────


def _build_styles():
    _register_fonts()
    s = {}
    s["title"] = ParagraphStyle(
        "Title", fontName="Pretendard-Bold", fontSize=22,
        textColor=_WHITE, leading=28, spaceAfter=2 * mm,
    )
    s["subtitle"] = ParagraphStyle(
        "Subtitle", fontName="Pretendard-Light", fontSize=10,
        textColor=_TEXT_SECONDARY, leading=14, spaceAfter=6 * mm,
    )
    s["section_title"] = ParagraphStyle(
        "SectionTitle", fontName="Pretendard-Bold", fontSize=13,
        textColor=_WHITE, leading=18, spaceBefore=4 * mm, spaceAfter=3 * mm,
    )
    s["card_title"] = ParagraphStyle(
        "CardTitle", fontName="Pretendard-SemiBold", fontSize=11,
        textColor=_GREEN, leading=15, spaceAfter=2 * mm,
    )
    s["body"] = ParagraphStyle(
        "Body", fontName="Pretendard", fontSize=8.5,
        textColor=_TEXT_PRIMARY, leading=13, spaceAfter=1.5 * mm,
    )
    s["body_light"] = ParagraphStyle(
        "BodyLight", fontName="Pretendard-Light", fontSize=8,
        textColor=_TEXT_SECONDARY, leading=12, spaceAfter=1 * mm,
    )
    s["headline"] = ParagraphStyle(
        "Headline", fontName="Pretendard-Medium", fontSize=9,
        textColor=_TEXT_PRIMARY, leading=14, spaceAfter=3 * mm,
        borderColor=_ACCENT, borderWidth=0, borderPadding=0,
    )
    s["table_header"] = ParagraphStyle(
        "TableHeader", fontName="Pretendard-SemiBold", fontSize=7.5,
        textColor=_TEXT_SECONDARY, leading=10, alignment=TA_CENTER,
    )
    s["table_cell"] = ParagraphStyle(
        "TableCell", fontName="Pretendard", fontSize=8,
        textColor=_TEXT_PRIMARY, leading=11, alignment=TA_CENTER,
    )
    s["table_cell_left"] = ParagraphStyle(
        "TableCellLeft", fontName="Pretendard-Medium", fontSize=8,
        textColor=_TEXT_PRIMARY, leading=11, alignment=TA_LEFT,
    )
    s["footer"] = ParagraphStyle(
        "Footer", fontName="Pretendard-Light", fontSize=7,
        textColor=_TEXT_MUTED, leading=9, alignment=TA_CENTER,
    )
    s["change_buy"] = ParagraphStyle(
        "ChangeBuy", fontName="Pretendard-Medium", fontSize=8,
        textColor=_GREEN, leading=12, spaceAfter=1 * mm,
    )
    s["change_sell"] = ParagraphStyle(
        "ChangeSell", fontName="Pretendard-Medium", fontSize=8,
        textColor=_RED, leading=12, spaceAfter=1 * mm,
    )
    s["change_neutral"] = ParagraphStyle(
        "ChangeNeutral", fontName="Pretendard", fontSize=8,
        textColor=_YELLOW, leading=12, spaceAfter=1 * mm,
    )
    return s


# ── Chart Generation (matplotlib → PNG buffer) ──────────────────────────────


def _make_returns_chart(returns_summary: list[dict]) -> io.BytesIO | None:
    if not returns_summary:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 0.35 * max(len(returns_summary), 3) + 0.6))
    fig.patch.set_facecolor("#111111")
    ax.set_facecolor("#1a1a1a")

    names = [r["name"][:20] for r in reversed(returns_summary)]
    daily = [r["daily_pct"] or 0 for r in reversed(returns_summary)]
    bar_colors = ["#34d399" if v >= 0 else "#f87171" for v in daily]

    bars = ax.barh(range(len(names)), daily, color=bar_colors, height=0.55,
                   edgecolor="none", zorder=3)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8, color="#e6e6e6")
    ax.tick_params(axis="x", colors="#999999", labelsize=7)
    ax.axvline(0, color="#444444", linewidth=0.5, zorder=2)
    ax.set_xlim(
        min(daily) - 0.5 if min(daily) < 0 else -0.3,
        max(daily) + 0.5 if max(daily) > 0 else 0.3,
    )

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#2a2a2a", linewidth=0.3, zorder=1)

    for i, (bar, val) in enumerate(zip(bars, daily)):
        label = f"{val:+.2f}%"
        x_pos = bar.get_width() + (0.08 if val >= 0 else -0.08)
        ha = "left" if val >= 0 else "right"
        ax.text(x_pos, i, label, fontsize=7.5, color="#e6e6e6", va="center", ha=ha,
                fontweight="medium")

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, facecolor="#111111",
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)
    return buf


def _make_period_comparison_chart(returns_summary: list[dict]) -> io.BytesIO | None:
    valid = [r for r in returns_summary
             if r.get("week_pct") is not None or r.get("month_pct") is not None]
    if not valid:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 0.5 * max(len(valid), 2) + 0.8))
    fig.patch.set_facecolor("#111111")
    ax.set_facecolor("#1a1a1a")

    names = [r["name"][:20] for r in valid]
    y_pos = range(len(names))
    bar_h = 0.25

    week_vals = [r.get("week_pct") or 0 for r in valid]
    month_vals = [r.get("month_pct") or 0 for r in valid]

    ax.barh([y - bar_h / 2 for y in y_pos], week_vals, height=bar_h,
            color="#60a5fa", label="Weekly", edgecolor="none", alpha=0.85)
    ax.barh([y + bar_h / 2 for y in y_pos], month_vals, height=bar_h,
            color="#818cf8", label="Monthly", edgecolor="none", alpha=0.85)

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(names, fontsize=8, color="#e6e6e6")
    ax.tick_params(axis="x", colors="#999999", labelsize=7)
    ax.axvline(0, color="#444444", linewidth=0.5, zorder=2)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#2a2a2a", linewidth=0.3, zorder=1)
    ax.legend(fontsize=7, loc="lower right", framealpha=0.3,
              facecolor="#1a1a1a", edgecolor="#333333",
              labelcolor="#e6e6e6")

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, facecolor="#111111",
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Page background ──────────────────────────────────────────────────────────


def _draw_page_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(_BG_DARK)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)

    # Footer
    canvas.setFont("Pretendard-Light", 7)
    canvas.setFillColor(_TEXT_MUTED)
    canvas.drawCentredString(
        A4[0] / 2, 10 * mm,
        f"ETF Daily Report — Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _strip_emoji(text: str) -> str:
    return re.sub(
        r'[\U0001F300-\U0001FAFF\U00002702-\U000027B0'
        r'\U0000FE00-\U0000FE0F\U0000200D]', '', text
    )


def _color_for_value(val: float | None) -> colors.HexColor:
    if val is None:
        return _TEXT_MUTED
    return _GREEN if val >= 0 else _RED


def _format_pct(val: float | None) -> str:
    if val is None:
        return "—"
    return f"{val:+.2f}%"


def _make_card_table(content_rows: list, col_widths: list, styles: dict) -> Table:
    """Wrap content rows in a styled card-like table."""
    t = Table(content_rows, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, -1), _BG_CARD),
        ("TEXTCOLOR", (0, 0), (-1, -1), _TEXT_PRIMARY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _DIVIDER),
    ]
    # Alternating row background
    for i in range(1, len(content_rows)):
        bg = _TABLE_ROW_ALT if i % 2 == 0 else _TABLE_ROW_BG
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    # Header row
    style_cmds.append(("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEADER_BG))

    t.setStyle(TableStyle(style_cmds))
    return t


_KNOWN_HEADINGS = {
    "오늘의 주요 변화", "운용 의도 분석", "주목할 점",
    "Today's Key Changes", "Manager Intent Analysis", "Key Takeaway",
}


def _parse_report_sections(report_text: str) -> list[tuple[str, str]]:
    """Parse report text into (heading, body) sections."""
    cleaned = _strip_emoji(report_text).replace("**", "")
    sections = []
    current_heading = ""
    current_body_lines = []

    for line in cleaned.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current_body_lines:
                current_body_lines.append("")
            continue

        if stripped.startswith("---"):
            current_body_lines.append(stripped)
            continue

        bare = stripped.lstrip("#").strip()
        is_heading = (
            stripped.startswith("#")
            or bare in _KNOWN_HEADINGS
            or (len(bare) < 20 and not bare.endswith((".", "다", "음"))
                and not bare.startswith(("-", "▲", "▼", "•", "·"))
                and bare.endswith(("변화", "분석", "점", "Changes", "Analysis", "Takeaway")))
        )

        if is_heading:
            if current_heading or current_body_lines:
                sections.append((current_heading, "\n".join(current_body_lines).strip()))
            current_heading = bare
            current_body_lines = []
        else:
            current_body_lines.append(stripped)

    if current_heading or current_body_lines:
        sections.append((current_heading, "\n".join(current_body_lines).strip()))

    return sections


# ── Public API ───────────────────────────────────────────────────────────────


def generate_daily_pdf(
    date_str: str,
    headline: str,
    returns_summary: list[dict],
    report_sections: list[tuple],
) -> str:
    _register_fonts()
    styles = _build_styles()
    path = os.path.join(tempfile.gettempdir(), f"etf_report_{date_str}.pdf")

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
    )

    story = []
    usable_width = A4[0] - 30 * mm

    # ── Cover / Title ────────────────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("ETF Daily Report", styles["title"]))
    story.append(Paragraph(
        f"{date_str} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Generated {datetime.now().strftime('%H:%M KST')}",
        styles["subtitle"],
    ))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=_DIVIDER, spaceAfter=5 * mm,
    ))

    # ── Headline ─────────────────────────────────────────────────────────────
    if headline:
        story.append(Paragraph("MARKET HEADLINE", styles["section_title"]))
        headline_clean = _strip_emoji(headline).replace("**", "")
        for line in headline_clean.split("\n"):
            line = line.strip().lstrip("#").strip()
            if line and line != "---":
                story.append(Paragraph(line, styles["headline"]))
        story.append(Spacer(1, 3 * mm))

    # ── Returns Table ────────────────────────────────────────────────────────
    if returns_summary:
        story.append(Paragraph("PERFORMANCE OVERVIEW", styles["section_title"]))

        # Chart
        chart_buf = _make_returns_chart(returns_summary)
        if chart_buf:
            img = Image(chart_buf, width=usable_width,
                        height=min(10 * mm * len(returns_summary) + 12 * mm, 90 * mm))
            story.append(img)
            story.append(Spacer(1, 4 * mm))

        # Table
        header_row = [
            Paragraph("ETF", styles["table_header"]),
            Paragraph("Close", styles["table_header"]),
            Paragraph("Daily", styles["table_header"]),
            Paragraph("Weekly", styles["table_header"]),
            Paragraph("Monthly", styles["table_header"]),
        ]
        data_rows = [header_row]
        col_widths = [usable_width * 0.36, usable_width * 0.16,
                      usable_width * 0.16, usable_width * 0.16, usable_width * 0.16]

        for r in returns_summary:
            name = f"{r['name'][:18]} ({r.get('ticker', '')})"
            daily_color = _color_for_value(r.get("daily_pct"))
            week_color = _color_for_value(r.get("week_pct"))
            month_color = _color_for_value(r.get("month_pct"))

            data_rows.append([
                Paragraph(name, styles["table_cell_left"]),
                Paragraph(f"{r['close']:.2f}", styles["table_cell"]),
                Paragraph(
                    f"<font color='{daily_color.hexval()}'>{_format_pct(r.get('daily_pct'))}</font>",
                    styles["table_cell"],
                ),
                Paragraph(
                    f"<font color='{week_color.hexval()}'>{_format_pct(r.get('week_pct'))}</font>",
                    styles["table_cell"],
                ),
                Paragraph(
                    f"<font color='{month_color.hexval()}'>{_format_pct(r.get('month_pct'))}</font>",
                    styles["table_cell"],
                ),
            ])

        table = _make_card_table(data_rows, col_widths, styles)
        story.append(table)
        story.append(Spacer(1, 3 * mm))

        # Period comparison chart
        period_chart = _make_period_comparison_chart(returns_summary)
        if period_chart:
            story.append(Spacer(1, 2 * mm))
            period_h = min(12 * mm * len(returns_summary) + 15 * mm, 80 * mm)
            img2 = Image(period_chart, width=usable_width, height=period_h)
            story.append(img2)

    # ── ETF Detail Sections ──────────────────────────────────────────────────
    active_sections = [s for s in report_sections if "변화 없음" not in s[2][:200]]
    if active_sections:
        story.append(PageBreak())
        story.append(Paragraph("ETF ANALYSIS", styles["section_title"]))
        story.append(HRFlowable(
            width="100%", thickness=0.5,
            color=_DIVIDER, spaceAfter=4 * mm,
        ))

        for idx, section in enumerate(active_sections):
            name, ticker = section[0], section[1]
            report = section[2]
            ref_date = section[3] if len(section) > 3 else None

            label = f"{name} ({ticker})"
            if ref_date:
                label += f" &nbsp;—&nbsp; data as of {ref_date}"

            section_elements = []
            section_elements.append(Paragraph(label, styles["card_title"]))

            parsed = _parse_report_sections(report)
            if parsed:
                for heading, body in parsed:
                    if heading:
                        section_elements.append(Paragraph(
                            heading,
                            ParagraphStyle(
                                "SubHeading", parent=styles["body"],
                                fontName="Pretendard-SemiBold", fontSize=8.5,
                                textColor=_BLUE, spaceBefore=2 * mm, spaceAfter=1 * mm,
                            ),
                        ))
                    if body:
                        for line in body.split("\n"):
                            line = line.strip()
                            if not line:
                                section_elements.append(Spacer(1, 1.5 * mm))
                                continue
                            if line.startswith("---"):
                                section_elements.append(Spacer(1, 1 * mm))
                                section_elements.append(HRFlowable(
                                    width="40%", thickness=0.3,
                                    color=_DIVIDER, spaceAfter=1 * mm,
                                ))
                                continue

                            if line.startswith(("▲", "▼", "🔼", "🔻")):
                                if "▲" in line or "🔼" in line or "편입" in line:
                                    st = styles["change_buy"]
                                elif "▼" in line or "🔻" in line or "청산" in line:
                                    st = styles["change_sell"]
                                else:
                                    st = styles["change_neutral"]
                                section_elements.append(Paragraph(
                                    _strip_emoji(line), st,
                                ))
                            elif line.startswith(("-", "•", "·")):
                                section_elements.append(Paragraph(
                                    f"&nbsp;&nbsp;{line}", styles["body"],
                                ))
                            else:
                                section_elements.append(Paragraph(
                                    line, styles["body"],
                                ))
            else:
                cleaned = _strip_emoji(report).replace("**", "")
                for line in cleaned.split("\n"):
                    line = line.strip()
                    if line:
                        section_elements.append(Paragraph(line, styles["body"]))

            section_elements.append(Spacer(1, 2 * mm))
            section_elements.append(HRFlowable(
                width="100%", thickness=0.3,
                color=_DIVIDER, spaceAfter=4 * mm,
            ))

            story.append(KeepTogether(section_elements[:6]))
            story.extend(section_elements[6:])

    # ── Build ────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_draw_page_bg, onLaterPages=_draw_page_bg)
    logger.info("PDF report generated: %s", path)
    return path
