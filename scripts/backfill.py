"""
One-time historical data backfill.
Run from project root: python -m scripts.backfill
"""
import sys
import os
import time
import logging
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import database as db, scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKFILL_START = date(2023, 5, 16)
REQUEST_DELAY = 0.5  # seconds between requests


def run():
    db.init_db()
    etfs = db.get_all_etfs()
    today = date.today()

    for etf in etfs:
        etf = dict(etf)
        logger.info(f"=== Backfilling: {etf['name']} ===")
        current = BACKFILL_START
        saved = skipped = errors = 0

        while current <= today:
            date_str = str(current)

            if db.get_snapshot(etf["id"], date_str):
                current += timedelta(days=1)
                skipped += 1
                continue

            try:
                data = scraper.fetch_holdings(etf["url"], current)
                if data:
                    db.save_snapshot(etf["id"], date_str, data["aum_100m"], data["holdings"])
                    saved += 1
                    logger.info(f"  Saved {date_str}: {len(data['holdings'])} holdings, AUM={data['aum_100m']}억원")
                else:
                    logger.debug(f"  {date_str}: no data (weekend/holiday)")
            except Exception as e:
                errors += 1
                logger.error(f"  {date_str}: {e}")

            current += timedelta(days=1)
            time.sleep(REQUEST_DELAY)

        logger.info(f"Done: saved={saved}, skipped={skipped}, errors={errors}")


if __name__ == "__main__":
    run()
