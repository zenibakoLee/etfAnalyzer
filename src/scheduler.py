import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Callable, Awaitable

import pytz
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src import database as db, scraper, analyzer
from src.comic import generate_comic
from src.config import SCHEDULE_HOUR, SCHEDULE_MINUTE
from src.pdf_report import generate_daily_pdf

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

BACKFILL_START = date(2023, 5, 16)
_BACKFILL_DELAY = 0.5  # seconds between requests


def _market_for_etf(etf: dict) -> str:
    yf = etf.get("yf_ticker") or ""
    return "KR" if yf.endswith((".KS", ".KQ")) else "US"


_CONSENSUS_TUNNEL = "/Users/haejoonlee/dev/investmentConsensus/logs/tunnel-url.txt"
_CONSENSUS_DB = "/Users/haejoonlee/dev/investmentConsensus/db/consensus.db"


def _dashboard_link() -> str:
    """ETF insights live on the investmentConsensus dashboard (/etf)."""
    try:
        url = open(_CONSENSUS_TUNNEL).read().strip()
        return f"{url}/etf" if url else ""
    except OSError:
        return ""


def _leverage_stage_change() -> str:
    """investmentConsensus의 레버리지 사이클 단계 전환 감지 (read-only).

    Tech Cycle Score가 매일 계산하는 leverage_daily.stage의 최근 이틀을 비교해
    단계가 바뀐 경우에만 리포트 라인을 반환한다.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{_CONSENSUS_DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT date, stage FROM leverage_daily WHERE stage IS NOT NULL ORDER BY date DESC LIMIT 2"
        ).fetchall()
        conn.close()
    except Exception:
        logger.exception("leverage stage check failed")
        return ""
    if len(rows) < 2:
        return ""
    (cur_date, cur_stage), (_, prev_stage) = rows
    if cur_stage == prev_stage:
        return ""
    guide = {
        "축적기": "레버리지가 빠르게 쌓이는 중 — 과열 경계",
        "청산 초기": "강제청산 진행 — 추가 변동성 주의",
        "청산 후반": "레버리지 대부분 정리 — 횡보 후 수급 회복 가능 구간",
        "정상화": "레버리지·변동성 안정 — 정상 배분",
        "혼조": "지표 혼재 — 단계 전환 구간일 가능성",
    }.get(cur_stage, "")
    try:
        base = open(_CONSENSUS_TUNNEL).read().strip()
        link = f"\n   → {base}/cycle" if base else ""
    except OSError:
        link = ""
    return (
        f"\n🧨 **레버리지 사이클 단계 전환** ({cur_date}): {prev_stage} → **{cur_stage}**\n"
        f"   {guide}{link}"
    )


def _cycle_rotation_change() -> str:
    """investmentConsensus 경기사이클(biz_cycle_daily)의 국가별 선호업종/대장주 전환 감지.

    각국 증시 사이클 위상이 바뀌면 선호 업종(favored_with_leaders)의 선두가 교체된다.
    최근 이틀 payload를 비교해 선두 업종·대장주가 바뀐 나라만 리포트한다.
    """
    import sqlite3
    import json

    try:
        conn = sqlite3.connect(f"file:{_CONSENSUS_DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT date, payload_json FROM biz_cycle_daily ORDER BY date DESC LIMIT 2"
        ).fetchall()
        conn.close()
    except Exception:
        logger.exception("cycle rotation check failed")
        return ""
    if len(rows) < 2:
        return ""

    def _lead(payload_json):
        """{country_label: (증시국면, 선두업종, 대장주)}"""
        out = {}
        try:
            data = json.loads(payload_json)
        except Exception:
            return out
        for c in (data.get("countries") or {}).values():
            eq = c.get("equity") or {}
            leaders = eq.get("favored_with_leaders") or []
            if leaders:
                out[f"{c.get('flag', '')} {c.get('label', '')}"] = (
                    eq.get("quadrant", ""), leaders[0].get("sector", ""), leaders[0].get("leader", ""),
                )
        return out

    cur_date, cur_payload = rows[0]
    cur, prev = _lead(cur_payload), _lead(rows[1][1])

    changes = []
    for country, (quadrant, sector, leader) in cur.items():
        prev_entry = prev.get(country)
        if prev_entry and prev_entry[1] != sector:
            leader_str = f" · {leader}" if leader else ""
            changes.append(f"   {country}: {prev_entry[1]} → **{sector}**{leader_str} ({quadrant})")
    if not changes:
        return ""

    try:
        base = open(_CONSENSUS_TUNNEL).read().strip()
        link = f"\n   → {base}/rotation" if base else ""
    except OSError:
        link = ""
    return (
        f"\n🔄 **증시사이클 선호업종 전환** ({cur_date})\n"
        + "\n".join(changes)
        + link
    )


_EXCHANGE_CALENDARS: dict[str, object] = {}

_YF_BENCHMARK = {"US": "SPY", "KR": "005930.KS"}


def _get_exchange_cal(market: str):
    import exchange_calendars as xcals
    if market not in _EXCHANGE_CALENDARS:
        code = "XKRX" if market == "KR" else "XNYS"
        _EXCHANGE_CALENDARS[market] = xcals.get_calendar(code)
    return _EXCHANGE_CALENDARS[market]


def _check_cal_closed(market: str, check_date: date) -> bool:
    try:
        return not _get_exchange_cal(market).is_session(check_date)
    except Exception:
        logger.exception("exchange_calendars check failed for %s", market)
        return False


def _check_yf_closed(market: str, check_date: date) -> bool:
    import yfinance as yf
    ticker = _YF_BENCHMARK[market]
    try:
        hist = yf.Ticker(ticker).history(
            start=str(check_date),
            end=str(check_date + timedelta(days=1)),
        )
        return hist.empty
    except Exception:
        logger.exception("yfinance check failed for %s (%s)", market, ticker)
        return False


def _web_verify_market(market: str, check_date: date) -> bool | None:
    from bs4 import BeautifulSoup
    market_name = "NYSE" if market == "US" else "KRX Korea Exchange"
    date_str = check_date.strftime("%Y-%m-%d")
    date_long = check_date.strftime("%B %d, %Y")
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{market_name} stock market holiday closed {date_str}"},
            headers={"User-Agent": scraper.HEADERS["User-Agent"]},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        snippets = " ".join(r.get_text() for r in soup.select(".result__snippet, .result__title"))
        snippets_lower = snippets.lower()
        closed_kw = ["holiday", "closed", "market close", "휴장", "공휴일"]
        open_kw = ["open", "trading", "개장"]
        has_date = date_str in snippets or date_long.lower() in snippets_lower
        closed_hits = sum(1 for w in closed_kw if w in snippets_lower)
        open_hits = sum(1 for w in open_kw if w in snippets_lower)
        if has_date and closed_hits > open_hits:
            return True
        if has_date and open_hits > closed_hits:
            return False
        return None
    except Exception:
        logger.exception("Web verification failed for %s on %s", market, check_date)
        return None


def _detect_closed_markets(today: date) -> set[str]:
    """A market is 'closed' when the previous calendar day had no session.

    The 08:00 KST report analyzes the previous day's trading. Weekends count as
    closed — checking the previous *weekday* instead would make Sunday/Monday
    runs compare stale Friday data against itself and narrate '변화 없음' as if
    the manager chose to hold.

    Primary source: Toss Securities official market calendar. Fallback:
    exchange_calendars + yfinance + web verification.
    """
    closed = set()
    for market in ("KR", "US"):
        # Official calendar first — authoritative for both KR and US
        try:
            from src import toss_api
            toss_result = toss_api.was_previous_day_session(market, today)
        except Exception:
            toss_result = None
        if toss_result is not None:
            if not toss_result:
                closed.add(market)
                logger.info("Market %s closed on %s (Toss official calendar)", market, today - timedelta(days=1))
            continue

        prev_bday = today - timedelta(days=1)
        if prev_bday.weekday() >= 5:
            closed.add(market)
            logger.info("Market %s: %s is a weekend — no new session to analyze", market, prev_bday)
            continue

        cal_closed = _check_cal_closed(market, prev_bday)
        yf_closed = _check_yf_closed(market, prev_bday)

        if cal_closed == yf_closed:
            if cal_closed:
                closed.add(market)
                logger.info("Market %s closed on %s (calendar + yfinance agree)", market, prev_bday)
            continue

        logger.warning(
            "Market %s on %s: calendar=%s, yfinance=%s — running web verification",
            market, prev_bday,
            "closed" if cal_closed else "open",
            "closed" if yf_closed else "open",
        )
        web_result = _web_verify_market(market, prev_bday)
        if web_result is True:
            closed.add(market)
            logger.info("Market %s closed on %s (web verified)", market, prev_bday)
        elif web_result is False:
            logger.info("Market %s open on %s (web verified)", market, prev_bday)
        else:
            if cal_closed:
                closed.add(market)
            logger.info(
                "Market %s on %s: web inconclusive, trusting exchange_calendars (%s)",
                market, prev_bday, "closed" if cal_closed else "open",
            )
    return closed


async def run_daily_job(send_fn: Callable[..., Awaitable]):
    today = datetime.now(KST).date()
    today_str = str(today)

    # Idempotency: skip if today's report was already generated
    latest_market = db.get_latest_market_insight()
    if latest_market and latest_market["date"] == today_str:
        logger.info("Daily report already generated today, skipping")
        return

    logger.info(f"Daily job started for {today_str}")

    etfs = db.get_all_etfs()
    all_changes = []
    report_sections = []
    scrape_failures = []

    # ── Collect daily returns FIRST (needed for market context) ──────────
    returns_summary = await _collect_daily_returns(etfs, today_str)
    market_returns = _build_market_returns_context(etfs)

    # ── Detect closed markets and filter ─────────────────────────────────
    closed_markets = _detect_closed_markets(today)
    if closed_markets:
        logger.info("Closed markets: %s — skipping those ETFs", closed_markets)
        etf_market_map = {dict(e)["ticker"]: _market_for_etf(dict(e)) for e in etfs}
        returns_summary = [r for r in returns_summary if etf_market_map.get(r["ticker"], "US") not in closed_markets]
        if "US" in closed_markets:
            market_returns = ""

    if {"KR", "US"} <= closed_markets:
        prev_day = today - timedelta(days=1)
        reason = "주말" if prev_day.weekday() >= 5 else "휴장일"
        # Save marker so the 09:00 recovery check doesn't re-send this notice
        db.save_market_insight(today_str, f"{reason} — 신규 거래 데이터 없음, 보고서 생략")
        await send_fn(
            f"📅 **{today_str} ETF 일일 보고서**\n"
            f"전일({prev_day})은 {reason}로 한국·미국 시장 모두 거래가 없었습니다. "
            f"분석할 신규 데이터가 없어 오늘 보고서는 생략합니다."
        )
        logger.info("All markets closed — holiday notice sent, skipping report")
        return

    for etf in etfs:
        etf = dict(etf)
        if etf.get("benchmark"):
            continue
        if _market_for_etf(etf) in closed_markets:
            logger.info("Skipping %s — %s market closed", etf["name"], _market_for_etf(etf))
            continue
        try:
            # ── Backfill missing dates before today ───────────────────────
            await _backfill_gaps(etf, today)

            # ── Scrape today ──────────────────────────────────────────────
            data = scraper.fetch_holdings(etf["url"], today, yf_ticker=etf.get("yf_ticker"))
            if not data:
                db.save_no_data_date(etf["id"], today_str)
                logger.info(f"No data for {etf['name']} on {today_str}, trying latest snapshots")
                scrape_failures.append({"name": etf["name"], "ticker": etf["ticker"], "reason": "데이터 없음 (폴백 사용)"})
                # Fallback: generate report from most recent 2 snapshots
                await _report_from_latest_snapshots(etf, today_str, report_sections)
                continue

            db.save_snapshot(etf["id"], today_str, data["aum_100m"], data["holdings"])
            today_snap = db.get_snapshot(etf["id"], today_str)
            prev_snap = db.get_prev_snapshot(etf["id"], today_str)

            if not prev_snap:
                logger.info(f"No previous snapshot for {etf['name']}, skipping analysis")
                continue

            today_holdings = db.get_holdings(today_snap["id"])
            prev_holdings = db.get_holdings(prev_snap["id"])

            # ── Analyze ──────────────────────────────────────────────────────
            changes = analyzer.analyze_changes(
                etf["name"], today_str,
                today_snap, prev_snap,
                today_holdings, prev_holdings,
            )
            all_changes.append(changes)

            # ── ETF report ───────────────────────────────────────────────────
            prev_insight_row = db.get_latest_insight(etf["id"])
            prev_insight = prev_insight_row["insight_text"] if prev_insight_row else ""
            etf_report = analyzer.generate_etf_report(changes, prev_insight, market_returns=market_returns)
            db.save_daily_report(etf["id"], today_str, etf_report)
            report_sections.append((etf["name"], etf["ticker"], etf_report))

        except Exception as exc:
            logger.exception(f"Error processing ETF {etf['name']}")
            scrape_failures.append({"name": etf["name"], "ticker": etf["ticker"], "reason": str(exc)[:80]})

    # ── Data health check + auto-recovery ────────────────────────────────
    health_alerts = await _check_data_health(etfs, today_str)

    if not report_sections:
        if returns_summary or health_alerts:
            msg = _build_returns_only_message(today_str, returns_summary) if returns_summary else f"📅 **{today_str} ETF 일일 보고서**"
            if health_alerts:
                msg += "\n" + _format_health_alerts(health_alerts)
            await send_fn(msg)
        else:
            logger.info("No report sections today — nothing to send")
        return

    # ── Market headline ───────────────────────────────────────────────────────
    headline = ""
    if all_changes:
        headline = analyzer.generate_market_headline(all_changes, market_returns=market_returns)
        db.save_market_insight(today_str, headline)

    # ── Generate PDF + comic + compact Discord summary ─────────────────────
    try:
        pdf_path = generate_daily_pdf(today_str, headline, returns_summary, report_sections)
    except Exception:
        logger.exception("PDF generation failed, falling back to text-only")
        pdf_path = None

    comic_data = _build_comic_data(today_str, headline, returns_summary, report_sections)
    comic_path = generate_comic(comic_data, today_str)

    compact = _build_compact_message(today_str, headline, returns_summary, report_sections, health_alerts, scrape_failures)
    extra_files = [comic_path] if comic_path else None
    await send_fn(compact, pdf_path, extra_files=extra_files)
    logger.info("Daily report sent")


def _build_all_changes(etf: dict) -> list:
    snapshots = db.get_all_snapshots(etf["id"])
    if len(snapshots) < 2:
        return []

    changes_list = []
    for i in range(1, len(snapshots)):
        today_snap = snapshots[i]
        prev_snap = snapshots[i - 1]
        today_h = db.get_holdings(today_snap["id"])
        prev_h = db.get_holdings(prev_snap["id"])
        changes_list.append(
            analyzer.analyze_changes(
                etf["name"], today_snap["date"],
                today_snap, prev_snap,
                today_h, prev_h,
            )
        )
    return changes_list


def _build_message(date_str: str, headline: str, sections: list, returns_summary: list | None = None) -> str:
    parts = [f"📅 **{date_str} ETF 일일 보고서**\n"]

    if headline:
        parts.append("🌐 **오늘의 시장 헤드라인**")
        parts.append(headline)
        parts.append("\n━━━━━━━━━━━━━━━━━━━━━")

    if returns_summary:
        parts.append("\n📈 **ETF 수익률 현황**")
        parts.append(_format_returns_table(returns_summary))
        parts.append("━━━━━━━━━━━━━━━━━━━━━")

    for section in sections:
        name, ticker, report = section[0], section[1], section[2]
        ref_date = section[3] if len(section) > 3 else None
        label = f"\n📊 **{name}** ({ticker})"
        if ref_date:
            label += f" _(데이터 기준: {ref_date})_"
        parts.append(label)
        parts.append(report)
        parts.append("━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(parts)


_SKIP_SECTION_HEADERS = ("오늘의 주요 변화", "운용 의도 분석", "핵심 요약", "날짜:", "베이스라인:")


def _extract_key_line(report: str) -> str:
    """First substantive line of an LLM report for the compact Discord summary.

    LLM output format varies — some reports open with markdown headings
    ('## TIME 나스닥100 — 분석') or bold metadata, which are useless as a
    one-line summary. Skip structural markup and known section headers;
    bold *content* lines (e.g. '**대규모 리밸런싱 — 신규 49종목**') are kept.
    """
    for line in report.split("\n"):
        stripped = line.strip()
        if not stripped or len(stripped) <= 5:
            continue
        if stripped.startswith(("#", "---", "|", "```", ">")):
            continue
        plain = stripped.strip("*").strip()
        if len(plain) <= 5:
            continue
        if any(h in plain[:25] for h in _SKIP_SECTION_HEADERS):
            continue
        return _truncate_to_sentence(plain, 120)
    return ""


def _truncate_to_sentence(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    for sep in ("다. ", "다.\n", ". ", ".\n"):
        idx = text.rfind(sep, 0, max_len)
        if idx != -1:
            return text[: idx + len(sep) - 1].rstrip()
    return text[:max_len].rstrip() + "…"


def _etf_short_name(name: str, ticker: str) -> str:
    short_map = {
        "456600": "글로벌AI",
        "426030": "나스닥100",
        "385720": "코스피",
    }
    return short_map.get(ticker, ticker)


def _build_compact_message(
    date_str: str, headline: str, returns_summary: list | None, sections: list,
    health_alerts: list | None = None, scrape_failures: list | None = None,
) -> str:
    """Discord-friendly compact summary (single message, < 1900 chars)."""
    parts = [f"📅 **{date_str} ETF 일일 보고서**"]

    if headline:
        short_headline = _truncate_to_sentence(headline.split("\n")[0], 300)
        parts.append(f"🌐 {short_headline}")

    if returns_summary:
        parts.append("")
        for r in returns_summary:
            arrow = "🔺" if r["daily_pct"] and r["daily_pct"] > 0 else "🔻" if r["daily_pct"] and r["daily_pct"] < 0 else "➖"
            daily = f"{r['daily_pct']:+.2f}%" if r["daily_pct"] is not None else "N/A"
            label = _etf_short_name(r["name"], r["ticker"])
            parts.append(f"{arrow} **{label}** ({r['ticker']}) {r['close']:.0f} | {daily}")

    changed_sections = [
        s for s in sections
        if "변화 없음" not in s[2][:200]
    ]
    if changed_sections:
        parts.append("\n📊 **ETF별 핵심 변화**")
        for section in changed_sections:
            name, ticker, report = section[0], section[1], section[2]
            label = _etf_short_name(name, ticker)
            first_line = _extract_key_line(report)
            if first_line:
                parts.append(f"• **{label}** ({ticker}): {first_line}")

    lev_change = _leverage_stage_change()
    if lev_change:
        parts.append(lev_change)

    rotation_change = _cycle_rotation_change()
    if rotation_change:
        parts.append(rotation_change)

    if scrape_failures:
        parts.append("\n🚨 **크롤링 실패**")
        for f in scrape_failures:
            label = _etf_short_name(f["name"], f["ticker"])
            parts.append(f"• **{label}** ({f['ticker']}): {f['reason']}")

    if health_alerts:
        parts.append(_format_health_alerts(health_alerts))

    parts.append("\n📎 상세 분석은 첨부 PDF를 확인하세요.")
    dash = _dashboard_link()
    if dash:
        parts.append(f"📊 대시보드: {dash}")
    return "\n".join(parts)


def _build_comic_data(
    date_str: str, headline: str,
    returns_summary: list | None, sections: list,
) -> str:
    parts = [f"{date_str} ETF 일일 보고서\n"]
    if headline:
        parts.append(f"시장 헤드라인: {headline}\n")
    if returns_summary:
        parts.append("ETF 수익률:")
        for r in returns_summary:
            daily = f"{r['daily_pct']:+.2f}%" if r["daily_pct"] is not None else "N/A"
            parts.append(f"  {r['ticker']}: {daily}")
        parts.append("")
    for section in sections:
        if "변화 없음" in section[2][:200]:
            continue
        parts.append(f"[{section[0]} ({section[1]})]")
        parts.append(section[2][:500])
        parts.append("")
    return "\n".join(parts)


def _build_returns_only_message(date_str: str, returns_summary: list) -> str:
    parts = [f"📅 **{date_str} ETF 수익률 현황**\n"]
    parts.append(_format_returns_table(returns_summary))
    dash = _dashboard_link()
    if dash:
        parts.append(f"\n📊 대시보드: {dash}")
    return "\n".join(parts)


def _format_returns_table(returns_summary: list) -> str:
    lines = []
    for r in returns_summary:
        arrow = "🔺" if r["daily_pct"] and r["daily_pct"] > 0 else "🔻" if r["daily_pct"] and r["daily_pct"] < 0 else "➖"
        daily = f"{r['daily_pct']:+.2f}%" if r["daily_pct"] is not None else "N/A"
        w1 = f"{r['week_pct']:+.2f}%" if r.get("week_pct") is not None else "—"
        m1 = f"{r['month_pct']:+.2f}%" if r.get("month_pct") is not None else "—"
        lines.append(f"{arrow} **{r['name']}** ({r['ticker']}): {r['close']:.2f} | 일간 {daily} | 주간 {w1} | 월간 {m1}")
    return "\n".join(lines)


async def _collect_daily_returns(etfs: list, today_str: str) -> list[dict]:
    """Fetch and store daily returns for all ETFs with yf_ticker."""
    summary = []
    for etf in etfs:
        etf = dict(etf)
        yf_ticker = etf.get("yf_ticker")
        if not yf_ticker:
            continue
        try:
            existing = db.get_returns(etf["id"], days=1)
            fetch_period = "2y" if not existing else "1mo"
            returns = scraper.fetch_etf_returns(yf_ticker, period=fetch_period)
            if returns:
                db.save_returns(etf["id"], returns)
                latest = returns[-1]
                week_pct = _calc_period_return(returns, 5)
                month_pct = _calc_period_return(returns, 20)
                summary.append({
                    "name": etf["name"],
                    "ticker": etf["ticker"],
                    "close": latest["close_price"],
                    "daily_pct": latest["daily_return_pct"],
                    "week_pct": week_pct,
                    "month_pct": month_pct,
                })
        except Exception:
            logger.exception("Returns collection failed for %s", etf["name"])
    return summary


def _calc_period_return(returns: list[dict], days: int) -> float | None:
    if len(returns) < days + 1:
        return None
    start = returns[-(days + 1)]["close_price"]
    end = returns[-1]["close_price"]
    if start == 0:
        return None
    return round(((end / start) - 1) * 100, 4)


def _build_market_returns_context(etfs: list) -> str:
    """Build a text summary of benchmark ETF returns for LLM context."""
    lines = []
    for etf in etfs:
        etf = dict(etf)
        if not etf.get("benchmark"):
            continue
        ret = db.get_latest_return(etf["id"])
        if ret and ret["daily_return_pct"] is not None:
            lines.append(f"- {etf['name']} ({etf['ticker']}): {ret['date']} 종가 기준 일간 {ret['daily_return_pct']:+.2f}%")
    if not lines:
        return ""
    return "전일 미국 시장 실제 수익률 (yfinance 기준):\n" + "\n".join(lines)


async def _report_from_latest_snapshots(etf: dict, today_str: str, report_sections: list):
    """Generate a report from the two most recent snapshots when today's data is unavailable."""
    snapshots = db.get_all_snapshots(etf["id"])
    if len(snapshots) < 2:
        return

    latest_snap = dict(snapshots[-1])
    prev_snap = dict(snapshots[-2])
    ref_date = latest_snap["date"]

    # Skip if already generated a report for today
    existing = db.get_latest_daily_report(etf["id"])
    if existing and existing["date"] == today_str:
        report_sections.append((etf["name"], etf["ticker"], existing["report_text"], ref_date))
        return

    changes = analyzer.analyze_changes(
        etf["name"], ref_date,
        latest_snap, prev_snap,
        db.get_holdings(latest_snap["id"]),
        db.get_holdings(prev_snap["id"]),
    )
    prev_insight_row = db.get_latest_insight(etf["id"])
    prev_insight = prev_insight_row["insight_text"] if prev_insight_row else ""
    etf_report = analyzer.generate_etf_report(changes, prev_insight)
    db.save_daily_report(etf["id"], today_str, etf_report)
    report_sections.append((etf["name"], etf["ticker"], etf_report, ref_date))
    logger.info(f"Fallback report generated for {etf['name']} (based on {ref_date})")


