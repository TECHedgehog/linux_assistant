"""Supervisor-owned tool registry, execution, and model/tool loop."""

import json
import sys

from config import MAX_TOOL_ROUNDS
from model import ollama_request
from policy import tool_risk
from tools import (
    disk_usage, list_directory, list_processes, open_app, read_file, restart_service,
    run_command, service_logs, service_status, start_service, stop_service, system_info,
)


TOOL_FUNCTIONS = {
    "system_info": system_info, "list_processes": list_processes,
    "disk_usage": disk_usage, "list_directory": list_directory, "read_file": read_file,
    "run_command": run_command, "open_app": open_app, "service_status": service_status,
    "service_logs": service_logs, "start_service": start_service,
    "stop_service": stop_service, "restart_service": restart_service,
}


def _tool(name, description, properties=None, required=None):
    function = {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties or {}}}
    if required:
        function["parameters"]["required"] = required
    return {"type": "function", "function": function}


TOOLS = [
    _tool("system_info", "Get basic information about the Linux system, CPU, RAM, root disk, kernel, and GPUs."),
    _tool("list_processes", "List the processes currently using the most RAM."),
    _tool("disk_usage", "Show filesystem disk usage for a path.", {"path": {"type": "string", "description": "Filesystem path. Defaults to /."}}),
    _tool("list_directory", "List files and directories at a given path.", {"path": {"type": "string", "description": "Directory path. Defaults to the current directory."}}),
    _tool("read_file", "Read a text file. Files larger than 256 KiB are rejected.", {"path": {"type": "string", "description": "Path to the text file."}}, ["path"]),
    _tool("run_command", "Run a non-root Linux command. Dangerous commands and shell composition are blocked.", {"command": {"type": "string", "description": "A single Linux command without shell pipes, redirects, chaining, sudo, or destructive operations."}}, ["command"]),
    _tool("open_app", "Launch an installed desktop application from the controlled application allowlist.", {"app": {"type": "string", "description": "Application name."}}, ["app"]),
    _tool("service_status", "Inspect the status of one systemd service without changing it.", {"service": {"type": "string", "description": "Systemd service name."}}, ["service"]),
    _tool("service_logs", "Read recent journal entries for one systemd service.", {"service": {"type": "string", "description": "Systemd service name."}, "lines": {"type": "integer", "description": "Number of recent lines, from 1 to 200."}}, ["service"]),
    _tool("start_service", "Start one systemd service after user confirmation.", {"service": {"type": "string", "description": "Systemd service name."}}, ["service"]),
    _tool("stop_service", "Stop one systemd service after user confirmation.", {"service": {"type": "string", "description": "Systemd service name."}}, ["service"]),
    _tool("restart_service", "Restart one systemd service after user confirmation.", {"service": {"type": "string", "description": "Systemd service name."}}, ["service"]),
]


def execute_tool(name, arguments, confirm_callback=None):
    """Execute one tool after supervisor permission checks."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"denied": True, "risk": "DENY", "error": f"Unknown tool: {name}"}
    try:
        arguments = arguments if isinstance(arguments, dict) else {}
        risk = tool_risk(name, arguments)
        if risk == "DENY":
            return {"denied": True, "risk": risk, "error": f"Supervisor denied tool request: {name}"}
        if risk == "CONFIRM" and (confirm_callback is None or not confirm_callback(name, arguments)):
            return {"denied": True, "risk": risk, "confirmed": False,
                    "error": f"User did not confirm tool request: {name}"}
        return function(**arguments)
    except Exception as exc:
        return {"error": f"Tool execution failed: {exc}"}


def ask(messages, confirm_callback=None, tool_output=None, model_request=None,
        execute_tool_fn=None):
    """Run the model/tool loop with supervisor-side safety limits."""
    called_tools = set()
    for _ in range(MAX_TOOL_ROUNDS):
        request = model_request or (lambda current: ollama_request(current, TOOLS))
        response = request(messages)
        message = response.get("message", {})
        tool_calls = message.get("tool_calls", [])
        if not tool_calls:
            answer = message.get("content", "").strip()
            return answer or "The model returned an empty response."
        messages.append(message)
        for tool_call in tool_calls:
            data = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            if not isinstance(data, dict):
                result = {"error": "Malformed tool call was not executed."}
                messages.append({"role": "tool", "content": json.dumps(result)})
                continue
            name, arguments = data.get("name"), data.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    result = {"error": "Malformed tool arguments was not executed."}
                    messages.append({"role": "tool", "content": json.dumps(result)})
                    continue
            arguments = arguments if isinstance(arguments, dict) else {}
            key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
            if name not in TOOL_FUNCTIONS:
                result = {"error": f"Tool '{name}' is not available."}
            elif key in called_tools:
                result = {"error": f"This exact tool call has already been executed: {name}({json.dumps(arguments, ensure_ascii=False)})"}
                messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})
                return "The assistant stopped a repeated tool-call loop."
            else:
                called_tools.add(key)
                if tool_output:
                    tool_output(name, arguments)
                executor = execute_tool_fn or execute_tool
                result = executor(name, arguments, confirm_callback=confirm_callback)
            messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)})
    return "The assistant reached its tool-call limit."
