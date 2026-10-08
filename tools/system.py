import os
import platform
import shutil
import subprocess
import re
from pathlib import Path

from config import COMMAND_TIMEOUT, MAX_FILE_SIZE, MAX_OUTPUT
from policy import command_denial_reason, parse_command


SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9@_.:-]+$")
SAFE_READ_ROOTS = (Path.home().resolve(), Path("/tmp").resolve(), Path("/etc").resolve())
SENSITIVE_PARTS = {".ssh", ".gnupg", ".aws", ".kube", ".docker", ".pki", "keyrings"}
SENSITIVE_NAMES = {
    ".env", ".bash_history", ".zsh_history", "authorized_keys", "known_hosts",
    "shadow", "credentials", "token",
}


def _safe_read_path(path):
    """Resolve a path and reject sensitive files or paths outside safe roots."""
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return None, f"Could not resolve path: {exc}"

    if not any(root == resolved or root in resolved.parents for root in SAFE_READ_ROOTS):
        return None, "Path is outside approved read-only locations"
    if set(resolved.parts) & SENSITIVE_PARTS or resolved.name in SENSITIVE_NAMES:
        return None, "Path may contain sensitive credentials"
    if resolved.suffix in {".pem", ".key", ".p12", ".pfx"}:
        return None, "Credential and key files are blocked"
    return str(resolved), None


