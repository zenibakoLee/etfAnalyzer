import asyncio
import logging
import time
import pytz
from datetime import datetime, date, timedelta

import discord
import httpx
from src import analyzer, database as db
from src.config import DISCORD_USER_ID, DISCORD_WEBHOOK_URL

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
        "ko": "👋 안녕하세요! ETF Analyzer 봇이 시작되었습니다.\n\n📌 `/report` — ETF 일일 리포트 조회\n📌 `/insight` — 누적 운용 인사이트 조회\n📌 `/returns` — ETF 수익률 비교",
        "en": "👋 Hello! ETF Analyzer bot is online.\n\n📌 `/report` — view daily ETF report\n📌 `/insight` — view cumulative insight\n📌 `/returns` — compare ETF returns",
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
    "returns_choose_period": {
        "ko": "📈 **수익률 비교 — 기간을 선택하세요:**\n\n1. 일간 (1일)\n2. 주간 (5일)\n3. 월간 (1개월)\n4. 연간 (1년)\n\n번호를 입력하세요.",
        "en": "📈 **Returns comparison — choose a period:**\n\n1. Daily (1d)\n2. Weekly (5d)\n3. Monthly (1mo)\n4. Yearly (1yr)\n\nEnter a number.",
    },
    "returns_header": {
        "ko": "📈 **ETF 수익률 비교 ({period})**\n_{date} 기준_\n",
        "en": "📈 **ETF Returns Comparison ({period})**\n_as of {date}_\n",
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

        if state["state"] == "awaiting_returns_period":
            del _user_states[user_id]
            period_map = {"1": "daily", "2": "weekly", "3": "monthly", "4": "yearly"}
            choice = content.strip()
            if choice in period_map:
                await _send_returns_comparison(message.channel, period_map[choice])
            else:
                await message.channel.send(t("out_of_range", n=4))
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
    elif lower in ("/returns", "!returns", "/수익률"):
        await _handle_returns(message)


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

    etfs = [dict(e) for e in db.get_all_etfs()]
    ko = lang == "ko"

    # Collect tasks per category
    backfill_tasks: list[str] = []
    report_tasks: list[str] = []
    insight_tasks: list[str] = []

    etf_lines: list[str] = []
    for etf in etfs:
        snaps = db.get_all_snapshots(etf["id"])
        missing = count_missing_dates(etf)
        last = snaps[-1]["date"] if snaps else None
        issues: list[str] = []

        if missing > 0:
            backfill_tasks.append(f"  • {etf['name']}: {missing}{'일 누락' if ko else ' days missing'}")
            issues.append(f"백필 {missing}{'일' if ko else 'd'} 누락")

        # Report: only flag if today is NOT a confirmed no-data day
        known = db.get_known_dates(etf["id"])
        today_confirmed_no_data = (today_str in known and db.get_snapshot(etf["id"], today_str) is None)
        latest_report = db.get_latest_daily_report(etf["id"])
        if not today_confirmed_no_data and (not latest_report or latest_report["date"] != today_str):
            report_tasks.append(f"  • {etf['name']}")
            issues.append("리포트 미생성" if ko else "report missing")

        # Insight: flag if missing or >7 days old
        insight_row = db.get_latest_insight(etf["id"])
        if not insight_row:
            insight_tasks.append(f"  • {etf['name']}: {'인사이트 없음' if ko else 'no insight'}")
            issues.append("인사이트 없음" if ko else "no insight")
        elif (today - date.fromisoformat(insight_row["date"])).days > 7:
            insight_tasks.append(f"  • {etf['name']}: 마지막 {insight_row['date']}" if ko
                                  else f"  • {etf['name']}: last {insight_row['date']}")
            issues.append(f"인사이트 오래됨({insight_row['date']})" if ko
                          else f"insight stale({insight_row['date']})")

        if issues:
            etf_lines.append(f"⚠️ {etf['name']}: {', '.join(issues)}")
        else:
            etf_lines.append(f"✅ {etf['name']}: {'최신' if ko else 'up to date'}")

    header = t("status_header", lang)
    body = "\n".join(etf_lines)

    needs_work = backfill_tasks or report_tasks or insight_tasks
    if not needs_work:
        await channel.send(f"{header}\n{body}\n\n{t('nothing_needed', lang)}")
        return

    # Build explicit task list
    task_lines: list[str] = []
    if backfill_tasks:
        task_lines.append("📊 **백필 필요:**" if ko else "📊 **Backfill needed:**")
        task_lines.extend(backfill_tasks)
    if report_tasks:
        task_lines.append("📋 **리포트 미생성:**" if ko else "📋 **Report missing:**")
        task_lines.extend(report_tasks)
    if insight_tasks:
        task_lines.append("💡 **인사이트 갱신 필요:**" if ko else "💡 **Insight refresh needed:**")
        task_lines.extend(insight_tasks)

    ask = t("ask_startup", lang)
    await channel.send(f"{header}\n{body}\n\n" + "\n".join(task_lines) + f"\n{ask}")
    _user_states[DISCORD_USER_ID] = {"state": "awaiting_startup_confirm"}


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


# ── /returns ─────────────────────────────────────────────────────────────────

async def _handle_returns(message: discord.Message):
    lang = db.get_preference("language") or "en"
    await message.channel.send(t("returns_choose_period", lang))
    _user_states[message.author.id] = {"state": "awaiting_returns_period"}


async def _send_returns_comparison(channel, period: str):
    lang = db.get_preference("language") or "en"
    today = datetime.now(KST).date()

    period_labels = {
        "daily":   {"ko": "일간 (1일)", "en": "Daily (1d)", "days": 1},
        "weekly":  {"ko": "주간 (5일)", "en": "Weekly (5d)", "days": 5},
        "monthly": {"ko": "월간 (1개월)", "en": "Monthly (1mo)", "days": 21},
        "yearly":  {"ko": "연간 (1년)", "en": "Yearly (1yr)", "days": 252},
    }
    p = period_labels[period]
    label = p[lang]
    days_needed = p["days"]

    etfs = [dict(e) for e in db.get_all_etfs()]
    rows = []

    for etf in etfs:
        returns = [dict(r) for r in db.get_returns(etf["id"], days=days_needed + 5)]
        if not returns:
            rows.append({"name": etf["name"], "ticker": etf["ticker"], "ret": None, "close": None})
            continue

        returns.sort(key=lambda r: r["date"])
        latest = returns[-1]

        if period == "daily":
            ret = latest["daily_return_pct"]
        elif len(returns) >= days_needed + 1:
            start_price = returns[-(days_needed + 1)]["close_price"]
            end_price = latest["close_price"]
            ret = round(((end_price / start_price) - 1) * 100, 2) if start_price else None
        else:
            start_price = returns[0]["close_price"]
            end_price = latest["close_price"]
            ret = round(((end_price / start_price) - 1) * 100, 2) if start_price else None

        rows.append({
            "name": etf["name"],
            "ticker": etf["ticker"],
            "ret": ret,
            "close": latest["close_price"],
        })

    rows.sort(key=lambda r: r["ret"] if r["ret"] is not None else -999, reverse=True)

    header = t("returns_header", lang, period=label, date=str(today))
    lines = [header]

    for i, r in enumerate(rows, 1):
        if r["ret"] is None:
            lines.append(f"{i}. **{r['name']}** ({r['ticker']}) — 데이터 없음")
            continue
        arrow = "🔺" if r["ret"] > 0 else "🔻" if r["ret"] < 0 else "➖"
        close_str = f"{r['close']:,.2f}" if r["close"] else ""
        lines.append(f"{i}. {arrow} **{r['name']}** ({r['ticker']}): **{r['ret']:+.2f}%** ({close_str})")

    if len(rows) >= 2:
        valid = [r for r in rows if r["ret"] is not None]
        if valid:
            best = valid[0]
            worst = valid[-1]
            spread = round(best["ret"] - worst["ret"], 2) if best["ret"] is not None and worst["ret"] is not None else None
            lines.append("")
            if lang == "ko":
                lines.append(f"📊 최고: {best['ticker']} | 최저: {worst['ticker']} | 격차: {spread:.2f}%p" if spread else "")
            else:
                lines.append(f"📊 Best: {best['ticker']} | Worst: {worst['ticker']} | Spread: {spread:.2f}%p" if spread else "")

    await _send_chunked(channel, "\n".join(lines))


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_chunked(channel, text: str):
    if len(text) <= CHUNK_SIZE:
        await channel.send(text)
        return

    chunks: list[str] = []
    current = ""

    for line in text.split("\n"):
        candidate = (current + "\n" + line) if current else line
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Line too long — split at sentence boundary first, then word, then hard
            while len(line) > CHUNK_SIZE:
                cut = _find_split(line, CHUNK_SIZE)
                chunks.append(line[:cut].rstrip())
                line = line[cut:].lstrip()
            current = line
    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        await channel.send(chunk)
        if i < len(chunks) - 1:
            await asyncio.sleep(0.3)


def _find_split(text: str, limit: int) -> int:
    """Find best split position at or before limit: sentence > word > hard cut."""
    for sep in (". ", "。", "! ", "? ", " "):
        pos = text.rfind(sep, 0, limit)
        if pos != -1:
            return pos + len(sep)
    return limit


async def send_report(text: str):
    """Send report via webhook."""
    if DISCORD_WEBHOOK_URL:
        try:
            await _send_webhook(text)
            logger.info("Daily report sent via webhook")
        except Exception:
            logger.exception("Failed to send webhook report")


async def _send_webhook(text: str):
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = (current + "\n" + line) if current else line
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(line) > CHUNK_SIZE:
                cut = _find_split(line, CHUNK_SIZE)
                chunks.append(line[:cut].rstrip())
                line = line[cut:].lstrip()
            current = line
    if current:
        chunks.append(current)

    async with httpx.AsyncClient() as client:
        for i, chunk in enumerate(chunks):
            resp = await client.post(DISCORD_WEBHOOK_URL, json={"content": chunk})
            resp.raise_for_status()
            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)
