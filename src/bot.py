import asyncio
import logging
import pytz
from datetime import datetime, date, timedelta

import discord
from src import analyzer, database as db
from src.config import DISCORD_USER_ID

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

bot = discord.Client(intents=intents)

# {user_id: {"state": ..., ...}}
_user_states: dict = {}

CHUNK_SIZE = 1900
_CONFIRM_KEYWORDS = {"y", "yes", "네", "ㅇ", "응", "ㅇㅇ"}

# ── Localization ──────────────────────────────────────────────────────────────

_T = {
    "greeting": {
        "ko": "👋 안녕하세요! ETF Analyzer 봇이 시작되었습니다.",
        "en": "👋 Hello! ETF Analyzer bot is online.",
    },
    "ask_language": {
        "ko": "👋 Hello! ETF Analyzer bot is online.\n\nWhat language would you like to use?\n(e.g. Korean, 한국어, English, 영어...)",
        "en": "👋 Hello! ETF Analyzer bot is online.\n\nWhat language would you like to use?\n(e.g. Korean, 한국어, English, 영어...)",
    },
    "language_saved": {
        "ko": "✅ 언어가 한국어로 설정되었습니다.",
        "en": "✅ Language set to English.",
    },
    "status_header": {
        "ko": "\n📊 **현재 데이터 현황:**",
        "en": "\n📊 **Current data status:**",
    },
    "missing_days": {
        "ko": "일 누락",
        "en": "days missing",
    },
    "up_to_date": {
        "ko": "최신",
        "en": "up to date",
    },
    "report_done": {
        "ko": "📋 오늘 리포트: 생성됨 ✅",
        "en": "📋 Today's report: generated ✅",
    },
    "report_missing": {
        "ko": "📋 오늘 리포트: 미생성",
        "en": "📋 Today's report: not generated",
    },
    "insight_fresh": {
        "ko": "💡 인사이트: 최신 ({date}) ✅",
        "en": "💡 Insights: up to date ({date}) ✅",
    },
    "insight_stale": {
        "ko": "💡 인사이트: 갱신 필요 (마지막: {date})",
        "en": "💡 Insights: stale (last: {date})",
    },
    "ask_startup": {
        "ko": "\n백필·리포트·인사이트 작업을 지금 진행할까요? (y / n)",
        "en": "\nRun backfill, report, and insight refresh now? (y / n)",
    },
    "nothing_needed": {
        "ko": "\n모든 데이터가 최신 상태입니다. 🎉",
        "en": "\nAll data is up to date. 🎉",
    },
    "startup_running": {
        "ko": "⏳ 작업 시작합니다. 완료까지 수 분이 소요될 수 있습니다.",
        "en": "⏳ Running tasks. This may take a few minutes.",
    },
    "startup_done": {
        "ko": "✅ 모든 작업 완료.",
        "en": "✅ All tasks complete.",
    },
    "cancelled": {
        "ko": "취소되었습니다.",
        "en": "Cancelled.",
    },
    "insight_list": {
        "ko": "📋 **인사이트 조회 가능한 ETF 목록:**\n",
        "en": "📋 **ETFs with available insights:**\n",
    },
    "report_list": {
        "ko": "📋 **일일 리포트 조회 가능한 ETF 목록:**\n",
        "en": "📋 **ETFs with available reports:**\n",
    },
    "enter_number": {
        "ko": "\n번호를 입력하세요.",
        "en": "\nEnter a number.",
    },
    "out_of_range": {
        "ko": "1~{n} 사이의 번호를 입력해주세요.",
        "en": "Please enter a number between 1 and {n}.",
    },
    "no_etfs": {
        "ko": "등록된 ETF가 없습니다.",
        "en": "No ETFs registered.",
    },
    "no_insight": {
        "ko": "**{name}**의 인사이트 데이터가 아직 없습니다.",
        "en": "No insight data available for **{name}** yet.",
    },
    "no_report_ask": {
        "ko": "**{name}**의 저장된 리포트가 없습니다.\n지금 바로 생성해드릴까요? (y / n)",
        "en": "No stored report for **{name}**.\nGenerate one now? (y / n)",
    },
    "report_generating": {
        "ko": "⏳ **{name}** 리포트 생성 중... 30~60초 소요됩니다.",
        "en": "⏳ Generating report for **{name}**... (~30-60 seconds)",
    },
    "report_no_data": {
        "ko": "분석할 데이터가 부족합니다. 스냅샷이 2개 이상 필요합니다.",
        "en": "Insufficient data. Need at least 2 snapshots.",
    },
    "report_error": {
        "ko": "리포트 생성 중 오류가 발생했습니다.",
        "en": "An error occurred while generating the report.",
    },
    "insight_header": {
        "ko": "📊 **{name} ({ticker}) 누적 인사이트**\n_(기준일: {date})_\n\n",
        "en": "📊 **{name} ({ticker}) Cumulative Insight**\n_(as of: {date})_\n\n",
    },
    "report_header": {
        "ko": "📊 **{name} ({ticker}) 일일 리포트**\n_(기준일: {date})_\n\n",
        "en": "📊 **{name} ({ticker}) Daily Report**\n_(as of: {date})_\n\n",
    },
    "no_data_label": {
        "ko": "(데이터 없음)",
        "en": "(no data)",
    },
}


