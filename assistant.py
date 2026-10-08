import json
import socket
import sys
import time
import urllib.error
import urllib.request

from config import (
    MAX_TOOL_ROUNDS,
    MODEL,
    OLLAMA_RETRIES,
    OLLAMA_RETRY_BACKOFF,
    OLLAMA_TIMEOUT,
    OLLAMA_URL,
)
from policy import tool_risk as supervisor_tool_risk

from tools import (
    disk_usage,
    list_directory,
    list_processes,
    read_file,
    run_command,
    system_info,
    open_app,
    service_status,
    service_logs,
    start_service,
    stop_service,
    restart_service,
)


SYSTEM_PROMPT = """You are a local Linux desktop assistant.

You operate on a CachyOS + Hyprland + Caelestia desktop.

Your job is to understand the user's request, inspect the system when necessary, and perform safe actions through the provided tools.

Tool rules:
- Use the most specific available tool for the user's request.
- Do not use run_command when a dedicated tool already provides the required information.
- After receiving a tool result, answer using that result.
- Never ignore, replace, or contradict information returned by a tool.
- Never invent tool output.
- Do not call additional tools unless the previous result is insufficient.
- For process questions, use list_processes().
- For CPU, GPU, RAM, disk, and kernel questions, use system_info().
- For directory listings, use list_directory().
- For reading files, use read_file().
- For service status, use service_status().
- For service logs, use service_logs().
- For service changes, use the dedicated service tool and let the supervisor request confirmation.
- Use run_command only when no dedicated tool can perform the requested action.

Safety rules:
- Never claim an action was performed unless a tool actually performed it.
- Prefer inspection before modification.
- Never request sudo.
- Never attempt destructive filesystem, partition, bootloader, or security operations.
- Never attempt to bypass a blocked tool.
- The supervisor decides whether a tool is allowed, requires confirmation, or is denied.
- Never claim confirmation or permission that the supervisor did not provide.
- Keep responses concise and factual.
"""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Get basic information about the Linux system, CPU, RAM, root disk, kernel, and GPUs.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "List the processes currently using the most RAM.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disk_usage",
            "description": "Show filesystem disk usage for a path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Filesystem path. Defaults to /.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path. Defaults to the current directory.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file. Files larger than 256 KiB are rejected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the text file.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a non-root Linux command. Dangerous commands and shell composition are blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "A single Linux command without shell pipes, redirects, chaining, sudo, or destructive operations.",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Launch an installed desktop application from the controlled application allowlist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "description": "Application name, such as thunar, steam, firefox, codium, kitty, or alacritty.",
                    }
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "service_status",
            "description": "Inspect the status of one systemd service without changing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Systemd service name, such as ollama.service.",
                    }
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "service_logs",
            "description": "Read recent journal entries for one systemd service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Systemd service name, such as ollama.service.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of recent lines to return, from 1 to 200.",
                    },
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_service",
            "description": "Start one systemd service after user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Systemd service name.",
                    }
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_service",
            "description": "Stop one systemd service after user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Systemd service name.",
                    }
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_service",
            "description": "Restart one systemd service after user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Systemd service name.",
                    }
                },
                "required": ["service"],
            },
        },
    },
]


TOOL_FUNCTIONS = {
    "system_info": system_info,
    "list_processes": list_processes,
    "disk_usage": disk_usage,
    "list_directory": list_directory,
    "read_file": read_file,
    "run_command": run_command,
    "open_app": open_app,
    "service_status": service_status,
    "service_logs": service_logs,
    "start_service": start_service,
    "stop_service": stop_service,
    "restart_service": restart_service,
}


def tool_risk(name, arguments):
    """Return supervisor-owned risk decision for a tool request."""
    return supervisor_tool_risk(name, arguments)


def confirm_tool_call(name, arguments):
    """Ask the local user to approve a confirmation-required tool call."""
    print(
        "\n[confirmation required] "
        f"Allow {name}({json.dumps(arguments, ensure_ascii=False)})? [y/N] ",
        end="",
        file=sys.stderr,
        flush=True,
    )

    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False

    return answer in {"y", "yes"}


