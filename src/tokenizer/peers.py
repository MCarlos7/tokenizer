from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass

PROTOCOL_VERSION = 1
ROLES = ("host", "client")


def token_fingerprint(token: str) -> str:
    """Identifica la red sin revelar el token. Los equipos con otro token se ignoran."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Peer:
    machine: str
    role: str
    address: str
    port: int
    last_seen: float
    pairing: bool = False


class PeerTable:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._peers: dict[str, Peer] = {}

    def update(self, peer: Peer) -> None:
        with self._lock:
            self._peers[peer.machine] = peer

    def fresh(self, timeout: float, now: float | None = None) -> list[Peer]:
        now = time.monotonic() if now is None else now
        with self._lock:
            return [peer for peer in self._peers.values() if now - peer.last_seen < timeout]

    def hosts(self, timeout: float, now: float | None = None) -> list[Peer]:
        return [peer for peer in self.fresh(timeout, now) if peer.role == "host"]


def encode_heartbeat(machine: str, role: str, port: int, fingerprint: str, pairing: bool = False) -> bytes:
    payload = {
        "app": "tokenizer",
        "v": PROTOCOL_VERSION,
        "machine": machine,
        "role": role,
        "port": port,
        "fp": fingerprint,
        "pairing": pairing,
    }
    return json.dumps(payload).encode("utf-8")


def decode_heartbeat(raw: bytes, address: str, fingerprint: str | None, now: float) -> Peer | None:
    """Con fingerprint=None solo acepta hosts que anuncian emparejamiento (equipos sin token)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("app") != "tokenizer" or data.get("v") != PROTOCOL_VERSION:
        return None
    machine, role, port = data.get("machine"), data.get("role"), data.get("port")
    if not isinstance(machine, str) or role not in ROLES or not isinstance(port, int):
        return None
    pairing = data.get("pairing") is True
    if fingerprint is None:
        if not (pairing and role == "host"):
            return None
    elif data.get("fp") != fingerprint:
        return None
    return Peer(machine=machine, role=role, address=address, port=port, last_seen=now, pairing=pairing)


def should_yield(own_machine: str, other_machine: str) -> bool:
    """Si dos equipos son host a la vez, conserva el control el de nombre menor."""
    return other_machine < own_machine
