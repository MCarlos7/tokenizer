from __future__ import annotations

import hmac
import html
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from tokenizer.config import PEER_TIMEOUT_SECONDS, Settings
from tokenizer.host_store import HostStore, record_from_dict
from tokenizer.opencode_db import UsageRecord
from tokenizer.pairing import redeem
from tokenizer.peers import PeerTable
from tokenizer.pricing import ModelPrice
from tokenizer.usage import WINDOW_LABELS, Window, compute_windows, utc

MAX_BODY_BYTES = 5 * 1024 * 1024
TOKEN_HEADER = "X-Tokenizer-Token"


def window_dict(window: Window) -> dict[str, Any]:
    return {
        "name": window.name,
        "used_percent": round(window.used_percent, 2),
        "limit_percent": window.limit_percent,
        "remaining_percent": round(window.remaining_percent, 2),
        "resets_at": window.resets_at.isoformat() if window.resets_at else None,
    }


def build_status(
    store: HostStore,
    settings: Settings,
    peers: PeerTable,
    prices: dict[str, ModelPrice],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = store.load()

    by_machine: dict[str, list[UsageRecord]] = {}
    for machine, record in rows:
        by_machine.setdefault(machine, []).append(record)

    online = {peer.machine for peer in peers.fresh(PEER_TIMEOUT_SECONDS)}
    online.add(settings.machine)
    names = sorted(set(by_machine) | online)

    options: dict[str, Any] = {
        "prices": prices,
        "now": now,
        "renews_at": settings.renews_at,
        "factor": settings.calibration_factor,
    }

    machines = []
    for name in names:
        records = by_machine.get(name, [])
        last = max((r.created_ms for r in records), default=None)
        machines.append(
            {
                "name": name,
                "online": name in online,
                "last_activity": utc(last).isoformat() if last is not None else None,
                "windows": [window_dict(w) for w in compute_windows(records, **options)],
            }
        )

    all_records = [record for _, record in rows]
    return {
        "generated_at": now.isoformat(),
        "plan": settings.plan,
        "alert_percent": settings.alert_percent,
        "machines": machines,
        "total": {"windows": [window_dict(w) for w in compute_windows(all_records, **options)]},
    }


def _window_row(window: dict[str, Any], alert_percent: float) -> str:
    used = window["used_percent"]
    width = min(used, 100.0)
    danger = " danger" if used >= alert_percent else ""
    label = WINDOW_LABELS.get(window["name"], window["name"])
    reset = window["resets_at"]
    reset_text = datetime.fromisoformat(reset).strftime("%d/%m %H:%M UTC") if reset else "sin uso activo"
    return (
        '<div class="row">'
        f'<span class="name">{html.escape(label)}</span>'
        f'<div class="bar{danger}"><span style="width:{width:.1f}%"></span></div>'
        f'<span class="value">{used:.1f} % de {window["limit_percent"]:.0f} %</span>'
        f'<span class="reset">reinicia: {html.escape(reset_text)}</span>'
        "</div>"
    )


def render_panel(status: dict[str, Any]) -> str:
    alert = status["alert_percent"]
    cards = []
    for machine in status["machines"]:
        state = "activo" if machine["online"] else "sin conexión"
        rows = "".join(_window_row(w, alert) for w in machine["windows"])
        cards.append(
            f'<section class="card"><h2>{html.escape(machine["name"])} <small>{state}</small></h2>{rows}</section>'
        )
    total_rows = "".join(_window_row(w, alert) for w in status["total"]["windows"])
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Tokenizer · OpenCode Go</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 24px; }}
h1 {{ font-size: 20px; }}
.grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }}
.card {{ background: #1c1c1c; border-radius: 10px; padding: 16px; }}
.card h2 {{ font-size: 16px; margin: 0 0 12px; }}
.card small {{ color: #888; font-weight: normal; }}
.row {{ display: grid; grid-template-columns: 90px 1fr; gap: 4px 10px; margin-bottom: 12px; }}
.bar {{ background: #333; border-radius: 6px; height: 12px; overflow: hidden; }}
.bar span {{ display: block; height: 100%; background: #3fb950; }}
.bar.danger span {{ background: #f85149; }}
.value, .reset {{ grid-column: 2; font-size: 13px; color: #bbb; }}
.name {{ font-size: 13px; }}
</style>
</head>
<body>
<h1>Consumo OpenCode Go · plan {html.escape(status["plan"])}</h1>
<div class="grid">
<section class="card"><h2>Total <small>todas las máquinas</small></h2>{total_rows}</section>
{"".join(cards)}
</div>
<p style="color:#666;font-size:12px">Generado {html.escape(status["generated_at"])}. Se actualiza cada 30 s. Estimación; compara con la consola.</p>
</body>
</html>
"""


class TokenizerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store: HostStore,
        peers: PeerTable,
        load_settings: Callable[[], Settings],
        load_prices: Callable[[], dict[str, ModelPrice]],
    ) -> None:
        super().__init__(address, TokenizerHandler)
        self.store = store
        self.peers = peers
        self.load_settings = load_settings
        self.load_prices = load_prices


class TokenizerHandler(BaseHTTPRequestHandler):
    server: TokenizerHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, "application/json", json.dumps(payload).encode("utf-8"))

    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html", "/api/status"):
            self._send(404, "text/plain; charset=utf-8", b"No encontrado")
            return
        try:
            prices = self.server.load_prices()
        except OSError:
            self._send_json(503, {"error": "Sin precios disponibles. Revisa la conexión a internet."})
            return
        status = build_status(self.server.store, self.server.load_settings(), self.server.peers, prices)
        if self.path == "/api/status":
            self._send_json(200, status)
        else:
            self._send(200, "text/html; charset=utf-8", render_panel(status).encode("utf-8"))

    def do_POST(self) -> None:
        if self.path == "/api/pair":
            self._handle_pair()
            return
        if self.path != "/api/usage":
            self._send_json(404, {"error": "No encontrado"})
            return
        settings = self.server.load_settings()
        provided = self.headers.get(TOKEN_HEADER, "")
        if not settings.token or not hmac.compare_digest(provided.encode("utf-8"), settings.token.encode("utf-8")):
            self._send_json(401, {"error": "Token no válido"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "Cuerpo vacío o demasiado grande"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            machine = str(payload["machine"])
            records = [record_from_dict(item) for item in payload["records"]]
        except (ValueError, KeyError, TypeError):
            self._send_json(400, {"error": "Formato de datos no válido"})
            return
        stored = self.server.store.upsert(machine, records)
        self._send_json(200, {"stored": stored})

    def _handle_pair(self) -> None:
        settings = self.server.load_settings()
        if not settings.token:
            self._send_json(503, {"error": "Este host no tiene red configurada"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "Cuerpo vacío o demasiado grande"})
            return
        try:
            code = str(json.loads(self.rfile.read(length).decode("utf-8"))["code"])
        except (ValueError, KeyError, TypeError):
            self._send_json(400, {"error": "Formato no válido"})
            return
        if not redeem(code):
            self._send_json(403, {"error": "Código no válido, caducado o ya usado"})
            return
        self._send_json(
            200,
            {
                "token": settings.token,
                "plan": settings.plan,
                "renews_at": settings.renews_at.isoformat() if settings.renews_at else None,
            },
        )
