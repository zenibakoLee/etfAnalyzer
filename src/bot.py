import asyncio
import logging
import pytz
from datetime import datetime

import discord
from src import analyzer, database as db
from src.config import DISCORD_USER_ID

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

bot = discord.Client(intents=intents)

# {user_id: {"state": ..., "etfs"?: [...], "etf"?: {...}}}
_user_states: dict = {}

CHUNK_SIZE = 1900  # Discord 2000 char limit with buffer

_CONFIRM_KEYWORDS = {"y", "yes", "네", "ㅇ", "응", "ㅇㅇ"}


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

        if state["state"] == "awaiting_report_generate_confirm":
            del _user_states[user_id]
            if content.lower() in _CONFIRM_KEYWORDS:
                await _generate_and_send_report(message, state["etf"])
            else:
                await message.channel.send("취소되었습니다.")
            return

        # Selection states (list → number input)
        etfs = state["etfs"]
        try:
            idx = int(content) - 1
            if 0 <= idx < len(etfs):
                del _user_states[user_id]
                if state["state"] == "awaiting_insight_selection":
                    await _send_etf_insight(message.channel, etfs[idx])
                else:
                    await _send_etf_report(message, etfs[idx])
            else:
                await message.channel.send(f"1~{len(etfs)} 사이의 번호를 입력해주세요.")
        except ValueError:
            del _user_states[user_id]
            await message.channel.send("취소되었습니다.")
        return

    # ── Commands ─────────────────────────────────────────────────────────────
    lower = content.lower()
    if lower in ("/insight", "!insight"):
        await _handle_insight(message)
    elif lower in ("/report", "!report"):
        await _handle_report(message)


# ── /insight ─────────────────────────────────────────────────────────────────

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
    _user_states[message.author.id] = {"state": "awaiting_insight_selection", "etfs": etfs}


async def _send_etf_insight(channel: discord.DMChannel, etf: dict):
    row = db.get_latest_insight(etf["id"])
    if not row:
        await channel.send(f"**{etf['name']}**의 인사이트 데이터가 아직 없습니다.")
        return

    header = (
        f"📊 **{etf['name']} ({etf['ticker']}) 누적 인사이트**\n"
        f"_(기준일: {row['date']})_\n\n"
    )
    await _send_chunked(channel, header + row["insight_text"])


# ── /report ──────────────────────────────────────────────────────────────────

async def _handle_report(message: discord.Message):
    etfs = [dict(e) for e in db.get_all_etfs()]
    if not etfs:
        await message.channel.send("등록된 ETF가 없습니다.")
        return

    lines = ["📋 **일일 리포트 조회 가능한 ETF 목록:**\n"]
    for i, etf in enumerate(etfs, 1):
        row = db.get_latest_daily_report(etf["id"])
        date_str = f" (최신: {row['date']})" if row else " (저장 없음)"
        lines.append(f"{i}. {etf['name']} ({etf['ticker']}){date_str}")
    lines.append("\n번호를 입력하세요.")

    await message.channel.send("\n".join(lines))
    _user_states[message.author.id] = {"state": "awaiting_report_selection", "etfs": etfs}


async def _send_etf_report(message: discord.Message, etf: dict):
    row = db.get_latest_daily_report(etf["id"])
    if not row:
        await message.channel.send(
            f"**{etf['name']}**의 저장된 리포트가 없습니다.\n"
            f"지금 바로 생성해드릴까요? (y / n)"
        )
        _user_states[message.author.id] = {
            "state": "awaiting_report_generate_confirm",
            "etf": etf,
        }
        return

    header = (
        f"📊 **{etf['name']} ({etf['ticker']}) 일일 리포트**\n"
        f"_(기준일: {row['date']})_\n\n"
    )
    await _send_chunked(message.channel, header + row["report_text"])


async def _generate_and_send_report(message: discord.Message, etf: dict):
    """On-demand: generate report from latest available snapshots, save, and send."""
    await message.channel.send(f"⏳ **{etf['name']}** 리포트 생성 중... 30~60초 소요됩니다.")

    try:
        snapshots = db.get_all_snapshots(etf["id"])
        if len(snapshots) < 2:
            await message.channel.send("분석할 데이터가 부족합니다. 스냅샷이 2개 이상 필요합니다.")
            return

        today_snap = dict(snapshots[-1])
        prev_snap = dict(snapshots[-2])
        today_holdings = db.get_holdings(today_snap["id"])
        prev_holdings = db.get_holdings(prev_snap["id"])

        changes = analyzer.analyze_changes(
            etf["name"], today_snap["date"],
            today_snap, prev_snap,
            today_holdings, prev_holdings,
        )

        prev_insight_row = db.get_latest_insight(etf["id"])
        prev_insight = prev_insight_row["insight_text"] if prev_insight_row else ""
        report_text = analyzer.generate_etf_report(changes, prev_insight)

        db.save_daily_report(etf["id"], today_snap["date"], report_text)

        header = (
            f"📊 **{etf['name']} ({etf['ticker']}) 일일 리포트**\n"
            f"_(기준일: {today_snap['date']})_\n\n"
        )
        await _send_chunked(message.channel, header + report_text)

    except Exception:
        logger.exception(f"On-demand report generation failed for {etf['name']}")
        await message.channel.send("리포트 생성 중 오류가 발생했습니다.")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_chunked(channel, text: str):
    for i in range(0, len(text), CHUNK_SIZE):
        await channel.send(text[i: i + CHUNK_SIZE])
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
