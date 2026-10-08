"""Supervisor-owned tool and command policy."""

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    default_risk: str


TOOL_POLICIES = {
    "system_info": ToolPolicy("ALLOW"),
    "list_processes": ToolPolicy("ALLOW"),
    "disk_usage": ToolPolicy("ALLOW"),
    "list_directory": ToolPolicy("ALLOW"),
    "read_file": ToolPolicy("ALLOW"),
    "preview_file_edit": ToolPolicy("ALLOW"),
    "apply_file_edit": ToolPolicy("CONFIRM"),
    "run_command": ToolPolicy("CONFIRM"),
    "open_app": ToolPolicy("ALLOW"),
    "service_status": ToolPolicy("ALLOW"),
    "service_logs": ToolPolicy("ALLOW"),
    "start_service": ToolPolicy("CONFIRM"),
    "stop_service": ToolPolicy("CONFIRM"),
    "restart_service": ToolPolicy("CONFIRM"),
}

READ_ONLY_COMMANDS = {
    "cat", "command", "df", "du", "free", "grep", "head", "id",
    "journalctl", "lspci", "ls", "ps", "pwd", "uname", "uptime", "w",
    "which", "whoami",
}

DENIED_COMMANDS = {
    "sudo", "su", "doas", "pkexec", "rm", "mkfs", "fdisk", "parted",
    "dd", "shutdown", "reboot", "poweroff", "chmod", "chown",
}

DENIED_SHELL_MARKERS = ("|", ">", ";", "`", "$ (", "$(")


def parse_command(command):
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    return args or None


def command_denial_reason(command):
    if not isinstance(command, str) or not command.strip():
        return "Command must be a non-empty string"
    if any(marker in command.lower() for marker in DENIED_SHELL_MARKERS):
        return "Shell composition is blocked"

    args = parse_command(command)
    if not args:
        return "Command could not be parsed"

    command_name = args[0].rsplit("/", 1)[-1].lower()
    if command_name in DENIED_COMMANDS:
        return f"Command is blocked: {command_name}"
    if command_name == "systemctl" and any(
        action in {"disable", "mask"} for action in args[1:]
    ):
        return "systemctl disable and mask are blocked"
    return None


def tool_risk(name, arguments):
    policy = TOOL_POLICIES.get(name)
    if policy is None:
        return "DENY"
    if name != "run_command":
        return policy.default_risk

    command = arguments.get("command", "") if isinstance(arguments, dict) else ""
    if command_denial_reason(command):
        return "DENY"
    args = parse_command(command)
    command_name = args[0].rsplit("/", 1)[-1].lower()
    return "ALLOW" if command_name in READ_ONLY_COMMANDS else policy.default_risk
