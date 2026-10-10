"""Private IPC helpers for Liam's optional layer-shell frontend."""

import json
import os
import socket
import tempfile
from pathlib import Path


def socket_path():
    """Return a per-user runtime socket path."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        runtime_dir = Path(runtime)
    else:
        runtime_dir = Path(tempfile.gettempdir()) / f"liam-{os.getuid()}"
        runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        runtime_dir.chmod(0o700)
    return runtime_dir / f"liam-{os.getuid()}.sock"


def send_command(path, command, timeout=0.5):
    """Send one command to a running frontend."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall((json.dumps({"command": command}) + "\n").encode())
