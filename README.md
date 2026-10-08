# Linux Assistant

Local-first Linux desktop assistant for Ollama, CachyOS, Hyprland, and Caelestia.

## Run

```fish
python assistant.py
```

Ollama must be running locally with the configured model. Configuration can be
overridden with `LINUX_ASSISTANT_MODEL` and `LINUX_ASSISTANT_OLLAMA_URL`.

## Test

```fish
pytest -q
```

The supervisor owns tool permissions. Read-only tools are limited to approved
locations, generic commands require confirmation unless proven read-only, and
privileged or destructive operations are denied.
