# ETF Analyzer

A personal Discord bot that automatically analyzes daily ETF holdings changes and delivers morning reports via Discord DM.  
It distinguishes intentional portfolio moves by the fund manager from passive changes caused by fund creation/redemption flows, and generates AI-powered insights using Claude.

## Features

- **Daily Auto Report** — Sends holdings change analysis to your Discord DM every day at 08:00 KST
- **Intentional Change Detection** — Strips out creation/redemption noise to isolate the fund manager's actual buy/sell decisions
- **Weekly Insights** — Every Sunday at 10:00 KST, generates and stores cumulative operational pattern analysis
- **On-demand Insight Query** — Type `/insight` in Discord DM to instantly retrieve the latest stored insight
- **Auto Historical Backfill** — When a new ETF is added, automatically fills in missing historical data from the listing date

## Supported ETFs

| ETF | Ticker | Data Source |
|-----|--------|-------------|
| TIME Global AI Active ETF | 456600 | timeetf.co.kr |
| TIME US Nasdaq 100 Active ETF | 426030 | timeetf.co.kr |
| TIME KOSPI Active ETF | 385720 | timeetf.co.kr |
| iShares A.I. Innovation and Tech Active ETF | BAI | iShares CSV API |

## Quick Start

### 1. Prerequisites

You need three things:

- **Python 3.10+**
- **Discord Bot Token** — Create a bot at [Discord Developer Portal](https://discord.com/developers/applications)
- **Anthropic API Key** — Get one at [console.anthropic.com](https://console.anthropic.com)

#### Discord Bot Setup

**Step 1 — Create a bot and get the token**
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → enter a name → Create
3. In the left sidebar, click **Bot**
4. Under **Token**, click **Reset Token** → copy the token (this is your `DISCORD_BOT_TOKEN`)
5. Scroll down to **Privileged Gateway Intents** and enable **Message Content Intent** → Save Changes

**Step 2 — Generate a server invite URL**
1. In the left sidebar, click **OAuth2**
2. Select the **OAuth2 URL Generator** tab
3. Under **SCOPES**, check `bot`
4. Under **BOT PERMISSIONS** (appears after checking `bot`), check:
   - `Send Messages`
   - `Read Message History`
   - `Read Messages/View Channels`
5. Copy the **GENERATED URL** at the bottom → open it in a browser → select your server → Authorize

> If you don't have a test server, create a new Discord server and invite the bot there.  
> The bot must share a server with you to be able to send you DMs.

**Step 3 — Find your user ID**
1. Discord → Settings → Advanced → enable **Developer Mode**
2. Right-click your profile → **Copy User ID** (this is your `DISCORD_USER_ID`)

### 2. Install

```bash
git clone https://github.com/zenibakoLee/etfAnalyzer.git
cd etfAnalyzer
pip install -r requirements.txt
```

### 3. Configure

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

```env
DISCORD_BOT_TOKEN=your_bot_token_here        # Discord bot token
DISCORD_USER_ID=your_discord_user_id_here    # Your Discord user ID (report recipient)
ANTHROPIC_API_KEY=your_anthropic_api_key     # Anthropic API key
DB_PATH=./data/etf_analyzer.db              # Database path (default is fine)
SCHEDULE_HOUR=8                              # Daily report hour (KST, 24h)
SCHEDULE_MINUTE=0
```

### 4. Run

**Local development (recommended)** — auto-restarts on file changes:
```bash
python dev.py
```

**Production (Railway etc.)** — single run:
```bash
python -m src.main
```

Expected output on successful startup:
```
Database initialized
Scheduler started: daily=08:00 KST, weekly insight=Sun 10:00 KST
Health server listening on port 8080
Starting Discord bot...
Discord bot ready: YourBot#1234
```

> **Port conflict**: Run `lsof -ti:8080 | xargs kill -9` or use `PORT=8081 python dev.py`

## Discord Commands

Send these commands to the bot via **DM**:

| Command | Description |
|---------|-------------|
| `/insight` | Shows the ETF list, select a number to retrieve the latest insight |

## How It Works

```
Every day at 08:00 KST
  → Auto-backfill any missing historical dates (per ETF listing date)
  → Scrape today's holdings for each ETF
  → Calculate baseline ratio (creation/redemption scaling factor)
  → Classify changes: intentional trade vs price drift
  → Generate per-ETF report with Claude AI
  → Generate market-wide headline with Claude AI
  → Send report via Discord DM

Every Sunday at 10:00 KST
  → Analyze full cumulative history
  → Generate and store operational pattern insights per ETF
```

### Baseline Ratio — Key Concept

ETFs issue and redeem shares daily (creation/redemption). This mechanically scales all holdings proportionally, making it hard to distinguish a manager's intentional trade from a passive scaling effect.

This tool calculates the **median of (today_qty / yesterday_qty)** across all commonly held positions as the baseline ratio, then flags positions that deviate more than 5% from this baseline as intentional changes.

## Project Structure

```
src/
  main.py       Entry point (DB init, scheduler, health server, bot start)
  config.py     Environment variable loading
  scraper.py    ETF holdings scraper (timeetf.co.kr, iShares)
  database.py   SQLite CRUD layer
  analyzer.py   Change detection logic + Claude API calls
  scheduler.py  Daily / weekly cron jobs
  bot.py        Discord event handler

docs/
  prd.md              Product requirements
  data-schema.md      Database schema
  code-architecture.md Code structure
  adr.md              Architecture decision records
```

## Adding a New ETF

Add an entry to `DEFAULT_ETFS` in `src/database.py`:

```python
DEFAULT_ETFS = [
    # (id, name, ticker, url, backfill_from)
    ...,
    (5, "New ETF Name", "TICKER", "https://...", "YYYY-MM-DD"),
]
```

- **timeetf.co.kr ETFs**: URL format `https://timeetf.co.kr/m11_view.php?idx=N`
- **iShares ETFs**: URL format `https://www.ishares.com/.../1467271812596.ajax?tab=holdings&fileType=csv`

## Tech Stack

- Python 3.10+, asyncio
- discord.py, APScheduler, aiohttp
- anthropic SDK (Claude claude-sonnet-4-6 with prompt caching)
- SQLite, BeautifulSoup4

## License

Built for personal use.
