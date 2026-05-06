import asyncio
import logging

from aiohttp import web

from src import database as db
from src.bot import bot, send_report
from src.config import DISCORD_BOT_TOKEN, PORT
from src.scheduler import setup_scheduler

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

    logger.info("Starting Discord bot...")
    await bot.start(DISCORD_BOT_TOKEN)


def _run():
    """Called by watchfiles subprocess on each restart."""
    asyncio.run(main())


if __name__ == "__main__":
    from watchfiles import run_process
    run_process("src/", target=_run)
