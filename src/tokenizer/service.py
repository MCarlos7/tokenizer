from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from tokenizer.config import cache_dir


def pid_file() -> Path:
    return cache_dir() / "daemon.pid"


def write_pid(pid: int | None = None) -> None:
    path = pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pid.tmp")
    temporary.write_text(str(pid or os.getpid()), encoding="ascii")
    temporary.replace(path)


def clear_pid(pid: int | None = None) -> None:
    path = pid_file()
    try:
        current = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    if pid is None or current == pid:
        path.unlink(missing_ok=True)


def read_pid() -> int | None:
    try:
        pid = int(pid_file().read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _is_tokenizer_process(pid: int) -> bool:
    if sys.platform == "win32":
        command = (
            f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
            "if ($p -and $p.CommandLine -match '(?i)(-m\\s+tokenizer\\s+run|tokenizer(?:\\.exe)?\\s+run)') "
            "{ exit 0 } else { exit 1 }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "tokenizer" in result.stdout.lower() and "run" in result.stdout.lower()


def _legacy_daemon_pids() -> list[int]:
    """Find daemons started before PID-file support, for stop/update compatibility."""
    pattern = r"(?i)(-m\s+tokenizer\s+run|tokenizer(?:\.exe)?\s+run)"
    if sys.platform == "win32":
        command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.ProcessId -ne $PID -and $_.CommandLine -match '{pattern}' }} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.splitlines():
            try:
                pids.append(int(line.strip()))
            except ValueError:
                continue
        return pids
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and "tokenizer" in parts[1].lower() and "run" in parts[1].lower():
            try:
                pids.append(int(parts[0]))
            except ValueError:
                continue
    return pids


def active_pid() -> int | None:
    pid = read_pid()
    if pid is None:
        return next(iter(_legacy_daemon_pids()), None)
    if _is_tokenizer_process(pid):
        return pid
    clear_pid(pid)
    return next(iter(_legacy_daemon_pids()), None)


def stop_daemon(timeout: float = 8.0) -> int | None:
    """Stops only the process identified by our PID file and verified command line."""
    pid = active_pid()
    if pid is None:
        return None
    if sys.platform == "win32":
        command = (
            f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
            "if ($p -and $p.CommandLine -match '(?i)(-m\\s+tokenizer\\s+run|tokenizer(?:\\.exe)?\\s+run)') "
            f"{{ Stop-Process -Id {pid} -Force -ErrorAction Stop }} else {{ exit 1 }}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return None
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            clear_pid(pid)
            return pid

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _is_tokenizer_process(pid):
        time.sleep(0.1)
    if _is_tokenizer_process(pid):
        return None
    clear_pid(pid)
    return pid
