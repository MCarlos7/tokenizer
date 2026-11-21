from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from tokenizer.config import PLANS, cache_dir, default_db_path, load_user_config, save_user_config, user_config_path
from tokenizer.opencode_db import read_usage
from tokenizer.pricing import load_prices
from tokenizer.usage import billing_period, compute_windows, usage_by_model


def _parse_datetime(value: str) -> datetime:
    """Acepta AAAA-MM-DD, AAAA-MM-DDTHH:MM o AAAA-MM-DDTHH:MM[Z]. Sin zona, asume UTC."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _format_reset(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "sin uso activo"
    delta = moment - now
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"en {hours} h {minutes:02d} min ({moment:%d/%m %H:%M} UTC)"


def cmd_config(args: argparse.Namespace) -> int:
    changes = {}
    if args.renews_at:
        changes["renews_at"] = args.renews_at.isoformat()
    if args.plan:
        changes["plan"] = args.plan
    if args.db:
        changes["db"] = str(args.db)
    if changes:
        save_user_config(changes)
        print(f"Guardado en {user_config_path()}")

    settings = load_user_config()
    if not settings:
        print("Sin configuración. Ejemplo: tokenizer config --renews-at 2026-12-18T23:00Z --plan go")
        return 0
    for key, value in settings.items():
        print(f"{key} = {value}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = load_user_config()
    now = datetime.now(timezone.utc)
    plan = args.plan or settings.get("plan", "go")
    db_path = args.db or (Path(settings["db"]) if "db" in settings else default_db_path())
    renews_at = _parse_datetime(settings["renews_at"]) if "renews_at" in settings else None

    prices = load_prices(cache_dir() / "prices.json", plan=plan)
    records = read_usage(db_path)
    windows = compute_windows(records, prices, now=now, renews_at=renews_at)
    period_start, period_end = billing_period(now, renews_at)

    print(f"Consumo estimado de OpenCode Go ({plan}) en esta máquina")
    print(f"Base de datos: {db_path}")
    if renews_at is None:
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

    by_model = usage_by_model(records, prices, since=period_start, until=period_end)
    print()
    if by_model:
        print("Por modelo (periodo actual, % del límite mensual del plan):")
        for model, percent in by_model.items():
            print(f"  {model:<28}{percent:>7.2f}%")
    else:
        print("Sin uso de modelos de pago en el periodo actual.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tokenizer", description="Consumo de OpenCode Go.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser("status", help="Muestra el consumo de esta máquina.")
    status.add_argument("--db", type=Path, default=None, help="Ruta a opencode.db (por defecto, la de OpenCode).")
    status.add_argument("--plan", choices=PLANS, default=None, help="Plan de Go contratado.")
    status.set_defaults(handler=cmd_status)

    config = subcommands.add_parser("config", help="Guarda o muestra tu configuración personal.")
    config.add_argument(
        "--renews-at",
        type=_parse_datetime,
        default=None,
        help="Próxima renovación de Go (AAAA-MM-DDTHH:MM, UTC). Define el periodo mensual.",
    )
    config.add_argument("--plan", choices=PLANS, default=None, help="Plan de Go contratado.")
    config.add_argument("--db", type=Path, default=None, help="Ruta a opencode.db.")
    config.set_defaults(handler=cmd_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.handler(args)
