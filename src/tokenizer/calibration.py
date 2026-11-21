from __future__ import annotations

from datetime import datetime, timezone

from tokenizer.config import Settings, save_user_config
from tokenizer.opencode_db import UsageRecord
from tokenizer.pricing import ModelPrice
from tokenizer.usage import billing_period, record_percent, utc


class CalibrationError(ValueError):
    pass


def base_monthly_percent(
    records: list[UsageRecord],
    prices: dict[str, ModelPrice],
    renews_at: datetime | None,
    now: datetime,
) -> float:
    """Estimación del periodo actual sin factor de calibración."""
    start, end = billing_period(now, renews_at)
    return sum(record_percent(r, prices) for r in records if start <= utc(r.created_ms) < end)


def apply_calibration(
    records: list[UsageRecord],
    prices: dict[str, ModelPrice],
    renews_at: datetime | None,
    console_percent: float,
    now: datetime | None = None,
) -> tuple[float, float]:
    """Guarda el factor que iguala la estimación con el porcentaje de la consola. Devuelve (base, factor)."""
    now = now or datetime.now(timezone.utc)
    if not 0 < console_percent <= 100:
        raise CalibrationError("El porcentaje debe estar entre 0 y 100.")
    base = base_monthly_percent(records, prices, renews_at, now)
    if base <= 0:
        raise CalibrationError("No hay uso estimado en el periodo actual; calibra cuando haya uso.")
    factor = console_percent / base
    save_user_config(
        {
            "calibration_factor": round(factor, 4),
            "calibrated_at": now.isoformat(),
            "calibration_base": round(base, 6),
        }
    )
    return base, factor


def drift_points(
    records: list[UsageRecord],
    prices: dict[str, ModelPrice],
    settings: Settings,
    now: datetime,
) -> float:
    """Cuántos puntos porcentuales ha crecido el uso desde la última calibración, en escala de consola."""
    if settings.calibration_base is None:
        return 0.0
    base = base_monthly_percent(records, prices, settings.renews_at, now)
    return (base - settings.calibration_base) * settings.calibration_factor
