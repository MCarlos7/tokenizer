import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tokenizer.config import Settings
from tokenizer.doctor import FAIL, OK, WARN, check_config, check_opencode_db


def settings(token: str | None, renews_at: datetime | None) -> Settings:
    return Settings(
        machine="PC-A",
        token=token,
        plan="go",
        db=Path("unused.db"),
        renews_at=renews_at,
        alert_percent=80.0,
        calibration_factor=1.0,
        calibrated_at=None,
    )


def statuses(checks) -> dict[str, str]:
    return {check.name: check.status for check in checks}


def test_config_without_token_fails_with_setup_hint():
    checks = check_config(settings(None, None))

    by_name = {check.name: check for check in checks}
    assert by_name["Token"].status == FAIL
    assert "tokenizer setup" in by_name["Token"].fix


def test_config_without_renewal_warns_about_natural_months():
    checks = check_config(settings("abc", None))

    assert statuses(checks)["Renovación de Go"] == WARN


def test_complete_config_is_ok():
    renews = datetime(2026, 12, 18, 22, 59, tzinfo=timezone.utc)

    checks = check_config(settings("abc", renews))

    assert all(check.status == OK for check in checks)


def test_missing_opencode_db_fails(tmp_path):
    check = check_opencode_db(tmp_path / "no-existe.db")

    assert check.status == FAIL


def test_opencode_db_counts_assistant_messages(tmp_path):
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE session_message (id TEXT, type TEXT)")
    conn.executemany("INSERT INTO session_message VALUES (?, ?)", [("1", "assistant"), ("2", "user"), ("3", "assistant")])
    conn.commit()
    conn.close()

    check = check_opencode_db(path)

    assert check.status == OK
    assert "2 respuestas" in check.detail
