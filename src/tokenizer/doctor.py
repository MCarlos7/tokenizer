from __future__ import annotations

import socket
import sqlite3
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from tokenizer.config import DEFAULT_PORT, DISCOVERY_PORT, FIREWALL_RULES, USER_AGENT, Settings, cache_dir
from tokenizer.pricing import load_prices

OK, WARN, FAIL = "OK", "AVISO", "FALLO"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def check_config(settings: Settings) -> list[Check]:
    checks = []
    if settings.token:
        checks.append(Check("Token", OK, "configurado"))
    else:
        checks.append(Check("Token", FAIL, "no configurado", "tokenizer setup --new   (o --join para unirte a una red)"))
    checks.append(Check("Nombre del equipo", OK, settings.machine))
    if settings.renews_at:
        checks.append(Check("Renovación de Go", OK, f"{settings.renews_at:%d/%m/%Y %H:%M} UTC"))
    else:
        checks.append(
            Check(
                "Renovación de Go",
                WARN,
                "sin fecha; el mensual usa meses naturales",
                "tokenizer config --renews-at AAAA-MM-DDTHH:MM",
            )
        )
    return checks


def check_opencode_db(path: Path) -> Check:
    name = "Historial de OpenCode"
    if not path.exists():
        return Check(name, FAIL, f"no existe {path}", "tokenizer config --db RUTA_A_opencode.db")
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            count = conn.execute("SELECT COUNT(*) FROM session_message WHERE type = 'assistant'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as error:
        return Check(name, FAIL, f"no se puede leer: {error}", "revisa la ruta o cierra OpenCode si bloquea el archivo")
    return Check(name, OK, f"{count} respuestas registradas")


def check_prices(settings: Settings) -> Check:
    try:
        prices = load_prices(cache_dir() / "prices.json", plan=settings.plan)
    except OSError as error:
        return Check("Precios de Go", FAIL, f"no disponibles: {error}", "revisa la conexión a internet")
    priced = sum(1 for price in prices.values() if price.monthly_limit)
    return Check("Precios de Go", OK, f"{priced} modelos con límite para el plan {settings.plan}")


def _port_free(kind: int, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, kind)
    try:
        sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _tokenizer_responds() -> bool:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{DEFAULT_PORT}/api/status", headers={"User-Agent": USER_AGENT}),
            timeout=2,
        ) as response:
            return response.status == 200
    except OSError:
        return False


def check_ports() -> list[Check]:
    checks = []
    if _port_free(socket.SOCK_STREAM, DEFAULT_PORT):
        checks.append(Check(f"Puerto {DEFAULT_PORT} (panel)", OK, "libre"))
    elif _tokenizer_responds():
        checks.append(Check(f"Puerto {DEFAULT_PORT} (panel)", OK, "en uso por Tokenizer (este equipo es host)"))
    else:
        checks.append(
            Check(
                f"Puerto {DEFAULT_PORT} (panel)",
                FAIL,
                "ocupado por otro programa",
                "cierra el programa que usa el puerto 8765; el puerto no se puede cambiar todavía",
            )
        )

    if _port_free(socket.SOCK_DGRAM, DISCOVERY_PORT):
        checks.append(Check(f"Puerto {DISCOVERY_PORT} (descubrimiento)", OK, "libre"))
    else:
        checks.append(
            Check(
                f"Puerto {DISCOVERY_PORT} (descubrimiento)",
                WARN,
                "ocupado; probablemente Tokenizer ya está en marcha",
                "tokenizer status o revisa el Administrador de tareas (python -m tokenizer)",
            )
        )
    return checks


def check_firewall() -> list[Check]:
    if sys.platform != "win32":
        return [Check("Firewall", OK, "no aplica en este sistema")]
    checks = []
    for rule_name, (protocol, port) in FIREWALL_RULES.items():
        try:
            output = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            checks.append(Check(f"Firewall {protocol} {port}", WARN, f"no se pudo consultar: {error}"))
            continue
        if rule_name in output and str(port) in output:
            checks.append(Check(f"Firewall {protocol} {port}", OK, "regla presente"))
        else:
            checks.append(
                Check(
                    f"Firewall {protocol} {port}",
                    WARN,
                    "regla no encontrada; otros equipos no podrán conectarse",
                    "ejecuta scripts\\install.ps1 como administrador",
                )
            )
    return checks


def check_plugin() -> Check:
    candidates = [
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path.home() / ".config" / "opencode" / "opencode.jsonc",
    ]
    for path in candidates:
        if path.exists() and "tokenizer" in path.read_text(encoding="utf-8", errors="replace"):
            return Check("Plugin de OpenCode", OK, f"referenciado en {path}")
    return Check(
        "Plugin de OpenCode",
        WARN,
        "no está en la configuración global de OpenCode (el plugin aún no está probado)",
        "añade la ruta de opencode-plugin en \"plugins\" de ~/.config/opencode/opencode.json",
    )


def check_service() -> Check:
    if _tokenizer_responds():
        return Check("Servicio local", OK, "responde en el puerto 8765")
    return Check(
        "Servicio local",
        WARN,
        "no responde en el puerto 8765 (no es host, o no está en marcha)",
        "tokenizer start",
    )


def run_checks(settings: Settings, db_path: Path) -> list[Check]:
    checks = check_config(settings)
    checks.append(check_opencode_db(db_path))
    checks.append(check_prices(settings))
    checks.extend(check_ports())
    checks.append(check_service())
    checks.extend(check_firewall())
    checks.append(check_plugin())
    return checks
