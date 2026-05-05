import asyncio
import logging
import discord
from src import database as db
from src.config import DISCORD_USER_ID

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

bot = discord.Client(intents=intents)

# {user_id: {"state": "awaiting_insight_selection", "etfs": [...]}}
_user_states: dict = {}

CHUNK_SIZE = 1900  # Discord 2000 char limit with buffer


@bot.event
async def on_ready():
    logger.info(f"Discord bot ready: {bot.user} (id={bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return

    user_id = message.author.id
    content = message.content.strip()

    # ── State machine ────────────────────────────────────────────────────────
    if user_id in _user_states:
        state = _user_states[user_id]
        if state["state"] == "awaiting_insight_selection":
            etfs = state["etfs"]
            try:
                idx = int(content) - 1
                if 0 <= idx < len(etfs):
                    del _user_states[user_id]
                    await _send_etf_insight(message.channel, etfs[idx])
                else:
                    await message.channel.send(f"1~{len(etfs)} 사이의 번호를 입력해주세요.")
            except ValueError:
                del _user_states[user_id]
                await message.channel.send("취소되었습니다. 다시 /insight 를 입력해주세요.")
            return

    # ── Commands ─────────────────────────────────────────────────────────────
    lower = content.lower()
    if lower in ("/insight", "!insight"):
        await _handle_insight(message)


async def _handle_insight(message: discord.Message):
    etfs = [dict(e) for e in db.get_all_etfs()]
    if not etfs:
        await message.channel.send("등록된 ETF가 없습니다.")
        return

    lines = ["📋 **인사이트 조회 가능한 ETF 목록:**\n"]
    for i, etf in enumerate(etfs, 1):
        row = db.get_latest_insight(etf["id"])
        date_str = f" (최신: {row['date']})" if row else " (데이터 없음)"
        lines.append(f"{i}. {etf['name']} ({etf['ticker']}){date_str}")
    lines.append("\n번호를 입력하세요.")

    await message.channel.send("\n".join(lines))
    _user_states[message.author.id] = {
        "state": "awaiting_insight_selection",
        "etfs": etfs,
    }


async def _send_etf_insight(channel: discord.DMChannel, etf: dict):
    row = db.get_latest_insight(etf["id"])
    if not row:
        await channel.send(f"**{etf['name']}**의 인사이트 데이터가 아직 없습니다.")
        return

    header = (
        f"📊 **{etf['name']} ({etf['ticker']}) 누적 인사이트**\n"
        f"_(기준일: {row['date']})_\n\n"
    )
    full_text = header + row["insight_text"]
    await _send_chunked(channel, full_text)


async def _send_chunked(channel, text: str):
    for i in range(0, len(text), CHUNK_SIZE):
        await channel.send(text[i : i + CHUNK_SIZE])
        if i + CHUNK_SIZE < len(text):
            await asyncio.sleep(0.3)


async def send_report(text: str):
    """Proactively send a DM report to the configured user."""
    try:
        user = await bot.fetch_user(DISCORD_USER_ID)
        await _send_chunked(user, text)
        logger.info("Daily report sent via DM")
    except Exception:
        logger.exception("Failed to send DM report")