def t(key: str, lang: str = None, **kwargs) -> str:
    lang = lang or db.get_preference("language") or "en"
    text = _T.get(key, {}).get(lang, _T.get(key, {}).get("en", key))
    return text.format(**kwargs) if kwargs else text


# ── Bot events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"Discord bot ready: {bot.user} (id={bot.user.id})")
    asyncio.create_task(_startup_greeting())


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return

    user_id = message.author.id
    content = message.content.strip()

    # ── State machine ─────────────────────────────────────────────────────────
    if user_id in _user_states:
        state = _user_states[user_id]

        if state["state"] == "awaiting_language_selection":
            lang = _parse_language(content)
            if lang:
                del _user_states[user_id]
                db.save_preference("language", lang)
                await message.channel.send(t("language_saved", lang))
                await _send_startup_status(message.channel)
            else:
                await message.channel.send("Sorry, I couldn't recognize that. Try: Korean, 한국어, English, 영어...")
            return

        if state["state"] == "awaiting_startup_confirm":
            del _user_states[user_id]
            if content.lower() in _CONFIRM_KEYWORDS:
                await message.channel.send(t("startup_running"))
                from src.scheduler import run_startup_job
                await run_startup_job(send_report)
                await message.channel.send(t("startup_done"))
            else:
                await message.channel.send(t("cancelled"))
            return

        if state["state"] == "awaiting_report_generate_confirm":
            del _user_states[user_id]
            if content.lower() in _CONFIRM_KEYWORDS:
                await _generate_and_send_report(message, state["etf"])
            else:
                await message.channel.send(t("cancelled"))
            return

        # Selection states
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
                await message.channel.send(t("out_of_range", n=len(etfs)))
        except ValueError:
            del _user_states[user_id]
            await message.channel.send(t("cancelled"))
        return

    # ── Commands ──────────────────────────────────────────────────────────────
    lower = content.lower()
    if lower in ("/insight", "!insight"):
        await _handle_insight(message)
    elif lower in ("/report", "!report"):
        await _handle_report(message)


# ── Startup flow ──────────────────────────────────────────────────────────────

async def _startup_greeting():
    await asyncio.sleep(1)  # wait for bot to fully connect
    try:
        user = await bot.fetch_user(DISCORD_USER_ID)
        lang = db.get_preference("language")
        if not lang:
            await user.send(t("ask_language"))
            _user_states[DISCORD_USER_ID] = {"state": "awaiting_language_selection"}
        else:
            channel = await user.create_dm()
            await channel.send(t("greeting", lang))
            await _send_startup_status(channel)
    except Exception:
        logger.exception("Failed to send startup greeting")


async def _send_startup_status(channel):
    lang = db.get_preference("language") or "en"
    today = datetime.now(KST).date()
    today_str = str(today)

    from src.scheduler import count_missing_dates

    lines = [t("status_header", lang)]
    needs_work = False

    for etf in [dict(e) for e in db.get_all_etfs()]:
        snaps = db.get_all_snapshots(etf["id"])
        missing = count_missing_dates(etf)
        last = snaps[-1]["date"] if snaps else None
        if missing > 0:
            needs_work = True
            label = f"⚠️ {last or '?'} ({missing} {t('missing_days', lang)})"
        else:
            label = f"✅ {last or '?'} ({t('up_to_date', lang)})"
        lines.append(f"• {etf['name']}: {label}")

    # Report status
    today_reports = [
        e for e in [dict(e) for e in db.get_all_etfs()]
        if (r := db.get_latest_daily_report(e["id"])) and r["date"] == today_str
    ]
    if len(today_reports) < len(db.get_all_etfs()):
        lines.append(t("report_missing", lang))
        needs_work = True
    else:
        lines.append(t("report_done", lang))

    # Insight status
    for etf in [dict(e) for e in db.get_all_etfs()]:
        row = db.get_latest_insight(etf["id"])
        if not row:
            needs_work = True
        else:
            last_date = date.fromisoformat(row["date"])
            if (today - last_date).days > 7:
                needs_work = True
                lines.append(t("insight_stale", lang, date=row["date"]))
            else:
                lines.append(t("insight_fresh", lang, date=row["date"]))
        break  # show summary from first ETF only for brevity

    if needs_work:
        lines.append(t("ask_startup", lang))
        await channel.send("\n".join(lines))
        _user_states[DISCORD_USER_ID] = {"state": "awaiting_startup_confirm"}
    else:
        lines.append(t("nothing_needed", lang))
        await channel.send("\n".join(lines))


