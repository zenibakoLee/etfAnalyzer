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
        try:
            # ── Backfill missing dates before today ───────────────────────
            await _backfill_gaps(etf, today)

            # ── Scrape today ──────────────────────────────────────────────
            data = scraper.fetch_holdings(etf["url"], today)
            if not data:
                db.save_no_data_date(etf["id"], today_str)
                logger.info(f"No data for {etf['name']} on {today_str} (weekend/holiday)")
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

    if not report_sections:
        logger.info("No report sections today — nothing to send")
        return

    # ── Market headline ───────────────────────────────────────────────────────
    headline = ""
    if all_changes:
        headline = analyzer.generate_market_headline(all_changes)
        db.save_market_insight(today_str, headline)

    message = _build_message(today_str, headline, report_sections)
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


def _build_message(date_str: str, headline: str, sections: list) -> str:
    parts = [f"📅 **{date_str} ETF 일일 보고서**\n"]

    if headline:
        parts.append("🌐 **오늘의 시장 헤드라인**")
        parts.append(headline)
        parts.append("\n━━━━━━━━━━━━━━━━━━━━━")

    for name, ticker, report in sections:
        parts.append(f"\n📊 **{name}** ({ticker})")
        parts.append(report)
        parts.append("━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(parts)


async def _backfill_gaps(etf: dict, today: date):
    """Scrape any missing weekday dates from the ETF's backfill_from date up to yesterday."""
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
