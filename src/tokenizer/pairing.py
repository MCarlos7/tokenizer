from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import socket
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tokenizer.config import DISCOVERY_PORT, USER_AGENT, cache_dir
from tokenizer.peers import Peer, decode_heartbeat

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8
CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5

_lock = threading.Lock()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _path() -> Path:
    return cache_dir() / "pairing.json"


def _normalize(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _digest(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{_normalize(code)}".encode("utf-8")).hexdigest()


def _read() -> dict[str, Any] | None:
    path = _path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _discard() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass


def _expires(data: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(data["expires_at"])


def open_pairing(now: datetime | None = None) -> str:
    """Crea un código de un solo uso. Solo se guarda su hash con sal."""
    now = now or datetime.now(timezone.utc)
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    salt = secrets.token_hex(16)
    with _lock:
        _write(
            {
                "salt": salt,
                "digest": _digest(salt, raw),
                "expires_at": (now + CODE_TTL).isoformat(),
                "attempts": 0,
            }
        )
    return f"{raw[:4]}-{raw[4:]}"


def pairing_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    with _lock:
        data = _read()
    if data is None:
        return False
    try:
        return _expires(data) > now
    except (KeyError, ValueError):
        return False


def redeem(code: str, now: datetime | None = None) -> bool:
    """Valida el código. Cuando es correcto, lo invalida."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        data = _read()
        try:
            valid_time = data is not None and _expires(data) > now
        except (KeyError, ValueError):
            valid_time = False
        if data is None or not valid_time:
            _discard()
            return False
        if hmac.compare_digest(_digest(data["salt"], code), data["digest"]):
            _discard()
            return True
        data["attempts"] = int(data.get("attempts", 0)) + 1
        if data["attempts"] >= MAX_ATTEMPTS:
            _discard()
        else:
            _write(data)
        return False


def find_pairing_host(timeout: float) -> Peer | None:
    """Espera a un host que tenga un código de emparejamiento abierto."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", DISCOVERY_PORT))
    sock.settimeout(1.0)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                raw, (address, _) = sock.recvfrom(4096)
            except socket.timeout:
                continue
            peer = decode_heartbeat(raw, address, None, time.monotonic())
            if peer is not None and peer.pairing:
                return peer
    finally:
        sock.close()
    return None


def request_pairing(host: Peer, code: str) -> dict[str, Any]:
    body = json.dumps({"code": code}).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host.address}:{host.port}/api/pair",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
