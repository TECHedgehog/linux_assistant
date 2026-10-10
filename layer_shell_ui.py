"""GTK layer-shell frontend for Liam's floating desktop assistant."""

import json
import os
import socket
import sys
import threading

try:
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
except (ImportError, ValueError) as exc:
    raise SystemExit(
        "Liam layer-shell UI requires PyGObject, GTK3, and gtk-layer-shell"
    ) from exc

from layer_shell_ipc import socket_path
from session import AssistantSession


class LayerShellChat:
    """Own the layer surface, chat widgets, and private control socket."""

    BUTTON_SIZE = 48
    EDGE_MARGIN = -36
    SNAP_DISTANCE = 80

    def __init__(self):
        self.session = AssistantSession()
        self.worker = None
        self.confirmation_event = None
        self.confirmation_result = False
        self.expanded = False
        self.edge = "bottom"
        self.along = 18
        self.drag_start = None
        self.drag_along_start = 0
        self.surface = Gtk.Window()
        self.surface.set_decorated(False)
        self.surface.set_resizable(False)
        self.surface.set_app_paintable(True)
        self.surface.connect("destroy", self._destroyed)
        self._configure_layer_surface()
        self._build_widgets()
        self._start_socket()

    def _configure_layer_surface(self):
        GtkLayerShell.init_for_window(self.surface)
        GtkLayerShell.set_namespace(self.surface, "liam")
        GtkLayerShell.set_layer(self.surface, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self.surface, 0)
        GtkLayerShell.set_keyboard_mode(
            self.surface, GtkLayerShell.KeyboardMode.ON_DEMAND
        )

    def _build_widgets(self):
        self.root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.root.get_style_context().add_class("liam-surface")
        self.surface.add(self.root)

        self.button = Gtk.Button(label="L")
        self.button.set_size_request(self.BUTTON_SIZE, self.BUTTON_SIZE)
        self.button.get_style_context().add_class("liam-button")
        self.button.connect("clicked", self.toggle)
        self.drag = Gtk.GestureDrag.new(self.button)
        self.drag.connect("drag-begin", self._drag_begin)
        self.drag.connect("drag-update", self._drag_update)
        self.drag.connect("drag-end", self._drag_end)
        self.root.pack_start(self.button, False, False, 0)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.panel.set_size_request(350, 300)
        self.panel.get_style_context().add_class("liam-panel")
        self.root.pack_start(self.panel, True, True, 0)

        title = Gtk.Label(label="Liam")
        self.panel.pack_start(title, False, False, 0)
        self.transcript = Gtk.TextView()
        self.transcript.set_editable(False)
        self.transcript.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        transcript_scroll = Gtk.ScrolledWindow()
        transcript_scroll.set_min_content_height(180)
        transcript_scroll.add(self.transcript)
        self.panel.pack_start(transcript_scroll, True, True, 0)

        input_row = Gtk.Box(spacing=6)
        self.input = Gtk.Entry()
        self.input.set_placeholder_text("Type a request")
        self.input.connect("activate", self.submit)
        send = Gtk.Button(label="Send")
        send.connect("clicked", self.submit)
        input_row.pack_start(self.input, True, True, 0)
        input_row.pack_start(send, False, False, 0)
        self.panel.pack_start(input_row, False, False, 0)

        self.confirmation = Gtk.Label()
        self.confirmation.set_line_wrap(True)
        self.panel.pack_start(self.confirmation, False, False, 0)
        confirmation_row = Gtk.Box(spacing=6)
        allow = Gtk.Button(label="Allow")
        deny = Gtk.Button(label="Deny")
        allow.connect("clicked", lambda *_: self.answer_confirmation(True))
        deny.connect("clicked", lambda *_: self.answer_confirmation(False))
        confirmation_row.pack_start(allow, False, False, 0)
        confirmation_row.pack_start(deny, False, False, 0)
        self.panel.pack_start(confirmation_row, False, False, 0)
        self.status = Gtk.Label(label="Ready")
        self.panel.pack_start(self.status, False, False, 0)
        self.panel.hide()

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            .liam-surface { background: transparent; }
            .liam-button { background: #5e81ac; color: white; border-radius: 24px; }
            .liam-panel { background: #2e3440; color: #eceff4; border-radius: 12px; padding: 8px; }
            """
        )
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _start_socket(self):
        self.path = socket_path()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        self.server.settimeout(0.5)
        self.socket_thread = threading.Thread(target=self._accept_commands, daemon=True)
        self.socket_thread.start()

    def _accept_commands(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                data = connection.recv(4096)
            try:
                message = json.loads(data.decode())
                command = message["command"]
            except (ValueError, KeyError, UnicodeDecodeError):
                continue
            GLib.idle_add(self._handle_command, command)

    def _handle_command(self, command):
        if command == "show":
            self.surface.show_all()
            if not self.expanded:
                self.panel.hide()
        elif command == "hide":
            self.surface.hide()
        elif command == "clear":
            self.clear()
        elif command == "quit":
            Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    def _set_edge(self, edge, along):
        for anchor in (
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.BOTTOM,
        ):
            GtkLayerShell.set_anchor(self.surface, anchor, False)

        if edge == "left":
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.LEFT, self.EDGE_MARGIN if not self.expanded else 0)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.TOP, along)
        elif edge == "right":
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.RIGHT, self.EDGE_MARGIN if not self.expanded else 0)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.TOP, along)
        elif edge == "top":
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.LEFT, along)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.TOP, self.EDGE_MARGIN if not self.expanded else 0)
        else:
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.LEFT, True)
            GtkLayerShell.set_anchor(self.surface, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.LEFT, along)
            GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.BOTTOM, self.EDGE_MARGIN if not self.expanded else 0)

    def _resize_surface(self):
        self.root.set_orientation(
            Gtk.Orientation.HORIZONTAL
            if self.edge in ("left", "right")
            else Gtk.Orientation.VERTICAL
        )
        self.root.reorder_child(self.button, 0 if self.edge in ("left", "top") else 1)
        self.panel.show() if self.expanded else self.panel.hide()
        self._set_edge(self.edge, self.along)

    def toggle(self, *_args):
        self.expanded = not self.expanded
        self._resize_surface()
        self.surface.show_all()
        if not self.expanded:
            self.panel.hide()
        else:
            self.input.grab_focus()

    def _drag_begin(self, _gesture, start_x, start_y):
        self.expanded = False
        self.panel.hide()
        self.drag_start = (start_x, start_y)
        self.drag_along_start = self.along
        GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.LEFT, 0)
        GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.RIGHT, 0)
        GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.TOP, 0)
        GtkLayerShell.set_margin(self.surface, GtkLayerShell.Edge.BOTTOM, 0)

    def _drag_update(self, _gesture, offset_x, offset_y):
        if self.edge in ("left", "right"):
            self.along = max(0, int(self.drag_along_start + offset_y))
        else:
            self.along = max(0, int(self.drag_along_start + offset_x))
        self._set_edge(self.edge, self.along)

    def _drag_end(self, _gesture, _offset_x, _offset_y):
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
        _screen, x, y = pointer.get_position()
        monitor = Gdk.Display.get_default().get_monitor_at_point(x, y)
        workarea = monitor.get_workarea() if monitor is not None else None
        if workarea is not None:
            distances = {
                "left": x - workarea.x,
                "right": workarea.x + workarea.width - x,
                "top": y - workarea.y,
                "bottom": workarea.y + workarea.height - y,
            }
            self.edge = min(distances, key=distances.get)
            self.along = (
                y - workarea.y if self.edge in ("left", "right") else x - workarea.x
            )
        self._set_edge(self.edge, self.along)

    def submit(self, *_args):
        prompt = self.input.get_text().strip()
        if not prompt or self.worker is not None:
            return
        self.input.set_text("")
        self._append(f"You: {prompt}")
        self.status.set_text("Thinking...")
        self.worker = threading.Thread(target=self._run_prompt, args=(prompt,), daemon=True)
        self.worker.start()

    def _run_prompt(self, prompt):
        try:
            answer = self.session.submit(
                prompt, confirm_callback=self.confirm, tool_output=self.show_tool
            )
        except Exception as exc:
            GLib.idle_add(self._finished, f"Error: {exc}", True)
        else:
            GLib.idle_add(self._finished, f"Liam: {answer}", False)

    def _finished(self, text, failed):
        self._append(text)
        self.status.set_text("Error" if failed else "Ready")
        self.worker = None
        return GLib.SOURCE_REMOVE

    def _append(self, text):
        buffer = self.transcript.get_buffer()
        end = buffer.get_end_iter()
        buffer.insert(end, text + "\n")

    def show_tool(self, name, arguments):
        GLib.idle_add(self.status.set_text, f"Tool: {name}({json.dumps(arguments)})")

    def confirm(self, name, arguments):
        self.confirmation_event = threading.Event()
        GLib.idle_add(self._show_confirmation, name, arguments)
        self.confirmation_event.wait()
        return self.confirmation_result

    def _show_confirmation(self, name, arguments):
        self.confirmation.set_text(f"Allow {name}({json.dumps(arguments)})?")
        self.status.set_text("Confirmation required")
        return GLib.SOURCE_REMOVE

    def answer_confirmation(self, allowed):
        if self.confirmation_event is not None:
            self.confirmation_result = allowed
            self.confirmation_event.set()
            self.confirmation_event = None

    def clear(self):
        if self.worker is not None:
            return
        self.session.clear()
        self.transcript.get_buffer().set_text("")
        self.status.set_text("Ready")

    def _destroyed(self, *_args):
        try:
            self.server.close()
            self.path.unlink()
        except (AttributeError, FileNotFoundError, OSError):
            pass


def main():
    if "--check" in sys.argv:
        return 0
    app = LayerShellChat()
    app.surface.show_all()
    app.panel.hide()
    app._set_edge(app.edge, app.along)
    try:
        Gtk.main()
    finally:
        app._destroyed()
    return 0


if __name__ == "__main__":
    sys.exit(main())
