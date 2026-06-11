import io
import logging
import os
import tempfile
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.backends.backend_pdf import PdfPages

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
]
_font_prop = None
for _p in _FONT_CANDIDATES:
    if os.path.exists(_p):
        _font_prop = fm.FontProperties(fname=_p)
        matplotlib.rcParams["font.family"] = _font_prop.get_name()
        break
if _font_prop is None:
    matplotlib.rcParams["font.family"] = "sans-serif"

matplotlib.rcParams["axes.unicode_minus"] = False

_BG = "#1a1a1a"
_CARD_BG = "#242424"
_TEXT = "#e0e0e0"
_MUTED = "#888888"
_GREEN = "#4DB674"
_RED = "#c0392b"
_COLORS = ["#4DB674", "#E07C5A", "#7BA7BC", "#D4A574", "#5B8C85", "#C17B8E"]


def generate_daily_pdf(
    date_str: str,
    headline: str,
    returns_summary: list[dict],
    report_sections: list[tuple],
) -> str:
    path = os.path.join(tempfile.gettempdir(), f"etf_report_{date_str}.pdf")

    with PdfPages(path) as pdf:
        _page_overview(pdf, date_str, headline, returns_summary)
        if report_sections:
            _page_etf_details(pdf, date_str, report_sections)

    logger.info("PDF report generated: %s", path)
    return path


def _page_overview(pdf, date_str, headline, returns_summary):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor=_BG)

    # Title
    fig.text(0.05, 0.95, f"ETF 일일 보고서  {date_str}",
             fontsize=16, fontweight="bold", color=_TEXT, fontproperties=_font_prop)

    if headline:
        wrapped = _wrap_text(_strip_emoji(headline), 70)
        fig.text(0.05, 0.91, "시장 헤드라인",
                 fontsize=10, fontweight="bold", color=_GREEN, fontproperties=_font_prop)
        fig.text(0.05, 0.895, wrapped,
                 fontsize=8, color=_MUTED, fontproperties=_font_prop,
                 verticalalignment="top", linespacing=1.6)

    if not returns_summary:
        pdf.savefig(fig, facecolor=_BG)
        plt.close(fig)
        return

    # Returns bar chart
    ax = fig.add_axes([0.08, 0.58, 0.85, 0.25])
    ax.set_facecolor(_CARD_BG)

    names = [r["name"][:12] for r in returns_summary]
    daily = [r["daily_pct"] or 0 for r in returns_summary]
    colors = [_GREEN if v >= 0 else _RED for v in daily]

    bars = ax.barh(range(len(names)), daily, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=7, color=_TEXT, fontproperties=_font_prop)
    ax.set_xlabel("일간 수익률 (%)", fontsize=7, color=_MUTED, fontproperties=_font_prop)
    ax.tick_params(axis="x", colors=_MUTED, labelsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(_MUTED)
    ax.spines["left"].set_color(_MUTED)
    ax.axvline(0, color=_MUTED, linewidth=0.5)

    for i, (bar, val) in enumerate(zip(bars, daily)):
        label = f"{val:+.2f}%"
        x_pos = bar.get_width() + (0.05 if val >= 0 else -0.05)
        ha = "left" if val >= 0 else "right"
        ax.text(x_pos, i, label, fontsize=6.5, color=_TEXT, va="center", ha=ha,
                fontproperties=_font_prop)

    ax.invert_yaxis()
    ax.set_title("일간 수익률", fontsize=9, color=_TEXT, fontweight="bold",
                 fontproperties=_font_prop, loc="left", pad=10)

    # Returns table
    table_y = 0.52
    fig.text(0.05, table_y, "ETF 수익률 현황",
             fontsize=10, fontweight="bold", color=_TEXT, fontproperties=_font_prop)

    headers = ["ETF", "현재가", "일간", "주간", "월간"]
    col_x = [0.05, 0.40, 0.55, 0.70, 0.85]

    header_y = table_y - 0.025
    for x, h in zip(col_x, headers):
        fig.text(x, header_y, h, fontsize=7, fontweight="bold", color=_MUTED,
                 fontproperties=_font_prop)

    for i, r in enumerate(returns_summary):
        y = header_y - 0.022 * (i + 1)
        name = f"{r['name'][:14]} ({r['ticker']})"
        fig.text(col_x[0], y, name, fontsize=6.5, color=_TEXT, fontproperties=_font_prop)
        fig.text(col_x[1], y, f"{r['close']:.2f}", fontsize=6.5, color=_TEXT,
                 fontproperties=_font_prop)

        for j, key in enumerate(["daily_pct", "week_pct", "month_pct"]):
            val = r.get(key)
            if val is not None:
                color = _GREEN if val >= 0 else _RED
                fig.text(col_x[2 + j], y, f"{val:+.2f}%", fontsize=6.5, color=color,
                         fontproperties=_font_prop)
            else:
                fig.text(col_x[2 + j], y, "—", fontsize=6.5, color=_MUTED,
                         fontproperties=_font_prop)

    pdf.savefig(fig, facecolor=_BG)
    plt.close(fig)


def _page_etf_details(pdf, date_str, report_sections):
    sections_per_page = 3
    for page_start in range(0, len(report_sections), sections_per_page):
        page_sections = report_sections[page_start:page_start + sections_per_page]
        fig = plt.figure(figsize=(8.27, 11.69), facecolor=_BG)

        fig.text(0.05, 0.96, f"ETF 상세 분석  {date_str}",
                 fontsize=12, fontweight="bold", color=_TEXT, fontproperties=_font_prop)

        y_cursor = 0.92
        section_height = 0.28

        for idx, section in enumerate(page_sections):
            name, ticker = section[0], section[1]
            report = section[2]
            ref_date = section[3] if len(section) > 3 else None

            label = f"{name} ({ticker})"
            if ref_date:
                label += f"  데이터 기준: {ref_date}"

            fig.text(0.05, y_cursor, label,
                     fontsize=9, fontweight="bold", color=_GREEN, fontproperties=_font_prop)

            cleaned = _strip_emoji(report).replace("**", "")
            wrapped = _wrap_text(cleaned, 85)
            lines = wrapped.split("\n")[:14]
            truncated = "\n".join(lines)

            fig.text(0.05, y_cursor - 0.015, truncated,
                     fontsize=6, color=_TEXT, fontproperties=_font_prop,
                     verticalalignment="top", linespacing=1.5)

            y_cursor -= section_height

        pdf.savefig(fig, facecolor=_BG)
        plt.close(fig)


def _strip_emoji(text: str) -> str:
    import re
    return re.sub(r'[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0000200D]', '', text)


def _wrap_text(text: str, width: int) -> str:
    text = _strip_emoji(text)
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            current += char
            if len(current) >= width and char in (" ", ",", ".", ")", "—"):
                lines.append(current)
                current = ""
        if current:
            lines.append(current)
    return "\n".join(lines)
