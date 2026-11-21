from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tokenizer.config import CACHE_MAX_AGE_SECONDS, PRICING_URL, USER_AGENT
from tokenizer.opencode_db import UsageRecord

PROVIDER = "opencode-go"


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float
    cache_write: float
    monthly_limit: float | None

    def cost(self, record: UsageRecord) -> float:
        """Coste en dólares. Precios por millón de tokens."""
        return (
            record.input * self.input
            + record.output * self.output
            + record.cache_read * self.cache_read
            + record.cache_write * self.cache_write
        ) / 1_000_000


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def parse_models(payload: dict[str, Any], plan: str = "go") -> dict[str, ModelPrice]:
    prices: dict[str, ModelPrice] = {}
    for item in payload.get("data", []):
        text = (item.get("cost") or {}).get("text") or {}
        cost_input = text.get("input") or {}
        cost_output = text.get("output") or {}
        cache = cost_input.get("cache") or {}
        go = item.get("go") or {}
        monthly = (go.get("monthly_usage") or {}).get(plan)
        prices[item["id"]] = ModelPrice(
            input=_number(cost_input.get("price")),
            output=_number(cost_output.get("price")),
            cache_read=_number(cache.get("read")),
            cache_write=_number(cache.get("write")),
            monthly_limit=float(monthly) if monthly else None,
        )
    return prices


def load_prices(cache_file: Path, plan: str = "go") -> dict[str, ModelPrice]:
    """Usa la caché local si es reciente; si no, descarga el catálogo de Go."""
    fresh = cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_SECONDS
    if not fresh:
        try:
            request = urllib.request.Request(PRICING_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            if not cache_file.exists():
                raise
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    return parse_models(payload, plan)
