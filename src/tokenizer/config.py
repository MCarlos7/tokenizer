from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRICING_URL = "https://opencode.ai/inference/go/v1/models"
USER_AGENT = "tokenizer/0.1"
CACHE_MAX_AGE_SECONDS = 24 * 3600

# Panel y API HTTP (host) y descubrimiento por UDP en la red local.
DEFAULT_PORT = 8765
DISCOVERY_PORT = 8766
FIREWALL_RULES = {
    "Tokenizer HTTP 8765": ("TCP", DEFAULT_PORT),
    "Tokenizer descubrimiento 8766": ("UDP", DISCOVERY_PORT),
}
HEARTBEAT_SECONDS = 5
PEER_TIMEOUT_SECONDS = 30
STARTUP_LISTEN_SECONDS = 6
SYNC_SECONDS = 60

DEFAULT_ALERT_PERCENT = 80.0
CALIBRATION_MAX_AGE_DAYS = 7
CALIBRATION_DRIFT_POINTS = 10.0

PLANS = ("go", "go-plus", "go-teams")


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "tokenizer"


def host_db_path() -> Path:
    return cache_dir() / "host.db"


def user_config_path() -> Path:
    """Configuración personal de cada usuario, fuera del repositorio."""
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "tokenizer" / "config.json"


def load_user_config() -> dict[str, Any]:
    path = user_config_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_user_config(values: dict[str, Any]) -> None:
    current = load_user_config()
    current.update(values)
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def parse_datetime(value: str) -> datetime:
    """Acepta AAAA-MM-DD, AAAA-MM-DDTHH:MM o con Z. Sin zona horaria, asume UTC."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def machine_name() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


@dataclass(frozen=True)
class Settings:
    machine: str
    token: str | None
    plan: str
    db: Path
    renews_at: datetime | None
    alert_percent: float
    calibration_factor: float
    calibrated_at: datetime | None
    calibration_base: float | None = None


def load_settings() -> Settings:
    raw = load_user_config()
    return Settings(
        machine=raw.get("machine") or machine_name(),
        token=raw.get("token") or None,
        plan=raw.get("plan", "go"),
        db=Path(raw["db"]) if raw.get("db") else default_db_path(),
        renews_at=parse_datetime(raw["renews_at"]) if raw.get("renews_at") else None,
        alert_percent=float(raw.get("alert_percent", DEFAULT_ALERT_PERCENT)),
        calibration_factor=float(raw.get("calibration_factor", 1.0)),
        calibrated_at=parse_datetime(raw["calibrated_at"]) if raw.get("calibrated_at") else None,
        calibration_base=float(raw["calibration_base"]) if raw.get("calibration_base") is not None else None,
    )
