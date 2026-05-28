import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Callable, Awaitable

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src import database as db, scraper, analyzer
from src.config import SCHEDULE_HOUR, SCHEDULE_MINUTE

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

BACKFILL_START = date(2023, 5, 16)
_BACKFILL_DELAY = 0.5  # seconds between requests


async def run_daily_job(send_fn: Callable[[str], Awaitable]):
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

    for etf in etfs:
        etf = dict(etf)
        if etf.get("benchmark"):
            continue
        try:
            # ── Backfill missing dates before today ───────────────────────
            await _backfill_gaps(etf, today)

            # ── Scrape today ──────────────────────────────────────────────
            data = scraper.fetch_holdings(etf["url"], today)
            if not data:
                db.save_no_data_date(etf["id"], today_str)
                logger.info(f"No data for {etf['name']} on {today_str}, trying latest snapshots")
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
            etf_report = analyzer.generate_etf_report(changes, prev_insight)
            db.save_daily_report(etf["id"], today_str, etf_report)
            report_sections.append((etf["name"], etf["ticker"], etf_report))

        except Exception:
            logger.exception(f"Error processing ETF {etf['name']}")

    # ── Collect daily returns for all ETFs ──────────────────────────────────
    returns_summary = await _collect_daily_returns(etfs, today_str)

    if not report_sections:
        if returns_summary:
            await send_fn(_build_returns_only_message(today_str, returns_summary))
        else:
            logger.info("No report sections today — nothing to send")
        return

    # ── Market headline ───────────────────────────────────────────────────────
    headline = ""
    if all_changes:
        headline = analyzer.generate_market_headline(all_changes)
        db.save_market_insight(today_str, headline)

    message = _build_message(today_str, headline, report_sections, returns_summary)
    await send_fn(message)
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


def _build_returns_only_message(date_str: str, returns_summary: list) -> str:
    parts = [f"📅 **{date_str} ETF 수익률 현황**\n"]
    parts.append(_format_returns_table(returns_summary))
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
            returns = scraper.fetch_etf_returns(yf_ticker, period="1mo")
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


async def _backfill_gaps(etf: dict, today: date):
    """Scrape any missing weekday dates from the ETF's backfill_from date up to yesterday."""
    if etf.get("url", "").startswith("yfinance://"):
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
            data = scraper.fetch_holdings(etf["url"], d)
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
    if etf.get("url", "").startswith("yfinance://"):
        return 0
    today = datetime.now(KST).date()
    yesterday = today - timedelta(days=1)
    etf_start = date.fromisoformat(etf["backfill_from"]) if etf.get("backfill_from") else BACKFILL_START
    known = db.get_known_dates(etf["id"])
    return sum(
        1 for d in _daterange(etf_start, yesterday)
        if str(d) not in known and d.weekday() < 5
    )


async def run_startup_job(send_fn: Callable[[str], Awaitable]):
    """Backfill gaps + generate today's report (if missing) + refresh insights if >7 days old."""
    today = datetime.now(KST).date()
    today_str = str(today)
    logger.info(f"Startup job started for {today_str}")

    # 1. Backfill + daily report (reuse run_daily_job but force re-run even if done today)
    latest_market = db.get_latest_market_insight()
    already_done = latest_market and latest_market["date"] == today_str
    if already_done:
        # Delete today's market insight to force re-run
        import sqlite3
        from src.config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM market_insights WHERE date = ?", (today_str,))
        conn.commit()
        conn.close()

    await run_daily_job(send_fn)

    # 2. Refresh insights if latest is >7 days old
    etfs = db.get_all_etfs()
    insight_needed = []
    for etf in etfs:
        etf = dict(etf)
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


def setup_scheduler(send_fn: Callable[[str], Awaitable]) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=KST)
    scheduler.add_job(
        run_daily_job,
        trigger="cron",
        hour=SCHEDULE_HOUR,
        minute=SCHEDULE_MINUTE,
        args=[send_fn],
        id="daily_etf_job",
        replace_existing=True,
    )
    scheduler.add_job(
        run_weekly_insight_job,
        trigger="cron",
        day_of_week="sun",
        hour=10,
        minute=0,
        id="weekly_insight_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started: daily={SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} KST, "
        f"weekly insight=Sun 10:00 KST"
    )
    return scheduler
