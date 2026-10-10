"""Interactive command-line session lifecycle."""

import json
import sys

from config import MODEL
from supervisor import ask


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


def confirm_tool_call(name, arguments):
    print(f"\n[confirmation required] Allow {name}({json.dumps(arguments, ensure_ascii=False)})? [y/N] ",
          end="", file=sys.stderr, flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False
    return answer in {"y", "yes"}


def _show_tool(name, arguments):
    print(f"\n[tool] {name}({json.dumps(arguments, ensure_ascii=False)})", file=sys.stderr)


def main():
    print(f"Liam — {MODEL}")
    print("Type 'exit' or 'quit' to leave.\n")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        messages.append({"role": "user", "content": user_input})
        try:
            answer = ask(messages, confirm_callback=confirm_tool_call, tool_output=_show_tool)
            messages.append({"role": "assistant", "content": answer})
            print(f"\nAssistant> {answer}\n")
        except KeyboardInterrupt:
            print("\nInterrupted.\n")
        except Exception as exc:
            print(f"\nError: {exc}\n", file=sys.stderr)
            if messages and messages[-1].get("role") == "user":
                messages.pop()
