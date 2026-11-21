from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from tokenizer.opencode_db import UsageRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    machine TEXT NOT NULL,
    message_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_ms INTEGER NOT NULL,
    input INTEGER NOT NULL,
    output INTEGER NOT NULL,
    cache_read INTEGER NOT NULL,
    cache_write INTEGER NOT NULL,
    PRIMARY KEY (machine, message_id)
)
"""


def record_to_dict(record: UsageRecord) -> dict[str, Any]:
    return asdict(record)


def record_from_dict(data: dict[str, Any]) -> UsageRecord:
    return UsageRecord(
        message_id=str(data["message_id"]),
        provider=str(data["provider"]),
        model=str(data["model"]),
        created_ms=int(data["created_ms"]),
        input=int(data["input"]),
        output=int(data["output"]),
        cache_read=int(data["cache_read"]),
        cache_write=int(data["cache_write"]),
    )


class HostStore:
    """Historial de todas las máquinas, guardado por el host."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            with conn:
                conn.execute(SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def upsert(self, machine: str, records: Iterable[UsageRecord]) -> int:
        rows = [
            (
                machine,
                r.message_id,
                r.provider,
                r.model,
                r.created_ms,
                r.input,
                r.output,
                r.cache_read,
                r.cache_write,
            )
            for r in records
        ]
        conn = self._connect()
        try:
            with conn:
                conn.executemany("INSERT OR REPLACE INTO usage VALUES (?,?,?,?,?,?,?,?,?)", rows)
        finally:
            conn.close()
        return len(rows)

    def load(self) -> list[tuple[str, UsageRecord]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT machine, message_id, provider, model, created_ms, input, output, cache_read, cache_write "
                "FROM usage ORDER BY created_ms"
            ).fetchall()
        finally:
            conn.close()
        return [
            (
                machine,
                UsageRecord(
                    message_id=message_id,
                    provider=provider,
                    model=model,
                    created_ms=created_ms,
                    input=input_tokens,
                    output=output_tokens,
                    cache_read=cache_read,
                    cache_write=cache_write,
                ),
            )
            for machine, message_id, provider, model, created_ms, input_tokens, output_tokens, cache_read, cache_write in rows
        ]
