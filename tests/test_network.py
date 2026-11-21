import json
from datetime import datetime, timezone
from pathlib import Path

from tokenizer.alerts import evaluate_alerts
from tokenizer.config import Settings
from tokenizer.host_store import HostStore, record_from_dict, record_to_dict
from tokenizer.opencode_db import UsageRecord
from tokenizer.peers import PeerTable, decode_heartbeat, encode_heartbeat, should_yield, token_fingerprint
from tokenizer.pricing import ModelPrice
from tokenizer.server import build_status, render_panel

FP = token_fingerprint("secreto-de-prueba")
PRICES = {"model-a": ModelPrice(input=0, output=1.0, cache_read=0, cache_write=0, monthly_limit=10.0)}


def ms(*args: int) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


def record(message_id: str, created_ms: int, output: int) -> UsageRecord:
    return UsageRecord(message_id, "opencode-go", "model-a", created_ms, 0, output, 0, 0)


def settings(machine: str = "PC-A") -> Settings:
    return Settings(
        machine=machine,
        token="secreto-de-prueba",
        plan="go",
        db=Path("unused.db"),
        renews_at=None,
        alert_percent=80.0,
        calibration_factor=1.0,
        calibrated_at=None,
    )


def test_heartbeat_roundtrip_accepts_same_network():
    raw = encode_heartbeat("PC-A", "host", 8765, FP)

    peer = decode_heartbeat(raw, "192.168.1.10", FP, now=1.0)

    assert peer is not None
    assert (peer.machine, peer.role, peer.address, peer.port) == ("PC-A", "host", "192.168.1.10", 8765)


def test_heartbeat_from_other_network_is_ignored():
    other = token_fingerprint("otro-token")
    raw = encode_heartbeat("PC-B", "host", 8765, other)

    assert decode_heartbeat(raw, "192.168.1.20", FP, now=1.0) is None


def test_heartbeat_garbage_is_ignored():
    assert decode_heartbeat(b"no es json", "192.168.1.20", FP, now=1.0) is None
    assert decode_heartbeat(json.dumps({"app": "otra"}).encode(), "1.2.3.4", FP, now=1.0) is None


def test_peer_table_expires_stale_peers():
    table = PeerTable()
    raw = encode_heartbeat("PC-A", "host", 8765, FP)
    table.update(decode_heartbeat(raw, "10.0.0.1", FP, now=100.0))

    assert len(table.hosts(timeout=30, now=120.0)) == 1
    assert table.hosts(timeout=30, now=140.0) == []


def test_conflicting_hosts_keep_the_lower_name():
    assert should_yield("PC-B", "PC-A") is True
    assert should_yield("PC-A", "PC-B") is False


def test_host_store_upsert_is_idempotent(tmp_path):
    store = HostStore(tmp_path / "host.db")
    records = [record("m1", ms(2026, 11, 2, 9), 1000), record("m2", ms(2026, 11, 2, 10), 2000)]

    store.upsert("PC-A", records)
    store.upsert("PC-A", records)
    store.upsert("PC-B", [record("m1", ms(2026, 11, 2, 9), 500)])

    rows = store.load()
    assert len(rows) == 3
    assert {machine for machine, _ in rows} == {"PC-A", "PC-B"}


def test_record_dict_roundtrip():
    original = record("m1", ms(2026, 11, 2, 9), 1234)

    assert record_from_dict(record_to_dict(original)) == original


def test_status_separates_machines_and_totals(tmp_path):
    store = HostStore(tmp_path / "host.db")
    store.upsert("PC-A", [record("a1", ms(2026, 11, 2, 9), 1_000_000)])
    store.upsert("PC-B", [record("b1", ms(2026, 11, 2, 10), 500_000)])
    now = datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)
    peers = PeerTable()

    status = build_status(store, settings("PC-A"), peers, PRICES, now=now)

    by_name = {machine["name"]: machine for machine in status["machines"]}
    assert by_name["PC-A"]["windows"][0]["used_percent"] == 10.0
    assert by_name["PC-B"]["windows"][0]["used_percent"] == 5.0
    assert by_name["PC-A"]["online"] is True
    assert by_name["PC-B"]["online"] is False
    assert status["total"]["windows"][0]["used_percent"] == 15.0


def test_alerts_trigger_on_threshold_and_calibration(tmp_path):
    store = HostStore(tmp_path / "host.db")
    store.upsert("PC-A", [record("a1", ms(2026, 11, 2, 9), 9_000_000)])
    now = datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)
    status = build_status(store, settings("PC-A"), PeerTable(), PRICES, now=now)

    messages = evaluate_alerts(status, alert_percent=80.0, calibrated_at=None, now=now)

    assert any("5 horas" in m or "de 5 horas" in m for m in messages)
    assert any("calibrar" in m for m in messages)


def test_panel_renders_machine_names_escaped(tmp_path):
    store = HostStore(tmp_path / "host.db")
    store.upsert("<PC>", [record("a1", ms(2026, 11, 2, 9), 1000)])
    now = datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)
    status = build_status(store, settings("PC-A"), PeerTable(), PRICES, now=now)

    html_page = render_panel(status)

    assert "&lt;PC&gt;" in html_page
    assert "<PC>" not in html_page
