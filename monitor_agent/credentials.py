import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DATA_DIR


STORE_PATH = Path(os.getenv("MONITOR_CREDENTIAL_PATH", str(DATA_DIR / "credentials.json")))
ALLOWED_AUTH_TYPES = {"session_cookie", "api_token", "api_key"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> Dict[str, Any]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STORE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, STORE_PATH)
    os.chmod(STORE_PATH, 0o600)


def set_credential(
    source_id: str,
    auth_type: str,
    secret: str,
    endpoint: Optional[str] = None,
) -> None:
    if auth_type not in ALLOWED_AUTH_TYPES:
        raise ValueError("不支持的授权类型")
    if not secret or len(secret.strip()) < 4:
        raise ValueError("授权凭据不能为空")
    source_id = source_id.strip()[:80]
    if not source_id:
        raise ValueError("来源标识不能为空")

    data = _load()
    data[source_id] = {
        "auth_type": auth_type,
        "secret": secret.strip(),
        "endpoint": (endpoint or "").strip()[:500],
        "updated_at": utc_now(),
    }
    _save(data)


def delete_credential(source_id: str) -> bool:
    data = _load()
    existed = source_id in data
    data.pop(source_id, None)
    _save(data)
    return existed


def get_credential(source_id: str) -> Optional[Dict[str, Any]]:
    return _load().get(source_id)


def credential_summary(source_id: str) -> Dict[str, Any]:
    entry = _load().get(source_id)
    if not entry:
        return {"configured": False}
    return {
        "configured": True,
        "auth_type": entry.get("auth_type", ""),
        "endpoint": entry.get("endpoint", ""),
        "updated_at": entry.get("updated_at", ""),
        "hint": "凭据已保存在本机，接口不会回传明文",
    }