def system_info():
    """Return basic system information."""
    try:
        memory = shutil.disk_usage("/")
        root_disk = {
            "total_gb": round(memory.total / (1024**3), 1),
            "used_gb": round(memory.used / (1024**3), 1),
            "free_gb": round(memory.free / (1024**3), 1),
        }
    except Exception as exc:
        root_disk = {"error": str(exc)}

    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            meminfo = f.read()

        values = {}
        for line in meminfo.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1])

        memory_info = {
            "total_gb": round(values.get("MemTotal", 0) / 1024 / 1024, 1),
            "available_gb": round(values.get("MemAvailable", 0) / 1024 / 1024, 1),
        }
    except Exception as exc:
        memory_info = {"error": str(exc)}

    return {
        "hostname": platform.node(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu": _cpu_info(),
        "memory": memory_info,
        "root_disk": root_disk,
        "gpu": _gpu_info(),
    }


def _cpu_info():
    """Return the CPU model from /proc/cpuinfo."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()

        return platform.machine()

    except Exception as exc:
        return f"CPU detection failed: {exc}"


def _gpu_info():
    """Return GPU information using lspci."""
    try:
        result = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        gpus = []

        for line in result.stdout.splitlines():
            lower = line.lower()

            if "vga compatible controller" in lower:
                gpus.append(line)

            elif "3d controller" in lower:
                gpus.append(line)

            elif "display controller" in lower:
                gpus.append(line)

        return gpus
    except Exception as exc:
        return [f"GPU detection failed: {exc}"]


def list_processes():
    """Return the processes currently using the most memory."""
    processes = []

    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue

            pid = entry.name

            try:
                with open(
                    f"/proc/{pid}/status",
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as f:
                    status = f.read()

                name = "unknown"
                rss_kb = 0

                for line in status.splitlines():
                    if line.startswith("Name:"):
                        name = line.split(":", 1)[1].strip()

                    elif line.startswith("VmRSS:"):
                        parts = line.split()

                        if len(parts) >= 2:
                            rss_kb = int(parts[1])

                if rss_kb > 0:
                    processes.append(
                        {
                            "pid": pid,
                            "command": name,
                            "rss_mb": round(rss_kb / 1024, 1),
                        }
                    )

            except (
                FileNotFoundError,
                PermissionError,
                ProcessLookupError,
                ValueError,
            ):
                continue

        processes.sort(
            key=lambda process: process["rss_mb"],
            reverse=True,
        )

        return {
            "processes": processes[:20],
        }

    except Exception as exc:
        return {
            "error": str(exc),
        }


def disk_usage(path="/"):
    """Return filesystem usage for a path."""
    try:
        usage = shutil.disk_usage(path)

        return {
            "path": os.path.abspath(path),
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "used_percent": round((usage.used / usage.total) * 100, 1),
        }

    except Exception as exc:
        return {"error": str(exc)}


def list_directory(path="."):
    """List files and directories."""
    try:
        absolute_path, error = _safe_read_path(path)
        if error:
            return {"error": error}

        entries = []

        for entry in sorted(
            os.scandir(absolute_path),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        ):
            if entry.name in SENSITIVE_NAMES or entry.name in SENSITIVE_PARTS:
                continue
            try:
                entries.append(
                    {
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size_bytes": entry.stat().st_size if entry.is_file() else None,
                    }
                )
            except OSError:
                entries.append(
                    {
                        "name": entry.name,
                        "type": "unknown",
                        "size_bytes": None,
                    }
                )

        return {
            "path": absolute_path,
            "entries": entries,
        }

    except Exception as exc:
        return {"error": str(exc)}


def read_file(path):
    """Read a text file with a reasonable size limit."""
    try:
        absolute_path, error = _safe_read_path(path)
        if error:
            return {"error": error}

        if not os.path.isfile(absolute_path):
            return {"error": f"Not a regular file: {absolute_path}"}

        if os.path.getsize(absolute_path) > MAX_FILE_SIZE:
            return {
                "error": f"File is larger than {MAX_FILE_SIZE // 1024} KiB",
                "path": absolute_path,
            }

        with open(absolute_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return {
            "path": absolute_path,
            "content": content,
        }

    except Exception as exc:
        return {"error": str(exc)}


def run_command(command):
    """Run a restricted non-root command."""
    if not isinstance(command, str):
        return {"error": "Command must be a string"}

    command = command.strip()

    if not command:
        return {"error": "Empty command"}

    denial_reason = command_denial_reason(command)
    if denial_reason:
        return {
            "blocked": True,
            "reason": denial_reason,
        }

    args = parse_command(command)
    if not args:
        return {"error": "Could not parse command"}

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )

        return {
            "command": command,
            "return_code": result.returncode,
            "stdout": result.stdout[:MAX_OUTPUT],
            "stderr": result.stderr[:MAX_OUTPUT],
        }

    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "error": f"Command timed out after {COMMAND_TIMEOUT} seconds",
        }

    except Exception as exc:
        return {
            "command": command,
            "error": str(exc),
        }


def _validate_service_name(service):
    if not isinstance(service, str):
        return None, "Service name must be a string"

    service = service.strip()

    if not service:
        return None, "Service name cannot be empty"

    if len(service) > 256:
        return None, "Service name is too long"

    if service.startswith("-"):
        return None, "Invalid service name"

    if not SERVICE_NAME_PATTERN.fullmatch(service):
        return None, "Invalid service name"

    return service, None


def _systemctl(args, service):
    try:
        result = subprocess.run(
            ["systemctl", *args, service],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        return {
            "service": service,
            "return_code": result.returncode,
            "stdout": result.stdout[:12000],
            "stderr": result.stderr[:12000],
        }

    except subprocess.TimeoutExpired:
        return {
            "service": service,
            "error": "systemctl timed out after 10 seconds",
        }

    except FileNotFoundError:
        return {"service": service, "error": "systemctl is not available"}

    except Exception as exc:
        return {"service": service, "error": str(exc)}


def _journalctl(args, service):
    try:
        result = subprocess.run(
            ["journalctl", *args, service],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        return {
            "service": service,
            "return_code": result.returncode,
            "stdout": result.stdout[:12000],
            "stderr": result.stderr[:12000],
        }

    except subprocess.TimeoutExpired:
        return {
            "service": service,
            "error": "journalctl timed out after 10 seconds",
        }

    except FileNotFoundError:
        return {"service": service, "error": "journalctl is not available"}

    except Exception as exc:
        return {"service": service, "error": str(exc)}


def service_status(service):
    """Return status for one systemd service without changing it."""
    service, error = _validate_service_name(service)

    if error:
        return {"error": error}

    return _systemctl(["status", "--no-pager", "--full"], service)


def service_logs(service, lines=100):
    """Return recent journal entries for one systemd service."""
    service, error = _validate_service_name(service)

    if error:
        return {"error": error}

    if not isinstance(lines, int) or isinstance(lines, bool):
        return {"error": "lines must be an integer"}

    if lines < 1 or lines > 200:
        return {"error": "lines must be between 1 and 200"}

    return _journalctl(["--no-pager", "-n", str(lines), "-u"], service)


def _change_service(service, action):
    service, error = _validate_service_name(service)

    if error:
        return {"error": error}

    return _systemctl([action], service)


def start_service(service):
    """Start one systemd service."""
    return _change_service(service, "start")


def stop_service(service):
    """Stop one systemd service."""
    return _change_service(service, "stop")


def restart_service(service):
    """Restart one systemd service."""
    return _change_service(service, "restart")

def open_app(app):
    """Launch an installed desktop application by its desktop entry."""
    if not isinstance(app, str):
        return {"error": "Application name must be a string"}

    app = app.strip()

    if not app:
        return {"error": "Application name cannot be empty"}

    allowed_apps = {
        "thunar": "thunar",
        "dolphin": "dolphin",
        "steam": "steam",
        "codium": "codium",
        "vscode": "code",
        "firefox": "firefox",
        "kitty": "kitty",
        "alacritty": "alacritty",
    }

    key = app.lower()

    if key not in allowed_apps:
        return {
            "error": (
                f"Application '{app}' is not in the allowed application list."
            ),
            "allowed": sorted(allowed_apps.keys()),
        }

    command = allowed_apps[key]

    try:
        result = subprocess.run(
            ["sh", "-c", f"command -v {shlex.quote(command)}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode != 0:
            return {
                "error": f"Application '{app}' is not installed or not in PATH."
            }

        process = subprocess.Popen(
            [command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return {
            "success": True,
            "application": app,
            "command": command,
            "pid": process.pid,
        }

    except Exception as exc:
        return {
            "error": f"Failed to launch '{app}': {exc}",
        }