def _skip_backfill(url: str) -> bool:
    return url.startswith(("yfinance://", "roundhill://", "wisdomtree://"))


async def _backfill_gaps(etf: dict, today: date):
    """Scrape any missing weekday dates from the ETF's backfill_from date up to yesterday."""
    if _skip_backfill(etf.get("url", "")):
        return
    known = db.get_known_dates(etf["id"])
    yesterday = today - timedelta(days=1)

    etf_start = date.fromisoformat(etf["backfill_from"]) if etf.get("backfill_from") else BACKFILL_START

    missing = [
        d for d in _daterange(etf_start, yesterday)
        if str(d) not in known and d.weekday() < 5  # Mon–Fri only
    ]

    if not missing:
        return

    logger.info(f"Backfilling {len(missing)} missing dates for {etf['name']}")
    for d in missing:
        date_str = str(d)
        try:
            data = scraper.fetch_holdings(etf["url"], d, yf_ticker=etf.get("yf_ticker"))
            if data:
                db.save_snapshot(etf["id"], date_str, data["aum_100m"], data["holdings"])
                logger.debug(f"  Backfilled {date_str}: {len(data['holdings'])} holdings")
            else:
                db.save_no_data_date(etf["id"], date_str)
                logger.debug(f"  No data {date_str} (holiday)")
        except Exception:
            logger.exception(f"Backfill error for {etf['name']} on {date_str}")
        await asyncio.sleep(_BACKFILL_DELAY)

    logger.info(f"Backfill complete for {etf['name']}")


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def count_missing_dates(etf: dict) -> int:
    """Return number of weekday dates missing from backfill_from to yesterday."""
    if _skip_backfill(etf.get("url", "")):
        return 0
    today = datetime.now(KST).date()
    yesterday = today - timedelta(days=1)
    etf_start = date.fromisoformat(etf["backfill_from"]) if etf.get("backfill_from") else BACKFILL_START
    known = db.get_known_dates(etf["id"])
    return sum(
        1 for d in _daterange(etf_start, yesterday)
        if str(d) not in known and d.weekday() < 5
    )