def _parse_language(content: str) -> str | None:
    # Korean characters present → Korean
    if any('가' <= ch <= '힣' or 'ᄀ' <= ch <= 'ᇿ' for ch in content):
        return "ko"
    c = content.strip().lower()
    _KO = {"korean", "korea", "ko", "kr", "한국어", "한국", "한글", "1"}
    _EN = {"english", "english", "en", "eng", "states", "us", "america", "american", "영어", "2"}
    if any(w in c for w in _KO):
        return "ko"
    if any(w in c for w in _EN):
        return "en"
    return None


# ── /insight ──────────────────────────────────────────────────────────────────

async def _handle_insight(message: discord.Message):
    lang = db.get_preference("language") or "en"
    etfs = [dict(e) for e in db.get_all_etfs()]
    if not etfs:
        await message.channel.send(t("no_etfs", lang))
        return

    lines = [t("insight_list", lang)]
    for i, etf in enumerate(etfs, 1):
        row = db.get_latest_insight(etf["id"])
        date_str = f" ({row['date']})" if row else f" {t('no_data_label', lang)}"
        lines.append(f"{i}. {etf['name']} ({etf['ticker']}){date_str}")
    lines.append(t("enter_number", lang))

    await message.channel.send("\n".join(lines))
    _user_states[message.author.id] = {"state": "awaiting_insight_selection", "etfs": etfs}


async def _send_etf_insight(channel: discord.DMChannel, etf: dict):
    lang = db.get_preference("language") or "en"
    row = db.get_latest_insight(etf["id"])
    if not row:
        await channel.send(t("no_insight", lang, name=etf["name"]))
        return
    header = t("insight_header", lang, name=etf["name"], ticker=etf["ticker"], date=row["date"])
    await _send_chunked(channel, header + row["insight_text"])


# ── /report ───────────────────────────────────────────────────────────────────

async def _handle_report(message: discord.Message):
    lang = db.get_preference("language") or "en"
    etfs = [dict(e) for e in db.get_all_etfs()]
    if not etfs:
        await message.channel.send(t("no_etfs", lang))
        return

    lines = [t("report_list", lang)]
    for i, etf in enumerate(etfs, 1):
        row = db.get_latest_daily_report(etf["id"])
        date_str = f" ({row['date']})" if row else f" {t('no_data_label', lang)}"
        lines.append(f"{i}. {etf['name']} ({etf['ticker']}){date_str}")
    lines.append(t("enter_number", lang))

    await message.channel.send("\n".join(lines))
    _user_states[message.author.id] = {"state": "awaiting_report_selection", "etfs": etfs}


async def _send_etf_report(message: discord.Message, etf: dict):
    lang = db.get_preference("language") or "en"
    row = db.get_latest_daily_report(etf["id"])
    if not row:
        await message.channel.send(t("no_report_ask", lang, name=etf["name"]))
        _user_states[message.author.id] = {"state": "awaiting_report_generate_confirm", "etf": etf}
        return
    header = t("report_header", lang, name=etf["name"], ticker=etf["ticker"], date=row["date"])
    await _send_chunked(message.channel, header + row["report_text"])


async def _generate_and_send_report(message: discord.Message, etf: dict):
    lang = db.get_preference("language") or "en"
    await message.channel.send(t("report_generating", lang, name=etf["name"]))
    try:
        snapshots = db.get_all_snapshots(etf["id"])
        if len(snapshots) < 2:
            await message.channel.send(t("report_no_data", lang))
            return

        today_snap = dict(snapshots[-1])
        prev_snap = dict(snapshots[-2])
        changes = analyzer.analyze_changes(
            etf["name"], today_snap["date"],
            today_snap, prev_snap,
            db.get_holdings(today_snap["id"]),
            db.get_holdings(prev_snap["id"]),
        )
        prev_insight_row = db.get_latest_insight(etf["id"])
        prev_insight = prev_insight_row["insight_text"] if prev_insight_row else ""
        report_text = analyzer.generate_etf_report(changes, prev_insight)
        db.save_daily_report(etf["id"], today_snap["date"], report_text)

        header = t("report_header", lang, name=etf["name"], ticker=etf["ticker"], date=today_snap["date"])
        await _send_chunked(message.channel, header + report_text)
    except Exception:
        logger.exception(f"On-demand report generation failed for {etf['name']}")
        await message.channel.send(t("report_error", lang))


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
