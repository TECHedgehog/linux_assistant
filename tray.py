"""Tray entry point for Liam's floating desktop interface."""

import signal
import os
import subprocess
import sys
import time
from pathlib import Path

from desktop_ui import FloatingChat
from layer_shell_ipc import send_command, socket_path
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class _LayerButtonState:
    def __init__(self):
        self.visible = True

    def isVisible(self):
        return self.visible


class LayerShellController:
    """Control the optional GTK layer-shell frontend through private IPC."""

    def __init__(self):
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("layer_shell_ui.py"))]
        )
        self.path = socket_path()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.path.exists():
                break
            if self.process.poll() is not None:
                raise RuntimeError("layer-shell frontend exited during startup")
            time.sleep(0.02)
        if not self.path.exists():
            self.process.terminate()
            raise RuntimeError("layer-shell frontend did not create its socket")
        self.button = _LayerButtonState()
        self.conversation = self

    def _send(self, command):
        try:
            send_command(self.path, command)
        except OSError:
            self.button.visible = False

    def show_button(self, checked=False):
        self.button.visible = True
        self._send("show")

    def hide_button(self, checked=False):
        self.button.visible = False
        self._send("hide")

    def clear(self):
        self._send("clear")

    def hide(self):
        self.hide_button()

    def close(self):
        self._send("quit")
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()


def create_floating_chat():
    """Prefer layer-shell on Wayland and retain the Qt fallback."""
    if os.environ.get("WAYLAND_DISPLAY"):
        check = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("layer_shell_ui.py")), "--check"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if check.returncode == 0:
            try:
                return LayerShellController()
            except (OSError, RuntimeError):
                pass
    return FloatingChat()


class TrayApplication:
    """Own the tray icon and menu for the floating desktop interface."""

    def __init__(self, app):
        self.app = app
        self.floating_chat = create_floating_chat()
        self.menu = QMenu()

        show_button_action = QAction("Show floating button", self.menu)
        show_button_action.triggered.connect(self.floating_chat.show_button)
        self.menu.addAction(show_button_action)

        hide_button_action = QAction("Hide floating button", self.menu)
        hide_button_action.triggered.connect(self.floating_chat.hide_button)
        self.menu.addAction(hide_button_action)
        self.menu.aboutToShow.connect(
            lambda: self.update_button_actions(show_button_action, hide_button_action)
        )

        clear_action = QAction("Clear conversation", self.menu)
        clear_action.triggered.connect(self.floating_chat.conversation.clear)
        self.menu.addAction(clear_action)
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.shutdown)
        self.menu.addAction(quit_action)

        icon = QIcon.fromTheme("dialog-information")
        self.tray = QSystemTrayIcon(icon, app)
        self.tray.setToolTip("Liam")
        self.tray.activated.connect(self.activated)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def shutdown(self, checked=False):
        """Hide desktop surfaces before stopping the Qt event loop."""
        self.tray.hide()
        if isinstance(self.floating_chat, LayerShellController):
            self.floating_chat.close()
        else:
            self.floating_chat.conversation.hide()
            self.floating_chat.button.hide()
        self.app.quit()

    def update_button_actions(self, show_action, hide_action):
        visible = self.floating_chat.button.isVisible()
        show_action.setEnabled(not visible)
        hide_action.setEnabled(visible)

    def activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.menu.popup(QCursor.pos())


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = TrayApplication(app)

    # Treat terminal Ctrl+Z as an intentional application exit. Without this
    # handler SIGTSTP suspends the process while its Qt windows remain visible.
    signal.signal(signal.SIGTSTP, lambda *_: controller.shutdown())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
