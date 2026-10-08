import json
import sys
import urllib.error
import urllib.request

from config import (
    COMMAND_TIMEOUT,
    MAX_OUTPUT,
    MAX_TOOL_ROUNDS,
    MODEL,
    OLLAMA_URL,
)

from tools import (
    disk_usage,
    list_directory,
    list_processes,
    read_file,
    run_command,
    system_info,
    open_app,
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
- Use run_command only when no dedicated tool can perform the requested action.

Safety rules:
- Never claim an action was performed unless a tool actually performed it.
- Prefer inspection before modification.
- Never request sudo.
- Never attempt destructive filesystem, partition, bootloader, or security operations.
- Never attempt to bypass a blocked tool.
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
]


TOOL_FUNCTIONS = {
    "system_info": system_info,
    "list_processes": list_processes,
    "disk_usage": disk_usage,
    "list_directory": list_directory,
    "read_file": read_file,
    "run_command": run_command,
    "open_app": open_app,
}


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

    try:
        with urllib.request.urlopen(
            request,
            timeout=COMMAND_TIMEOUT + 60,
        ) as response:
            body = response.read().decode("utf-8")

        return json.loads(body)

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama HTTP {exc.code}: {body}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not connect to Ollama: {exc.reason}"
        ) from exc


def execute_tool(name, arguments):
    """Execute one tool call."""
    function = TOOL_FUNCTIONS.get(name)

    if function is None:
        return {
            "error": f"Unknown tool: {name}",
        }

    try:
        if not isinstance(arguments, dict):
            arguments = {}

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
            function_data = tool_call.get("function", {})

            name = function_data.get("name")
            arguments = function_data.get("arguments", {})

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

            if not isinstance(arguments, dict):
                arguments = {}

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

                result = execute_tool(name, arguments)

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
