from tokenizer import service


def test_pid_file_roundtrip_and_owner_only_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    service.write_pid(12345)

    assert service.read_pid() == 12345
    service.clear_pid(99999)
    assert service.read_pid() == 12345
    service.clear_pid(12345)
    assert service.read_pid() is None


def test_active_pid_uses_verified_pid_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service.write_pid(12345)
    monkeypatch.setattr(service, "_is_tokenizer_process", lambda pid: pid == 12345)

    assert service.active_pid() == 12345


def test_stale_pid_file_is_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service.write_pid(12345)
    monkeypatch.setattr(service, "_is_tokenizer_process", lambda _: False)
    monkeypatch.setattr(service, "_legacy_daemon_pids", lambda: [])

    assert service.active_pid() is None
    assert service.read_pid() is None


def test_cli_parser_exposes_stop_and_update():
    from tokenizer.cli import build_parser, cmd_stop, cmd_update

    parser = build_parser()

    assert parser.parse_args(["stop"]).handler is cmd_stop
    assert parser.parse_args(["update"]).handler is cmd_update


def test_update_refuses_dirty_worktree_before_fetching(monkeypatch, capsys):
    import subprocess

    from tokenizer import cli

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, "D:/tokenizer\n", "")
        if "status" in command:
            return subprocess.CompletedProcess(command, 0, " M src/tokenizer/cli.py\n", "")
        raise AssertionError("update must refuse before network or reset commands")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.cmd_update(None) == 1
    assert "cambios locales" in capsys.readouterr().out
    assert len(calls) == 2