async def run_startup_job(send_fn: Callable[..., Awaitable]):
    """Backfill gaps + generate today's report (if missing) + refresh insights if >7 days old."""
    today = datetime.now(KST).date()
    today_str = str(today)
    logger.info(f"Startup job started for {today_str}")

    # 1. Backfill + daily report (idempotent — skips if already done today)
    await run_daily_job(send_fn)

    # 2. Refresh insights if latest is >7 days old
    etfs = db.get_all_etfs()
    insight_needed = []
    for etf in etfs:
        etf = dict(etf)
        if etf.get("benchmark"):
            continue
        row = db.get_latest_insight(etf["id"])
        if not row:
            insight_needed.append(etf)
        else:
            from datetime import timedelta
            last_date = date.fromisoformat(row["date"])
            if (today - last_date).days > 7:
                insight_needed.append(etf)

    if insight_needed:
        logger.info(f"Refreshing insights for {len(insight_needed)} ETFs")
        for etf in insight_needed:
            try:
                all_snap_changes = _build_all_changes(etf)
                if all_snap_changes:
                    insight = analyzer.generate_etf_insight(etf["name"], all_snap_changes)
                    db.save_insight(etf["id"], today_str, insight)
                    logger.info(f"Startup insight refreshed for {etf['name']}")
            except Exception:
                logger.exception(f"Error refreshing insight for {etf['name']}")


