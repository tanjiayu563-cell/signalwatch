import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def load_environment() -> None:
    load_env_file(BASE_DIR / ".env")


load_environment()

DATA_DIR = Path(os.getenv("MONITOR_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = Path(os.getenv("MONITOR_DB_PATH", str(DATA_DIR / "monitor.db")))
HOST = os.getenv("MONITOR_HOST", "127.0.0.1")
PORT = int(os.getenv("MONITOR_PORT", "8765"))
SCAN_INTERVAL_SECONDS = max(60, int(os.getenv("MONITOR_SCAN_INTERVAL", "300")))
HTTP_TIMEOUT_SECONDS = max(5, int(os.getenv("MONITOR_HTTP_TIMEOUT", "15")))
MAX_ITEMS_PER_SOURCE = max(10, int(os.getenv("MONITOR_ITEMS_PER_SOURCE", "60")))
USER_AGENT = os.getenv(
    "MONITOR_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
