from datetime import datetime, timezone

from tokenizer.opencode_db import UsageRecord
from tokenizer.pricing import ModelPrice, parse_models
from tokenizer.usage import compute_windows, model_breakdown

PRICES = {"model-a": ModelPrice(input=0, output=1.0, cache_read=0, cache_write=0, monthly_limit=10.0)}


def at(*args: int) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


def record(ms: int, output: int) -> UsageRecord:
    return UsageRecord(
        message_id=str(ms),
        provider="opencode-go",
        model="model-a",
        created_ms=ms,
        input=0,
        output=output,
        cache_read=0,
        cache_write=0,
    )


def test_five_hour_window_opens_at_first_use_and_expires():
    start = at(2026, 11, 2, 9, 0)
    records = [record(start, 1_000_000), record(at(2026, 11, 2, 14, 0), 500_000)]
    now = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)

    five_hour = compute_windows(records, PRICES, now=now)[0]

    assert round(five_hour.used_percent, 6) == 5.0
    assert five_hour.resets_at == datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)


def test_five_hour_window_inactive_after_expiry():
    records = [record(at(2026, 11, 2, 9, 0), 1_000_000)]
    now = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)

    five_hour = compute_windows(records, PRICES, now=now)[0]

    assert five_hour.used_percent == 0.0
    assert five_hour.resets_at is None


def test_weekly_window_resets_on_monday_utc():
    records = [record(at(2026, 11, 15, 12, 0), 1_000_000), record(at(2026, 11, 17, 12, 0), 500_000)]
    now = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)

    weekly = compute_windows(records, PRICES, now=now)[1]

    assert round(weekly.used_percent, 6) == 5.0
    assert weekly.resets_at == datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)


def test_free_or_other_provider_usage_is_ignored():
    free = UsageRecord("x", "opencode-go", "unknown", at(2026, 11, 2, 9, 0), 0, 1_000_000, 0, 0)
    other = UsageRecord("y", "openai", "model-a", at(2026, 11, 2, 9, 0), 0, 1_000_000, 0, 0)
    now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)

    windows = compute_windows([free, other], PRICES, now=now)

    assert all(window.used_percent == 0.0 for window in windows)


def test_monthly_window_follows_renewal_date():
    renews_at = datetime(2026, 12, 18, 23, 0, tzinfo=timezone.utc)
    records = [record(at(2026, 11, 19, 12, 0), 1_000_000), record(at(2026, 11, 25, 12, 0), 500_000)]
    now = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)

    monthly = compute_windows(records, PRICES, now=now, renews_at=renews_at)[2]

    assert round(monthly.used_percent, 6) == 15.0
    assert monthly.resets_at == datetime(2026, 12, 18, 23, 0, tzinfo=timezone.utc)


def test_model_breakdown_reports_cost_and_equivalent_remaining():
    prices = {"model-a": ModelPrice(input=0, output=1.0, cache_read=0, cache_write=0, monthly_limit=10.0)}
    records = [record(at(2026, 11, 2, 9, 0), 2_000_000), record(at(2026, 11, 3, 9, 0), 1_000_000)]

    rows = model_breakdown(
        records,
        prices,
        since=datetime(2026, 11, 1, tzinfo=timezone.utc),
        remaining_percent=75.0,
    )

    assert len(rows) == 1
    assert round(rows[0].cost_usd, 6) == 3.0
    assert round(rows[0].percent, 6) == 30.0
    assert rows[0].monthly_limit == 10.0
    assert round(rows[0].equivalent_remaining_usd, 6) == 7.5


def test_parse_models_reads_plan_limit_and_prices():
    payload = {
        "data": [
            {
                "id": "model-a",
                "cost": {"text": {"input": {"price": 0.1, "cache": {"read": 0.01}}, "output": {"price": 0.5}}},
                "go": {"monthly_usage": {"go": 15, "go-plus": 60}},
            },
            {"id": "beam-free", "cost": {"text": {}}, "go": {"monthly_usage": None}},
        ]
    }

    prices = parse_models(payload, plan="go")

    assert prices["model-a"].monthly_limit == 15
    assert prices["model-a"].output == 0.5
    assert prices["beam-free"].monthly_limit is None


def test_cache_write_ttl_and_long_context_price_match_go_request_log():
    payload = {
        "data": [
            {
                "id": "claude-haiku-5-5",
                "cost": {
                    "text": {
                        "input": {
                            "price": 0.1,
                            "cache": {"read": 0.01, "write": 0.125},
                            "overrides": [
                                {
                                    "when": {"context": {"gt": 100000}},
                                    "price": 0.5,
                                    "cache": {"read": 0.05, "write": 0.625},
                                }
                            ],
                        },
                        "output": {
                            "price": 0.5,
                            "overrides": [{"when": {"context": {"gt": 100000}}, "price": 2.5}],
                        },
                    }
                },
                "go": {"monthly_usage": {"go": 15}},
            }
        ]
    }
    price = parse_models(payload)["claude-haiku-5-5"]
    request = UsageRecord(
        message_id="anonymized-sample",
        provider="opencode-go",
        model="claude-haiku-5-5",
        created_ms=at(2026, 11, 21, 12, 0),
        input=2,
        output=1018,
        cache_read=327950,
        cache_write=4581,
    )

    # Anonymized request-log cost: $0.02180663.
    assert abs(price.cost(request) - 0.02180663) < 1e-8


def test_cache_write_ttl_uses_shortest_catalog_price():
    payload = {
        "data": [
            {
                "id": "gpt-6-luna",
                "cost": {
                    "text": {
                        "input": {
                            "price": 0.1,
                            "cache": {"read": 0.01, "write": {"12h": 0.25, "30m": 0.125}},
                        },
                        "output": {"price": 0.5},
                    }
                },
                "go": {"monthly_usage": {"go": 15}},
            }
        ]
    }

    price = parse_models(payload)["gpt-6-luna"]

    assert price.cache_write == 0.125
    request = UsageRecord("sample", "opencode-go", "gpt-6-luna", at(2026, 11, 21, 12), 0, 0, 0, 100_000)
    assert price.cost(request) == 0.0125
