from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_MEDIA_DIR = ROOT / "static" / "media"
DB_PATH = DATA_DIR / "members.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    "APP_PASSWORD": "Reset@123",
    "SESSION_SECRET": "rid3206-monthly-report-dev-secret",
    "ASKEVA_TOKEN": "",
    "ASKEVA_TEMPLATE": "monthly_report",
    "ASKEVA_TEMPLATE_LANG": "en",
    "ASKEVA_API_URL": "https://backend.askeva.io/v1/message/send-message",
    "PUBLIC_BASE_URL": "http://127.0.0.1:8000",
    "SEND_DELAY_MS": "350",
    "PORT": "8000",
    "MAX_PDF_MB": "64",
}

EDITABLE_FIELDS = [
    ("APP_PASSWORD", "Login password", "password"),
    ("ASKEVA_TOKEN", "AskEva API token", "password"),
    ("ASKEVA_TEMPLATE", "WhatsApp template name", "text"),
    ("ASKEVA_TEMPLATE_LANG", "Template language code", "text"),
    ("ASKEVA_API_URL", "AskEva send URL", "text"),
    ("PUBLIC_BASE_URL", "Public base URL for PDFs", "text"),
    ("SEND_DELAY_MS", "Delay between messages (ms)", "int"),
    ("MAX_PDF_MB", "Max PDF size (MB)", "int"),
    ("PORT", "App port (restart required)", "int"),
    ("SESSION_SECRET", "Session secret", "password"),
]

APP_PASSWORD = DEFAULTS["APP_PASSWORD"]
SESSION_SECRET = DEFAULTS["SESSION_SECRET"]
ASKEVA_TOKEN = ""
ASKEVA_TEMPLATE = DEFAULTS["ASKEVA_TEMPLATE"]
ASKEVA_TEMPLATE_LANG = DEFAULTS["ASKEVA_TEMPLATE_LANG"]
ASKEVA_API_URL = DEFAULTS["ASKEVA_API_URL"]
PUBLIC_BASE_URL = DEFAULTS["PUBLIC_BASE_URL"]
SEND_DELAY_MS = 350
PORT = 8000
MAX_PDF_MB = 64


def running_on_streamlit_cloud() -> bool:
    return Path("/mount/src").exists() or os.getenv("STREAMLIT_RUNTIME_ENV") == "cloud"


def _load_streamlit_secrets() -> None:
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

        if get_script_run_ctx() is None:
            return
        import streamlit as st

        secrets = st.secrets
    except Exception:
        return
    for key in DEFAULTS:
        try:
            if key in secrets:
                os.environ[key] = str(secrets[key]).strip()
        except Exception:
            continue


def _apply() -> None:
    global APP_PASSWORD, SESSION_SECRET, ASKEVA_TOKEN, ASKEVA_TEMPLATE
    global ASKEVA_TEMPLATE_LANG, ASKEVA_API_URL, PUBLIC_BASE_URL
    global SEND_DELAY_MS, PORT, MAX_PDF_MB
    APP_PASSWORD = os.getenv("APP_PASSWORD", DEFAULTS["APP_PASSWORD"])
    SESSION_SECRET = os.getenv("SESSION_SECRET", DEFAULTS["SESSION_SECRET"])
    ASKEVA_TOKEN = os.getenv("ASKEVA_TOKEN", "").strip()
    ASKEVA_TEMPLATE = os.getenv("ASKEVA_TEMPLATE", DEFAULTS["ASKEVA_TEMPLATE"]).strip()
    ASKEVA_TEMPLATE_LANG = os.getenv("ASKEVA_TEMPLATE_LANG", DEFAULTS["ASKEVA_TEMPLATE_LANG"]).strip()
    ASKEVA_API_URL = os.getenv("ASKEVA_API_URL", DEFAULTS["ASKEVA_API_URL"]).strip()
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", DEFAULTS["PUBLIC_BASE_URL"]).rstrip("/")
    SEND_DELAY_MS = int(os.getenv("SEND_DELAY_MS", DEFAULTS["SEND_DELAY_MS"]))
    PORT = int(os.getenv("PORT", DEFAULTS["PORT"]))
    MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", DEFAULTS["MAX_PDF_MB"]))


def reload() -> None:
    load_dotenv(ENV_PATH, override=True)
    _load_streamlit_secrets()
    _apply()


def apply_request_public_url() -> str | None:
    """On a public Streamlit host, use that URL so AskEva can fetch PDFs."""
    global PUBLIC_BASE_URL
    try:
        import streamlit as st

        headers = st.context.headers
        host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(",")[0].strip()
        proto = (headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
    except Exception:
        return None
    if not host or host.startswith("127.") or "localhost" in host:
        return None
    url = f"{proto}://{host}".rstrip("/")
    current_host = urlparse(PUBLIC_BASE_URL).hostname or ""
    if not PUBLIC_BASE_URL or current_host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        PUBLIC_BASE_URL = url
        os.environ["PUBLIC_BASE_URL"] = url
        return url
    return None


def values() -> dict[str, str]:
    return {
        "APP_PASSWORD": APP_PASSWORD,
        "SESSION_SECRET": SESSION_SECRET,
        "ASKEVA_TOKEN": ASKEVA_TOKEN,
        "ASKEVA_TEMPLATE": ASKEVA_TEMPLATE,
        "ASKEVA_TEMPLATE_LANG": ASKEVA_TEMPLATE_LANG,
        "ASKEVA_API_URL": ASKEVA_API_URL,
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
        "SEND_DELAY_MS": str(SEND_DELAY_MS),
        "PORT": str(PORT),
        "MAX_PDF_MB": str(MAX_PDF_MB),
    }


def save_env(updates: dict[str, str]) -> None:
    cleaned = {}
    for key, raw in updates.items():
        if key not in DEFAULTS:
            continue
        text = "" if raw is None else str(raw).strip()
        if key == "PUBLIC_BASE_URL":
            text = text.rstrip("/")
        if key in {"SEND_DELAY_MS", "PORT", "MAX_PDF_MB"}:
            if not text.isdigit() or int(text) < 0:
                raise ValueError(f"{key} must be a non-negative number")
        cleaned[key] = text

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in cleaned:
            out.append(f"{key}={cleaned[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in cleaned.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ.update(cleaned)
    _apply()


reload()
