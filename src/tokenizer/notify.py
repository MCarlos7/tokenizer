from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str) -> None:
    """Notificación de escritorio en Windows. En otros sistemas no hace nada."""
    if sys.platform != "win32":
        return
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$icon = New-Object System.Windows.Forms.NotifyIcon;"
        "$icon.Icon = [System.Drawing.SystemIcons]::Information;"
        "$icon.Visible = $true;"
        f"$icon.ShowBalloonTip(8000, '{safe_title}', '{safe_message}', "
        "[System.Windows.Forms.ToolTipIcon]::Warning);"
        "Start-Sleep -Seconds 9;"
        "$icon.Dispose()"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
