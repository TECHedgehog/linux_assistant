# Liam

Liam is a local-first Linux desktop assistant for Ollama, CachyOS, Hyprland, and Caelestia.

## Run

```fish
python assistant.py
```

Install optional tray interface with `uv venv .venv && uv pip install --python .venv/bin/python PySide6`, then run:

```fish
.venv/bin/python tray.py
```

Tray interface provides a small floating Liam button. Click it to open a compact
chat window. The tray icon remains available for clearing the conversation,
hiding or showing the floating button, and quitting.

On Wayland, Liam automatically uses the optional GTK layer-shell frontend when
PyGObject, GTK3, and `gtk-layer-shell` are installed. On Arch-based systems,
install `python-gobject`, `gtk3`, and `gtk-layer-shell`. On Debian-based systems,
install `python3-gi`, `gir1.2-gtk-3.0`, and `gir1.2-gtklayershell-0.1`.
The layer-shell frontend is not tiled by Hyprland and does not require a
Hyprland window rule. Without these dependencies, Liam uses the Qt fallback.

The Qt fallback uses always-on-top desktop hints and does not create a taskbar
application entry. On Hyprland, use a `pin` window rule if the fallback button
must remain visible on every workspace:

```ini
windowrulev2 = pin, title:^(Liam)$
```

For Hyprland, launch `tray.py` with `exec-once`:

```ini
exec-once = python /path/to/liam/tray.py
```

Caelestia can launch Liam through the included desktop entry in `desktop/liam.desktop`.

Ollama must be running locally with the configured model. Configuration can be
overridden with `LIAM_MODEL` and `LIAM_OLLAMA_URL` environment variables.

Conversation history is bounded by `LIAM_MAX_HISTORY_MESSAGES` (80)
and `LIAM_MAX_HISTORY_TOKENS` (12000, approximate). Set either to
`0` to disable that limit. Repeated identical tool calls are stopped after
`LIAM_MAX_DUPLICATE_TOOL_CALLS` (1) duplicate.

## Test

```fish
pytest -q
```

The supervisor owns tool permissions. Read-only tools are limited to approved
locations, generic commands require confirmation unless proven read-only, and
privileged or destructive operations are denied. File previews are read-only;
file changes are limited to the home directory and `/tmp`, require confirmation,
and preserve backups.
