from pathlib import Path

from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_MEDIA_DIR = ROOT / "static" / "media"
DB_PATH = DATA_DIR / "members.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

APP_PASSWORD = os.getenv("APP_PASSWORD", "Reset@123")
SESSION_SECRET = os.getenv("SESSION_SECRET", "rid3206-monthly-report-dev-secret")
ASKEVA_TOKEN = os.getenv("ASKEVA_TOKEN", "").strip()
ASKEVA_TEMPLATE = os.getenv("ASKEVA_TEMPLATE", "monthly_report").strip()
ASKEVA_TEMPLATE_LANG = os.getenv("ASKEVA_TEMPLATE_LANG", "en").strip()
ASKEVA_API_URL = os.getenv(
    "ASKEVA_API_URL", "https://backend.askeva.io/v1/message/send-message"
).strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SEND_DELAY_MS = int(os.getenv("SEND_DELAY_MS", "350"))
PORT = int(os.getenv("PORT", "8000"))
MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "64"))
