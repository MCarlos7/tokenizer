from __future__ import annotations

import json
import os
import random
import socket
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timezone

from tokenizer.alerts import evaluate_alerts
from tokenizer.calibration import drift_points
from tokenizer.config import (
    DEFAULT_PORT,
    DISCOVERY_PORT,
    HEARTBEAT_SECONDS,
    PEER_TIMEOUT_SECONDS,
    STARTUP_LISTEN_SECONDS,
    SYNC_SECONDS,
    USER_AGENT,
    Settings,
    cache_dir,
    host_db_path,
    load_settings,
)
from tokenizer.host_store import HostStore, record_to_dict
from tokenizer.notify import notify
from tokenizer.opencode_db import UsageRecord, read_usage
from tokenizer.peers import Peer, PeerTable, decode_heartbeat, encode_heartbeat, should_yield, token_fingerprint
from tokenizer.pairing import pairing_open
from tokenizer.pricing import load_prices
from tokenizer.server import TOKEN_HEADER, TokenizerHTTPServer, build_status
from tokenizer.service import clear_pid, write_pid

UPLOAD_CHUNK = 500


def log(message: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)


class Daemon:
    """Un proceso por equipo. Anuncia su presencia, elige host y sincroniza el uso."""

    def __init__(self, settings: Settings) -> None:
        if not settings.token:
            raise ValueError("Falta el token compartido: tokenizer config --token TU_TOKEN")
        self.settings = settings
        self.fingerprint = token_fingerprint(settings.token)
        self.peers = PeerTable()
        self.role = "client"
        self.server: TokenizerHTTPServer | None = None
        self.store: HostStore | None = None
        self.cursor = 0
        self.sync_target: str | None = None
        self.alerts: set[str] = set()
        self.sync_due = True
        self.last_sync = 0.0
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None

    def run(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", DISCOVERY_PORT))
        self.sock.settimeout(1.0)
        write_pid()
        try:
            threading.Thread(target=self._listen, daemon=True).start()
            log(f"Tokenizer activo como '{self.settings.machine}'. Buscando otros equipos...")
            self._send_heartbeat()
            self.stop_event.wait(STARTUP_LISTEN_SECONDS)

            if self.peers.hosts(PEER_TIMEOUT_SECONDS):
                log("Ya hay un host en la red; este equipo se conecta como cliente.")
            else:
                self._become_host()

            while not self.stop_event.is_set():
                self._send_heartbeat()
                self._elect()
                if self.sync_due or time.monotonic() - self.last_sync >= SYNC_SECONDS:
                    self._sync()
                self.stop_event.wait(HEARTBEAT_SECONDS)
        finally:
            self.stop()
            clear_pid(os.getpid())

    def stop(self) -> None:
        self.stop_event.set()
        self._stop_server()
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _listen(self) -> None:
        while not self.stop_event.is_set():
            sock = self.sock
            if sock is None:
                return
            try:
                raw, (address, _) = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            peer = decode_heartbeat(raw, address, self.fingerprint, time.monotonic())
            if peer is not None and peer.machine != self.settings.machine:
                self.peers.update(peer)

    def _send_heartbeat(self) -> None:
        if self.sock is None:
            return
        payload = encode_heartbeat(
            self.settings.machine,
            self.role,
            DEFAULT_PORT,
            self.fingerprint,
            pairing=self.role == "host" and pairing_open(),
        )
        try:
            self.sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
        except OSError as error:
            log(f"No pude enviar el latido: {error}")

    def _elect(self) -> None:
        hosts = self.peers.hosts(PEER_TIMEOUT_SECONDS)
        if self.role == "host":
            if any(should_yield(self.settings.machine, peer.machine) for peer in hosts):
                log("Otro equipo tiene prioridad como host; cambio a cliente.")
                self._stop_server()
                self.role = "client"
                self.sync_due = True
            return
        if not hosts:
            time.sleep(random.uniform(0, 2))
            if not self.peers.hosts(PEER_TIMEOUT_SECONDS):
                self._become_host()

    def _become_host(self) -> None:
        try:
            self.store = HostStore(host_db_path())
            self.server = TokenizerHTTPServer(
                ("0.0.0.0", DEFAULT_PORT),
                self.store,
                self.peers,
                load_settings,
                lambda: load_prices(cache_dir() / "prices.json", plan=load_settings().plan),
            )
        except OSError as error:
            log(f"No puedo ser host (puerto {DEFAULT_PORT} ocupado o red no disponible): {error}")
            self.role = "client"
            return
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.role = "host"
        self.cursor = 0
        self.sync_target = None
        self.sync_due = True
        log(f"Sin otros equipos activos: este equipo es el host. Panel: http://localhost:{DEFAULT_PORT}")

    def _stop_server(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def _read_local(self) -> list[UsageRecord]:
        if not self.settings.db.exists():
            return []
        try:
            return read_usage(self.settings.db, since_ms=self.cursor)
        except sqlite3.Error as error:
            log(f"No pude leer OpenCode ({self.settings.db}): {error}")
            return []

    def _sync(self) -> None:
        self.sync_due = False
        self.last_sync = time.monotonic()

        if self.role == "host":
            records = self._read_local()
            if records and self.store is not None:
                self.store.upsert(self.settings.machine, records)
                self.cursor = max(r.created_ms for r in records)
            self._check_alerts()
            return

        hosts = self.peers.hosts(PEER_TIMEOUT_SECONDS)
        if not hosts:
            return
        host = min(hosts, key=lambda peer: peer.machine)
        if host.machine != self.sync_target:
            log(f"Conectado al host '{host.machine}' ({host.address}). Enviando historial...")
            self.sync_target = host.machine
            self.cursor = 0

        records = self._read_local()
        if not records:
            return
        try:
            for start in range(0, len(records), UPLOAD_CHUNK):
                _upload(host, self.settings, records[start : start + UPLOAD_CHUNK])
        except OSError as error:
            log(f"No pude enviar datos al host '{host.machine}': {error}")
            return
        self.cursor = max(r.created_ms for r in records)

    def _check_alerts(self) -> None:
        if self.store is None:
            return
        settings = load_settings()
        try:
            prices = load_prices(cache_dir() / "prices.json", plan=settings.plan)
        except OSError as error:
            log(f"No pude cargar precios para las alertas: {error}")
            return
        status = build_status(self.store, settings, self.peers, prices)
        now = datetime.now(timezone.utc)
        records = [record for _, record in self.store.load()]
        drift = drift_points(records, prices, settings, now)
        current = set(evaluate_alerts(status, settings.alert_percent, settings.calibrated_at, now, drift))
        for message in sorted(current - self.alerts):
            log(f"ALERTA: {message}")
            notify("Tokenizer", message)
        self.alerts = current


def _upload(host: Peer, settings: Settings, records: list[UsageRecord]) -> None:
    body = json.dumps(
        {"machine": settings.machine, "records": [record_to_dict(r) for r in records]}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host.address}:{host.port}/api/usage",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            TOKEN_HEADER: settings.token or "",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()