async def run_weekly_insight_job():
    """Generate and save cumulative insights for all ETFs. Runs every Sunday 10:00 KST."""
    today_str = str(datetime.now(KST).date())
    logger.info(f"Weekly insight job started for {today_str}")

    etfs = db.get_all_etfs()
    for etf in etfs:
        etf = dict(etf)
        if etf.get("benchmark"):
            continue
        try:
            all_snap_changes = _build_all_changes(etf)
            if not all_snap_changes:
                logger.info(f"No history for {etf['name']}, skipping insight")
                continue
            insight = analyzer.generate_etf_insight(etf["name"], all_snap_changes)
            db.save_insight(etf["id"], today_str, insight)
            logger.info(f"Weekly insight saved for {etf['name']}")
        except Exception:
            logger.exception(f"Error generating weekly insight for {etf['name']}")


def _count_weekday_gap(from_date: date, to_date: date) -> int:
    """Count weekdays strictly between from_date and to_date (both exclusive)."""
    count = 0
    d = from_date + timedelta(days=1)
    while d < to_date:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


async def _check_data_health(etfs: list, today_str: str) -> list[dict]:
    """Detect ETFs with consecutive data failures and attempt yfinance recovery."""
    today = date.fromisoformat(today_str)
    alerts = []

    for etf in etfs:
        etf = dict(etf)
        if etf.get("benchmark"):
            continue

        last_snap_str = db.get_latest_snapshot_date(etf["id"])
        if not last_snap_str:
            continue

        last_snap = date.fromisoformat(last_snap_str)
        gap = _count_weekday_gap(last_snap, today)

        if gap >= 3:
            alert = {
                "name": etf["name"],
                "ticker": etf["ticker"],
                "gap_days": gap,
                "last_data": last_snap_str,
                "recovered": False,
                "recovery_method": None,
            }

            today_has_snapshot = db.get_snapshot(etf["id"], today_str) is not None
            yf_ticker = etf.get("yf_ticker")

            if not today_has_snapshot and yf_ticker:
                try:
                    data = scraper.fetch_holdings(f"yfinance://{yf_ticker}", today)
                    if data and data["holdings"]:
                        db.save_snapshot(etf["id"], today_str, data["aum_100m"], data["holdings"])
                        db.delete_no_data_date(etf["id"], today_str)
                        alert["recovered"] = True
                        alert["recovery_method"] = "yfinance"
                        logger.info("Health: %s recovered via yfinance", etf["name"])
                except Exception:
                    logger.exception("Health: recovery failed for %s", etf["name"])

            alerts.append(alert)

        elif last_snap_str == today_str:
            prev = db.get_prev_snapshot(etf["id"], today_str)
            if prev:
                prev_gap = _count_weekday_gap(date.fromisoformat(prev["date"]), today)
                if prev_gap >= 5:
                    alerts.append({
                        "name": etf["name"],
                        "ticker": etf["ticker"],
                        "gap_days": prev_gap,
                        "last_data": prev["date"],
                        "recovered": True,
                        "recovery_method": "정상 복구",
                    })

    return alerts


