from datetime import datetime, timedelta, timezone

import pytest

from tokenizer import pairing
from tokenizer.peers import decode_heartbeat, encode_heartbeat, token_fingerprint

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_new_token_is_long_and_unique():
    first, second = pairing.new_token(), pairing.new_token()

    assert len(first) >= 40
    assert first != second


def test_code_redeems_once():
    code = pairing.open_pairing(now=NOW)

    assert pairing.pairing_open(now=NOW)
    assert pairing.redeem(code, now=NOW) is True
    assert pairing.redeem(code, now=NOW) is False
    assert not pairing.pairing_open(now=NOW)


def test_code_is_case_and_dash_insensitive():
    code = pairing.open_pairing(now=NOW)

    assert pairing.redeem(code.replace("-", "").lower(), now=NOW) is True


def test_expired_code_is_rejected():
    code = pairing.open_pairing(now=NOW)
    later = NOW + timedelta(minutes=11)

    assert pairing.redeem(code, now=later) is False


def test_code_is_blocked_after_too_many_wrong_attempts():
    code = pairing.open_pairing(now=NOW)
    wrong = "ZZZZ-ZZZZ" if code != "ZZZZ-ZZZZ" else "AAAA-AAAA"

    for _ in range(pairing.MAX_ATTEMPTS):
        assert pairing.redeem(wrong, now=NOW) is False

    assert pairing.redeem(code, now=NOW) is False


def test_code_is_stored_only_as_digest():
    code = pairing.open_pairing(now=NOW)
    stored = (pairing._path()).read_text(encoding="utf-8")

    assert code.replace("-", "") not in stored


def test_heartbeat_without_token_only_accepts_pairing_hosts():
    fingerprint = token_fingerprint("secreto")
    open_host = encode_heartbeat("PC-A", "host", 8765, fingerprint, pairing=True)
    closed_host = encode_heartbeat("PC-A", "host", 8765, fingerprint, pairing=False)
    client = encode_heartbeat("PC-B", "client", 8765, fingerprint, pairing=True)

    assert decode_heartbeat(open_host, "10.0.0.1", None, now=1.0).pairing is True
    assert decode_heartbeat(closed_host, "10.0.0.1", None, now=1.0) is None
    assert decode_heartbeat(client, "10.0.0.2", None, now=1.0) is None
