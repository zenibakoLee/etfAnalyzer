import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DISCORD_USER_ID = int(os.environ["DISCORD_USER_ID"])
DB_PATH = os.environ.get("DB_PATH", "./data/etf_analyzer.db")
PORT = int(os.environ.get("PORT", 8080))
SCHEDULE_HOUR = int(os.environ.get("SCHEDULE_HOUR", 8))
SCHEDULE_MINUTE = int(os.environ.get("SCHEDULE_MINUTE", 0))
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
