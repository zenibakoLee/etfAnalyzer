import asyncio
import logging

from aiohttp import web

from src import database as db
from src.config import PORT
from src.scheduler import setup_scheduler
from src.webhook import send_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def health(_request):
    return web.Response(text="OK")


async def main():
    db.init_db()
    logger.info("Database initialized")

    setup_scheduler(send_report)

    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health server listening on port {PORT}")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