def ollama_request(messages):
    """Send a non-streaming chat request to Ollama."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
        },
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(OLLAMA_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
                status = getattr(response, "status", None)
                if not isinstance(status, int):
                    status = response.getcode()
                if not isinstance(status, int) or not 200 <= status < 300:
                    raise RuntimeError(f"Ollama returned HTTP status {status}")

                body = response.read().decode("utf-8")

            parsed = json.loads(body)
            return validate_ollama_response(parsed)

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace").strip()
            detail = f": {body}" if body else ""
            raise RuntimeError(f"Ollama HTTP {exc.code}{detail}") from exc

        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt < OLLAMA_RETRIES:
                time.sleep(OLLAMA_RETRY_BACKOFF * (2**attempt))
                continue

            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Could not connect to Ollama: {reason}") from exc

        except UnicodeDecodeError as exc:
            raise RuntimeError("Ollama returned a response that was not valid UTF-8") from exc

        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON") from exc


def validate_ollama_response(response):
    """Validate the subset of Ollama's response used by the assistant."""
    if not isinstance(response, dict):
        raise RuntimeError("Ollama returned an invalid response: expected an object")

    message = response.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama returned an invalid response: missing message")
    if not isinstance(message.get("content"), str):
        raise RuntimeError("Ollama returned an invalid message: content must be text")

    tool_calls = message.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        raise RuntimeError("Ollama returned an invalid message: tool_calls must be a list")

    return response


def execute_tool(name, arguments, confirm_callback=None):
    """Execute one tool call after supervisor permission checks."""
    function = TOOL_FUNCTIONS.get(name)

    if function is None:
        return {
            "denied": True,
            "risk": "DENY",
            "error": f"Unknown tool: {name}",
        }

    try:
        if not isinstance(arguments, dict):
            arguments = {}

        risk = tool_risk(name, arguments)

        if risk == "DENY":
            return {
                "denied": True,
                "risk": risk,
                "error": f"Supervisor denied tool request: {name}",
            }

        if risk == "CONFIRM":
            if confirm_callback is None or not confirm_callback(name, arguments):
                return {
                    "denied": True,
                    "risk": risk,
                    "confirmed": False,
                    "error": f"User did not confirm tool request: {name}",
                }

        return function(**arguments)

    except Exception as exc:
        return {
            "error": f"Tool execution failed: {exc}",
        }


def ask(messages):
    """Run the model/tool loop with supervisor-side safety limits."""
    called_tools = set()

    for _ in range(MAX_TOOL_ROUNDS):
        response = ollama_request(messages)
        message = response.get("message", {})

        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            answer = message.get("content", "").strip()

            if answer:
                return answer

            return "The model returned an empty response."

        messages.append(message)

        for tool_call in tool_calls:
            if not isinstance(tool_call, dict) or not isinstance(
                tool_call.get("function"), dict
            ):
                result = {"error": "Malformed Ollama tool call: function must be an object."}
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}
                )
                continue

            function_data = tool_call["function"]
            name = function_data.get("name")
            arguments = function_data.get("arguments")

            if not isinstance(name, str) or not name:
                result = {"error": "Malformed Ollama tool call: tool name is required."}
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}
                )
                continue

            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = None

            if not isinstance(arguments, dict):
                result = {
                    "error": f"Malformed arguments for tool '{name}'; tool was not executed."
                }
                messages.append(
                    {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}
                )
                continue

            if name not in TOOL_FUNCTIONS:
                result = {
                    "error": f"Tool '{name}' is not available."
                }

                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            tool_key = (
                name,
                json.dumps(
                    arguments,
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            )

            if tool_key in called_tools:
                result = {
                    "error": (
                        f"This exact tool call has already been executed: "
                        f"{name}({json.dumps(arguments, ensure_ascii=False)})"
                    )
                }
            else:
                called_tools.add(tool_key)

                print(
                    f"\n[tool] {name}({json.dumps(arguments, ensure_ascii=False)})",
                    file=sys.stderr,
                )

                result = execute_tool(
                    name,
                    arguments,
                    confirm_callback=confirm_tool_call,
                )

            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        result,
                        ensure_ascii=False,
                    ),
                }
            )

    return "The assistant reached its tool-call limit."

def main():
    print(f"Linux Assistant — {MODEL}")
    print("Type 'exit' or 'quit' to leave.")
    print()

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    while True:
        try:
            user_input = input("You> ").strip()

        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            break

        messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        try:
            answer = ask(messages)

            messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                }
            )

            print(f"\nAssistant> {answer}\n")

        except KeyboardInterrupt:
            print("\nInterrupted.\n")

        except Exception as exc:
            print(f"\nError: {exc}\n", file=sys.stderr)

            if messages and messages[-1].get("role") == "user":
                messages.pop()


if __name__ == "__main__":
    main()
