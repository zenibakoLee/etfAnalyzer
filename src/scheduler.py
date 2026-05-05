import logging
from datetime import datetime
from typing import Callable, Awaitable

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src import database as db, scraper, analyzer
from src.config import SCHEDULE_HOUR, SCHEDULE_MINUTE

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")


async def run_daily_job(send_fn: Callable[[str], Awaitable]):
    today = datetime.now(KST).date()
    today_str = str(today)
    logger.info(f"Daily job started for {today_str}")

    etfs = db.get_all_etfs()
    all_changes = []
    report_sections = []

    for etf in etfs:
        etf = dict(etf)
        try:
            # ── Scrape ───────────────────────────────────────────────────────
            data = scraper.fetch_holdings(etf["url"], today)
            if not data:
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
            report_sections.append((etf["name"], etf["ticker"], etf_report))

            # ── Update cumulative insight ─────────────────────────────────────
            all_snap_changes = _build_all_changes(etf)
            new_insight = analyzer.generate_etf_insight(etf["name"], all_snap_changes)
            db.save_insight(etf["id"], today_str, new_insight)

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
    scheduler.start()
    logger.info(f"Scheduler started: daily job at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} KST")
    return scheduler
