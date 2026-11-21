from __future__ import annotations

import json
import os
from pathlib import Path

PRICING_URL = "https://opencode.ai/inference/go/v1/models"
USER_AGENT = "tokenizer/0.1"
CACHE_MAX_AGE_SECONDS = 24 * 3600

# Puerto del panel y del servidor central. Se eligió uno poco común para no
# chocar con servidores de desarrollo habituales (3000, 5000, 8000, 8080...).
DEFAULT_PORT = 8765

PLANS = ("go", "go-plus", "go-teams")


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "tokenizer"


def user_config_path() -> Path:
    """Configuración personal de cada usuario, fuera del repositorio."""
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "tokenizer" / "config.json"


def load_user_config() -> dict[str, str]:
    path = user_config_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_user_config(values: dict[str, str]) -> None:
    current = load_user_config()
    current.update(values)
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
