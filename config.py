"""Configuration: everything comes from environment variables (GitHub Secrets)."""
import os
import sys


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(2)  # exit code 2 = configuration error (workflow will not retry)
    return value


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


TELEGRAM_BOT_TOKEN = _required("TELEGRAM_BOT_TOKEN")
IMAGE_API_KEY = _required("IMAGE_API_KEY")
try:
    ADMIN_ID = int(_required("ADMIN_ID"))
except ValueError:
    print("ADMIN_ID must be a number", file=sys.stderr)
    sys.exit(2)

# Optional settings (can be changed from the workflow file / env)
IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "pollinations").strip().lower()
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "https://gen.pollinations.ai").strip()
DEFAULT_MODEL = os.environ.get("IMAGE_MODEL", "flux").strip()
DB_PATH = os.environ.get("DB_PATH", "data/bot.db").strip()
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 120)  # seconds per API call
MAX_CONCURRENT = _int("MAX_CONCURRENT", 3)  # simultaneous generations (all users)