def _format_health_alerts(health_alerts: list) -> str:
    parts = ["\n⚠️ **데이터 수집 현황**"]
    for a in health_alerts:
        if a["recovered"]:
            parts.append(
                f"✅ **{a['ticker']}**: {a['gap_days']}일간 수집 실패 "
                f"→ {a['recovery_method']} 폴백 복구 성공"
            )
        else:
            parts.append(
                f"🚨 **{a['ticker']}**: {a['gap_days']}일 연속 수집 실패 "
                f"(최종 데이터: {a['last_data']}) — 수동 확인 필요"
            )
    return "\n".join(parts)


async def _recovery_check(send_fn: Callable[..., Awaitable]):
    """Runs at 09:00 — if today's report wasn't generated at 08:00, retry it."""
    today = datetime.now(KST).date()
    today_str = str(today)
    latest_market = db.get_latest_market_insight()
    if latest_market and latest_market["date"] == today_str:
        logger.info("Recovery check: today's report already exists, skipping")
        return
    logger.warning("Recovery check: today's report missing, retrying daily job")
    try:
        await run_daily_job(send_fn)
    except Exception:
        logger.exception("Recovery check: retry also failed")
        import os, httpx
        webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        if webhook:
            try:
                httpx.Client(timeout=10).post(
                    webhook,
                    json={"content": f"⚠️ **ETF 레포트 생성 실패** ({today_str})\n08:00 트리거 + 09:00 재시도 모두 실패. 수동 확인 필요."},
                )
            except Exception:
                pass


def setup_scheduler(send_fn: Callable[..., Awaitable]) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=KST)
    scheduler.add_job(
        run_daily_job,
        trigger="cron",
        hour=SCHEDULE_HOUR,
        minute=SCHEDULE_MINUTE,
        args=[send_fn],
        id="daily_etf_job",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_weekly_insight_job,
        trigger="cron",
        day_of_week="sun",
        hour=10,
        minute=0,
        id="weekly_insight_job",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _recovery_check,
        trigger="cron",
        hour=9,
        minute=0,
        args=[send_fn],
        id="recovery_check",
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started: daily={SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} KST, "
        f"weekly insight=Sun 10:00 KST"
    )
    return scheduler
