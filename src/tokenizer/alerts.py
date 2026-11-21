from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from tokenizer.config import CALIBRATION_DRIFT_POINTS, CALIBRATION_MAX_AGE_DAYS


def evaluate_alerts(
    status: dict[str, Any],
    alert_percent: float,
    calibrated_at: datetime | None,
    now: datetime,
    drift: float = 0.0,
) -> list[str]:
    """Mensajes estables: no cambian con el porcentaje exacto, para no repetir notificaciones."""
    messages = []
    labels = {"5h": "de 5 horas", "weekly": "semanal", "monthly": "mensual"}
    for window in status["total"]["windows"]:
        if window["used_percent"] >= alert_percent:
            label = labels.get(window["name"], window["name"])
            messages.append(f"Límite {label} por encima del {alert_percent:.0f} %")
    if calibrated_at is None or now - calibrated_at > timedelta(days=CALIBRATION_MAX_AGE_DAYS):
        messages.append("Conviene calibrar con el porcentaje de la consola (panel o tokenizer calibrate)")
    elif drift >= CALIBRATION_DRIFT_POINTS:
        messages.append(f"Conviene recalibrar: el uso subió más de {CALIBRATION_DRIFT_POINTS:.0f} puntos desde la última calibración")
    return messages
