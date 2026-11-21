from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tokenizer.config import (
    DEFAULT_PORT,
    PLANS,
    cache_dir,
    host_db_path,
    load_settings,
    load_user_config,
    parse_datetime,
    save_user_config,
    user_config_path,
)
from tokenizer.daemon import Daemon
from tokenizer.host_store import HostStore
from tokenizer.opencode_db import read_usage
from tokenizer.pricing import load_prices
from tokenizer.usage import billing_period, compute_windows, record_percent, usage_by_model, utc


def _format_reset(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "sin uso activo"
    delta = moment - now
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"en {hours} h {minutes:02d} min ({moment:%d/%m %H:%M} UTC)"


def _require_token() -> bool:
    if load_settings().token:
        return True
    print("Falta el token compartido. Configúralo igual en todos los equipos:")
    print("  tokenizer config --token TU_TOKEN")
    return False


def cmd_run(args: argparse.Namespace) -> int:
    if not _require_token():
        return 1
    try:
        Daemon(load_settings()).run()
    except OSError as error:
        print(f"No se pudo iniciar Tokenizer: {error}")
        print("Puede que ya esté activo en esta máquina (puerto de descubrimiento ocupado).")
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    if not _require_token():
        return 1
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "daemon.log"
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with log_path.open("a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "tokenizer", "run"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    print(f"Tokenizer iniciado en segundo plano. Registro: {log_path}")
    print(f"Panel (en el host): http://localhost:{DEFAULT_PORT}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    now = datetime.now(timezone.utc)
    plan = args.plan or settings.plan
    db_path = args.db or settings.db
    factor = settings.calibration_factor

    prices = load_prices(cache_dir() / "prices.json", plan=plan)
    records = read_usage(db_path)
    windows = compute_windows(records, prices, now=now, renews_at=settings.renews_at, factor=factor)
    period_start, period_end = billing_period(now, settings.renews_at)

    print(f"Consumo estimado de OpenCode Go ({plan}) en esta máquina")
    print(f"Base de datos: {db_path}")
    if settings.renews_at is None:
        print("Aviso: sin fecha de renovación; el mensual usa meses naturales. Configúrala con 'tokenizer config --renews-at'.")
    print()
    print(f"{'Ventana':<10}{'Usado':>10}{'Límite':>10}{'Disponible':>12}  Reinicio")
    for window in windows:
        print(
            f"{window.name:<10}"
            f"{window.used_percent:>9.1f}%"
            f"{window.limit_percent:>9.0f}%"
            f"{window.remaining_percent:>11.1f}%"
            f"  {_format_reset(window.resets_at, now)}"
        )

    by_model = usage_by_model(records, prices, since=period_start, until=period_end, factor=factor)
    print()
    if by_model:
        print("Por modelo (periodo actual, % del límite mensual del plan):")
        for model, percent in by_model.items():
            print(f"  {model:<28}{percent:>7.2f}%")
    else:
        print("Sin uso de modelos de pago en el periodo actual.")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    changes: dict[str, object] = {}
    if args.renews_at:
        changes["renews_at"] = args.renews_at.isoformat()
    if args.plan:
        changes["plan"] = args.plan
    if args.db:
        changes["db"] = str(args.db)
    if args.token:
        changes["token"] = args.token
    if args.machine:
        changes["machine"] = args.machine
    if args.alert_percent is not None:
        changes["alert_percent"] = args.alert_percent
    if changes:
        save_user_config(changes)
        print(f"Guardado en {user_config_path()}")

    settings = load_user_config()
    if not settings:
        print("Sin configuración. Ejemplo: tokenizer config --token TU_TOKEN --renews-at 2026-12-18T23:00Z")
        return 0
    for key, value in settings.items():
        shown = "********" if key == "token" else value
        print(f"{key} = {shown}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = HostStore(host_db_path())
    prices = load_prices(cache_dir() / "prices.json", plan=settings.plan)
    records = [record for _, record in store.load()]

    now = datetime.now(timezone.utc)
    start, end = billing_period(now, settings.renews_at)
    estimate = sum(record_percent(r, prices) for r in records if start <= utc(r.created_ms) < end)
    if estimate <= 0:
        print("No hay uso estimado en el periodo actual; calibra cuando haya uso.")
        return 1

    factor = args.console_percent / estimate
    save_user_config({"calibration_factor": round(factor, 4), "calibrated_at": now.isoformat()})
    print(f"Estimación base: {estimate:.2f} %. Consola: {args.console_percent:.2f} %. Factor: {factor:.3f}")
    print("Ejecútalo en el host, que tiene el historial de todas las máquinas.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tokenizer", description="Consumo de OpenCode Go.")
    parser.set_defaults(handler=cmd_run)
    subcommands = parser.add_subparsers(dest="command")

    run = subcommands.add_parser("run", help="Ejecuta Tokenizer en primer plano (predeterminado).")
    run.set_defaults(handler=cmd_run)

    start = subcommands.add_parser("start", help="Ejecuta Tokenizer en segundo plano.")
    start.set_defaults(handler=cmd_start)

    status = subcommands.add_parser("status", help="Muestra el consumo de esta máquina.")
    status.add_argument("--db", type=Path, default=None, help="Ruta a opencode.db.")
    status.add_argument("--plan", choices=PLANS, default=None, help="Plan de Go contratado.")
    status.set_defaults(handler=cmd_status)

    config = subcommands.add_parser("config", help="Guarda o muestra tu configuración personal.")
    config.add_argument("--token", default=None, help="Token compartido de la red (igual en todos los equipos).")
    config.add_argument("--machine", default=None, help="Nombre de este equipo (único en la red).")
    config.add_argument("--renews-at", type=parse_datetime, default=None, help="Próxima renovación de Go (UTC).")
    config.add_argument("--plan", choices=PLANS, default=None, help="Plan de Go contratado.")
    config.add_argument("--db", type=Path, default=None, help="Ruta a opencode.db.")
    config.add_argument("--alert-percent", type=float, default=None, help="Umbral de alerta (%%).")
    config.set_defaults(handler=cmd_config)

    calibrate = subcommands.add_parser("calibrate", help="Ajusta la estimación con el porcentaje de la consola.")
    calibrate.add_argument("--console-percent", type=float, required=True, help="Porcentaje mensual que muestra la consola.")
    calibrate.set_defaults(handler=cmd_calibrate)
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.handler(args)
