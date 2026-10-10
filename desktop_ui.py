"""Floating desktop interface for Liam."""

import json
import threading

try:
    from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # Keep CLI and tests usable without desktop extras.
    raise SystemExit(
        "Liam tray requires PySide6. Install it with: python -m pip install PySide6"
    ) from exc

from session import AssistantSession


class AssistantWorker(QObject):
    """Run model calls away from the Qt event loop."""

    finished = Signal(str)
    failed = Signal(str)
    tool_called = Signal(str)
    confirmation_requested = Signal(str, str)

    def __init__(self, session, prompt):
        super().__init__()
        self.session = session
        self.prompt = prompt
        self._confirmation = None
        self._confirmation_result = False

    @Slot()
    def run(self):
        try:
            answer = self.session.submit(
                self.prompt,
                confirm_callback=self.confirm,
                tool_output=self.show_tool,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(answer)

    def show_tool(self, name, arguments):
        self.tool_called.emit(f"{name}({json.dumps(arguments, ensure_ascii=False)})")

    def confirm(self, name, arguments):
        event = threading.Event()
        self._confirmation = event
        self._confirmation_result = False
        self.confirmation_requested.emit(
            name, json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        )
        event.wait()
        self._confirmation = None
        return self._confirmation_result

    def answer_confirmation(self, allowed):
        if self._confirmation is not None:
            self._confirmation_result = allowed
            self._confirmation.set()


class ConversationPanel(QWidget):
    """Small persistent conversation window."""

    def __init__(self):
        super().__init__(None)
        self.session = AssistantSession()
        self.worker = None
        self.thread = None
        self.setWindowTitle("Liam")
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setMinimumWidth(390)

        title = QLabel("<b>Liam</b>")
        title.setAlignment(Qt.AlignCenter)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMinimumHeight(220)
        self.transcript.setPlaceholderText("Ask Liam something...")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a request")
        self.input.returnPressed.connect(self.submit)
        self.send = QPushButton("Send")
        self.send.clicked.connect(self.submit)
        self.status = QLabel("Ready")
        self.confirmation = QLabel()
        self.confirmation.setWordWrap(True)
        self.confirmation.hide()
        self.allow = QPushButton("Allow")
        self.allow.clicked.connect(lambda: self.answer_confirmation(True))
        self.deny = QPushButton("Deny")
        self.deny.clicked.connect(lambda: self.answer_confirmation(False))
        self.allow.hide()
        self.deny.hide()

        input_row = QHBoxLayout()
        input_row.addWidget(self.input)
        input_row.addWidget(self.send)
        confirmation_row = QHBoxLayout()
        confirmation_row.addWidget(self.confirmation)
        confirmation_row.addWidget(self.allow)
        confirmation_row.addWidget(self.deny)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(title)
        layout.addWidget(self.transcript)
        layout.addLayout(confirmation_row)
        layout.addLayout(input_row)
        layout.addWidget(self.status)

    @Slot()
    def submit(self):
        prompt = self.input.text().strip()
        if not prompt or self.thread is not None:
            return
        self.input.clear()
        self.transcript.append(f"<b>You:</b> {prompt}")
        self.status.setText("Thinking...")
        self.send.setEnabled(False)
        self.worker = AssistantWorker(self.session, prompt)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.tool_called.connect(lambda text: self.status.setText(f"Tool: {text}"))
        self.worker.confirmation_requested.connect(self.request_confirmation)
        self.worker.finished.connect(self.response_finished)
        self.worker.failed.connect(self.request_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.worker_finished)
        self.thread.start()

    @Slot(str, str)
    def request_confirmation(self, name, arguments):
        self.confirmation.setText(f"Allow {name}({arguments})?")
        self.confirmation.show()
        self.allow.show()
        self.deny.show()
        self.status.setText("Confirmation required")

    def answer_confirmation(self, allowed):
        if self.worker:
            self.worker.answer_confirmation(allowed)
        self.confirmation.hide()
        self.allow.hide()
        self.deny.hide()

    @Slot(str)
    def response_finished(self, answer):
        self.transcript.append(f"<b>Liam:</b> {answer}")
        self.status.setText("Ready")

    @Slot(str)
    def request_failed(self, error):
        self.transcript.append(f"<b>Error:</b> {error}")
        self.status.setText("Error")

    def worker_finished(self):
        self.worker = None
        self.thread = None
        self.send.setEnabled(True)

    def clear(self):
        if self.thread is not None:
            return
        self.session.clear()
        self.transcript.clear()
        self.status.setText("Ready")

    def closeEvent(self, event):
        """Hide the panel instead of destroying the persistent chat session."""
        self.hide()
        event.ignore()


class FloatingButton(QPushButton):
    """Compact launcher that stays available above normal application windows."""

    def __init__(self, clicked):
        super().__init__("L")
        self.setWindowTitle("Liam")
        self.setToolTip("Open Liam")
        self.setFixedSize(48, 48)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setStyleSheet(
            """
            QPushButton {
                background: #5e81ac;
                border: 2px solid #88c0d0;
                border-radius: 24px;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover { background: #81a1c1; }
            QPushButton:pressed { background: #4c566a; }
            """
        )
        self.clicked.connect(clicked)

    def closeEvent(self, event):
        event.ignore()


class FloatingChat:
    """Own and position the launcher and its connected conversation window."""

    def __init__(self):
        self.conversation = ConversationPanel()
        self.button = FloatingButton(self.toggle)
        self.button.show()
        self.position_button()

    def position_button(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = 18
        self.button.move(
            area.right() - self.button.width() - margin,
            area.bottom() - self.button.height() - margin,
        )

    def toggle(self, checked=False):
        if self.conversation.isVisible():
            self.conversation.hide()
        else:
            self.show()

    def show_button(self, checked=False):
        self.position_button()
        self.button.show()
        self.button.raise_()

    def hide_button(self, checked=False):
        self.button.hide()

    def show(self, checked=False):
        self.show_button()
        self.conversation.adjustSize()
        button_position = self.button.pos()
        x = button_position.x() + self.button.width() - self.conversation.width()
        y = button_position.y() - self.conversation.height() - 8
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - self.conversation.width()))
            if y < area.top():
                y = button_position.y() + self.button.height() + 8
        self.conversation.move(x, y)
        self.conversation.show()
        self.conversation.raise_()
        self.conversation.activateWindow()
        self.conversation.input.setFocus()
