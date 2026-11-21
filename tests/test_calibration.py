import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tokenizer.alerts import evaluate_alerts
from tokenizer.calibration import CalibrationError, apply_calibration, drift_points
from tokenizer.config import Settings, load_settings
from tokenizer.host_store import HostStore
from tokenizer.opencode_db import UsageRecord
from tokenizer.peers import PeerTable
from tokenizer.pricing import ModelPrice
from tokenizer.server import TokenizerHTTPServer, build_status

PRICES = {"model-a": ModelPrice(input=0, output=1.0, cache_read=0, cache_write=0, monthly_limit=10.0)}
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))


def record(message_id: str, moment: datetime, output: int) -> UsageRecord:
    return UsageRecord(message_id, "opencode-go", "model-a", int(moment.timestamp() * 1000), 0, output, 0, 0)


def test_apply_calibration_sets_factor_from_console_percent():
    records = [record("a", NOW - timedelta(hours=2), 1_000_000)]  # 10 % base

    base, factor = apply_calibration(records, PRICES, None, 20.0, now=NOW)

    assert round(base, 6) == 10.0
    assert round(factor, 6) == 2.0
    settings = load_settings()
    assert round(settings.calibration_factor, 6) == 2.0
    assert settings.calibrated_at == NOW
    assert round(settings.calibration_base, 6) == 10.0


def test_apply_calibration_rejects_invalid_values():
    records = [record("a", NOW - timedelta(hours=2), 1_000_000)]

    with pytest.raises(CalibrationError):
        apply_calibration(records, PRICES, None, 0, now=NOW)
    with pytest.raises(CalibrationError):
        apply_calibration(records, PRICES, None, 150, now=NOW)
    with pytest.raises(CalibrationError):
        apply_calibration([], PRICES, None, 10, now=NOW)


def test_drift_is_measured_since_last_calibration():
    settings = Settings(
        machine="PC-A",
        token="t",
        plan="go",
        db=Path("unused.db"),
        renews_at=None,
        alert_percent=80.0,
        calibration_factor=2.0,
        calibrated_at=NOW,
        calibration_base=10.0,
    )
    records = [record("a", NOW - timedelta(hours=2), 1_000_000), record("b", NOW - timedelta(hours=1), 500_000)]

    drift = drift_points(records, PRICES, settings, NOW)

    assert round(drift, 6) == 10.0  # (base 15 - calibrado 10) * factor 2


def test_drift_alert_appears_only_after_threshold():
    status = {"total": {"windows": []}}

    quiet = evaluate_alerts(status, 80.0, NOW, NOW, drift=5.0)
    loud = evaluate_alerts(status, 80.0, NOW, NOW, drift=12.0)

    assert quiet == []
    assert any("recalibrar" in message for message in loud)


def test_calibrate_form_from_host_updates_config(tmp_path):
    store = HostStore(tmp_path / "host.db")
    store.upsert("PC-A", [record("a", datetime.now(timezone.utc) - timedelta(hours=1), 1_000_000)])
    settings = load_settings()
    server = TokenizerHTTPServer(
        ("127.0.0.1", 0),
        store,
        PeerTable(),
        load_settings,
        lambda: PRICES,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = urllib.parse.urlencode({"console_percent": "5"}).encode()
        url = f"http://127.0.0.1:{server.server_address[1]}/api/calibrate"
        with urllib.request.urlopen(url, data=body, timeout=10) as response:
            page = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    assert "Calibración guardada" in page
    assert round(load_settings().calibration_factor, 6) == 0.5
    assert settings.calibration_factor == 1.0


def test_status_exposes_calibration(tmp_path):
    store = HostStore(tmp_path / "host.db")
    status = build_status(store, load_settings(), PeerTable(), PRICES, now=NOW)

    assert status["calibration"]["factor"] == 1.0
    assert status["calibration"]["calibrated_at"] is None
