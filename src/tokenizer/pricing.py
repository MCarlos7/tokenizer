from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tokenizer.config import CACHE_MAX_AGE_SECONDS, PRICING_URL, USER_AGENT
from tokenizer.opencode_db import UsageRecord

PROVIDER = "opencode-go"


@dataclass(frozen=True)
class PriceOverride:
    """Catalog price changes when prompt context exceeds a token threshold."""

    context_gt: int
    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write: float | None = None


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float
    cache_write: float
    monthly_limit: float | None
    overrides: tuple[PriceOverride, ...] = ()

    def cost(self, record: UsageRecord) -> float:
        """Estimate one request in USD; catalog rates are per million tokens.

        OpenCode's stored usage separates input, cache reads, and cache writes.
        These all contribute to prompt context for context-tier pricing. When a
        catalog offers cache-write TTL rates, use its shortest TTL: this matches
        the rate observed in Go request logs, where the local message schema
        does not retain the TTL breakdown.
        """
        input_price = self.input
        output_price = self.output
        cache_read_price = self.cache_read
        cache_write_price = self.cache_write
        context = record.input + record.cache_read + record.cache_write
        for tier in self.overrides:
            if context <= tier.context_gt:
                continue
            if tier.input is not None:
                input_price = tier.input
            if tier.output is not None:
                output_price = tier.output
            if tier.cache_read is not None:
                cache_read_price = tier.cache_read
            if tier.cache_write is not None:
                cache_write_price = tier.cache_write
        return (
            record.input * input_price
            + record.output * output_price
            + record.cache_read * cache_read_price
            + record.cache_write * cache_write_price
        ) / 1_000_000


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _cache_write_rate(value: Any) -> float:
    """Resolve a TTL-keyed cache-write price to the shortest available TTL."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, dict):
        return 0.0

    def ttl_seconds(item: tuple[str, Any]) -> tuple[int, str]:
        match = re.fullmatch(r"(\d+)(m|h|d)", str(item[0]))
        if not match:
            return (10**12, str(item[0]))
        amount = int(match.group(1))
        multiplier = {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
        return (amount * multiplier, str(item[0]))

    for _, rate in sorted(value.items(), key=ttl_seconds):
        if isinstance(rate, (int, float)):
            return float(rate)
    return 0.0


def _context_threshold(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    context = value.get("context")
    if not isinstance(context, dict):
        return None
    threshold = context.get("gt")
    return int(threshold) if isinstance(threshold, (int, float)) else None


def _override_rates(raw: dict[str, Any]) -> dict[str, float | None]:
    cache = raw.get("cache") or {}
    return {
        "input": _number(raw["price"]) if isinstance(raw.get("price"), (int, float)) else None,
        "cache_read": _number(cache["read"]) if isinstance(cache.get("read"), (int, float)) else None,
        "cache_write": _cache_write_rate(cache["write"]) if "write" in cache else None,
    }


def parse_models(payload: dict[str, Any], plan: str = "go") -> dict[str, ModelPrice]:
    prices: dict[str, ModelPrice] = {}
    for item in payload.get("data", []):
        text = (item.get("cost") or {}).get("text") or {}
        cost_input = text.get("input") or {}
        cost_output = text.get("output") or {}
        cache = cost_input.get("cache") or {}

        overrides: dict[int, dict[str, float | None]] = {}
        for raw in cost_input.get("overrides") or []:
            if not isinstance(raw, dict):
                continue
            threshold = _context_threshold(raw.get("when"))
            if threshold is not None:
                overrides.setdefault(threshold, {}).update(_override_rates(raw))
        for raw in cost_output.get("overrides") or []:
            if not isinstance(raw, dict):
                continue
            threshold = _context_threshold(raw.get("when"))
            if threshold is not None and isinstance(raw.get("price"), (int, float)):
                overrides.setdefault(threshold, {})["output"] = float(raw["price"])

        go = item.get("go") or {}
        monthly = (go.get("monthly_usage") or {}).get(plan)
        prices[item["id"]] = ModelPrice(
            input=_number(cost_input.get("price")),
            output=_number(cost_output.get("price")),
            cache_read=_number(cache.get("read")),
            cache_write=_cache_write_rate(cache.get("write")),
            monthly_limit=float(monthly) if monthly else None,
            overrides=tuple(
                PriceOverride(context_gt=threshold, **rates)
                for threshold, rates in sorted(overrides.items())
            ),
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
