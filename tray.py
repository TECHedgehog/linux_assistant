"""Tray entry point for Liam's floating desktop interface."""

import signal
import sys

from desktop_ui import FloatingChat
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class TrayApplication:
    """Own the tray icon and menu for the floating desktop interface."""

    def __init__(self, app):
        self.app = app
        self.floating_chat = FloatingChat()
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
