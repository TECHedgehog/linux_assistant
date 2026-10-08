# Linux Assistant

Local-first Linux desktop assistant for Ollama, CachyOS, Hyprland, and Caelestia.

## Run

```fish
python assistant.py
```

Ollama must be running locally with the configured model. Configuration can be
overridden with `LINUX_ASSISTANT_MODEL` and `LINUX_ASSISTANT_OLLAMA_URL`.

Conversation history is bounded by `LINUX_ASSISTANT_MAX_HISTORY_MESSAGES` (80)
and `LINUX_ASSISTANT_MAX_HISTORY_TOKENS` (12000, approximate). Set either to
`0` to disable that limit. Repeated identical tool calls are stopped after
`LINUX_ASSISTANT_MAX_DUPLICATE_TOOL_CALLS` (1) duplicate.

## Test

```fish
pytest -q
```

The supervisor owns tool permissions. Read-only tools are limited to approved
locations, generic commands require confirmation unless proven read-only, and
privileged or destructive operations are denied. File previews are read-only;
file changes are limited to the home directory and `/tmp`, require confirmation,
and preserve backups.
