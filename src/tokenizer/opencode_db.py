from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UsageRecord:
    message_id: str
    provider: str
    model: str
    created_ms: int
    input: int
    output: int
    cache_read: int
    cache_write: int


def read_usage(db_path: Path, since_ms: int = 0) -> list[UsageRecord]:
    """Lee los mensajes del asistente con tokens desde opencode.db en modo solo lectura."""
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, time_created, data FROM session_message "
            "WHERE type = 'assistant' AND time_created >= ? ORDER BY time_created",
            (since_ms,),
        ).fetchall()
    finally:
        conn.close()

    records: list[UsageRecord] = []
    for message_id, created_ms, raw in rows:
        data = json.loads(raw)
        tokens = data.get("tokens")
        model = data.get("model") or {}
        if not tokens or not model.get("id"):
            continue
        cache = tokens.get("cache") or {}
        records.append(
            UsageRecord(
                message_id=message_id,
                provider=model.get("providerID", ""),
                model=model["id"],
                created_ms=created_ms,
                input=tokens.get("input") or 0,
                output=tokens.get("output") or 0,
                cache_read=cache.get("read") or 0,
                cache_write=cache.get("write") or 0,
            )
        )
    return records
