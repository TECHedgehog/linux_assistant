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
    """Small conversation panel embedded in the floating launcher."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = AssistantSession()
        self.worker = None
        self.thread = None
        self.setMinimumWidth(350)

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

class FloatingButton(QPushButton):
    """Compact launcher with click-versus-drag handling."""

    def __init__(self, clicked, drag_started, dragged, drag_finished, parent=None):
        super().__init__("L", parent)
        self._clicked_callback = clicked
        self._drag_started_callback = drag_started
        self._dragged_callback = dragged
        self._drag_finished_callback = drag_finished
        self._press_position = None
        self._dragging = False
        self.setToolTip("Open Liam")
        self.setFixedSize(48, 48)
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

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self._press_position = event.globalPosition().toPoint()
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press_position is None:
            return
        current = event.globalPosition().toPoint()
        if not self._dragging:
            if (current - self._press_position).manhattanLength() < QApplication.startDragDistance():
                return
            self._dragging = True
            self._drag_started_callback(self._press_position)
        self._dragged_callback(current)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        was_dragging = self._dragging
        position = event.globalPosition().toPoint()
        self._press_position = None
        self._dragging = False
        if was_dragging:
            self._drag_finished_callback(position)
        else:
            self._clicked_callback()
        event.accept()


class FloatingSurface(QWidget):
    """Frameless top-level surface that hides instead of closing the tray app."""

    def __init__(self, close_callback):
        super().__init__()
        self._close_callback = close_callback

    def closeEvent(self, event):
        self._close_callback()
        event.ignore()


class FloatingChat:
    """Single top-level surface containing the launcher and chat panel."""

    EDGE_SNAP_DISTANCE = 24
    VISIBLE_EDGE_PORTION = 12
    EXPANSION_GAP = 8

    def __init__(self):
        self.window = FloatingSurface(self.hide_button)
        self.window.setWindowTitle("Liam")
        self.window.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.window.setAttribute(Qt.WA_QuitOnClose, False)
        self.window.setObjectName("floatingSurface")
        self.window.setStyleSheet("QWidget#floatingSurface { background: transparent; }")
        self.conversation = ConversationPanel(self.window)
        self.button = FloatingButton(
            self.toggle,
            self._drag_started,
            self._dragged,
            self._drag_finished,
            self.window,
        )
        self.expanded = False
        self.docked_edge = None
        self._drag_offset = None
        self._button_global_position = None
        self.window.resize(self.button.size())
        self.conversation.hide()
        self.position_button()
        self.window.show()

    def _screen_area(self, position):
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _button_position(self):
        return self.button.mapToGlobal(self.button.rect().topLeft())

    def position_button(self):
        area = self._screen_area(QCursor.pos())
        if area is None:
            return
        margin = 18
        x = area.right() - self.button.width() - margin
        y = area.bottom() - self.button.height() - margin
        self.window.move(x, y)
        self._button_global_position = self.window.pos()

    def _drag_started(self, press_position):
        if self.expanded:
            self._collapse()
        self._drag_offset = press_position - self._button_position()
        self.docked_edge = None

    def _dragged(self, current_position):
        if self._drag_offset is None:
            return
        area = self._screen_area(current_position)
        if area is None:
            return
        target = current_position - self._drag_offset
        x = max(area.left(), min(target.x(), area.right() - self.button.width() + 1))
        y = max(area.top(), min(target.y(), area.bottom() - self.button.height() + 1))
        self.window.move(x, y)
        self._button_global_position = self._button_position()

    def _drag_finished(self, release_position):
        if self._drag_offset is None:
            return
        area = self._screen_area(release_position)
        if area is None:
            self._drag_offset = None
            return
        position = self._button_position()
        distances = {
            "left": position.x() - area.left(),
            "right": area.right() - position.x() - self.button.width() + 1,
            "top": position.y() - area.top(),
            "bottom": area.bottom() - position.y() - self.button.height() + 1,
        }
        edge, distance = min(distances.items(), key=lambda item: item[1])
        if distance <= self.EDGE_SNAP_DISTANCE:
            self._dock(edge, area)
        else:
            self.docked_edge = None
            self._button_global_position = position
        self._drag_offset = None

    def _dock(self, edge, area):
        self.docked_edge = edge
        x, y = self.window.x(), self.window.y()
        if edge == "left":
            x = area.left() - self.button.width() + self.VISIBLE_EDGE_PORTION
            y = max(area.top(), min(y, area.bottom() - self.button.height() + 1))
        elif edge == "right":
            x = area.right() - self.VISIBLE_EDGE_PORTION + 1
            y = max(area.top(), min(y, area.bottom() - self.button.height() + 1))
        elif edge == "top":
            x = max(area.left(), min(x, area.right() - self.button.width() + 1))
            y = area.top() - self.button.height() + self.VISIBLE_EDGE_PORTION
        else:
            x = max(area.left(), min(x, area.right() - self.button.width() + 1))
            y = area.bottom() - self.VISIBLE_EDGE_PORTION + 1
        self.window.move(x, y)
        self._button_global_position = self._button_position()

    def _expanded_geometry(self, button_position):
        self.conversation.adjustSize()
        panel_size = self.conversation.sizeHint()
        button_size = self.button.size()
        area = self._screen_area(button_position)
        if area is None:
            return None

        if self.docked_edge == "left":
            width = button_size.width() + panel_size.width()
            height = max(button_size.height(), panel_size.height())
            x, y = button_position.x(), button_position.y()
            button_offset = (0, (height - button_size.height()) // 2)
            panel_offset = (button_size.width(), (height - panel_size.height()) // 2)
        elif self.docked_edge == "right":
            width = button_size.width() + panel_size.width()
            height = max(button_size.height(), panel_size.height())
            x, y = button_position.x() - panel_size.width(), button_position.y()
            button_offset = (panel_size.width(), (height - button_size.height()) // 2)
            panel_offset = (0, (height - panel_size.height()) // 2)
        elif self.docked_edge == "top":
            width = max(button_size.width(), panel_size.width())
            height = button_size.height() + panel_size.height()
            x, y = button_position.x(), button_position.y()
            button_offset = ((width - button_size.width()) // 2, 0)
            panel_offset = ((width - panel_size.width()) // 2, button_size.height())
        elif self.docked_edge == "bottom":
            width = max(button_size.width(), panel_size.width())
            height = button_size.height() + panel_size.height()
            x, y = button_position.x(), button_position.y() - panel_size.height()
            button_offset = ((width - button_size.width()) // 2, panel_size.height())
            panel_offset = ((width - panel_size.width()) // 2, 0)
        else:
            width = panel_size.width()
            height = panel_size.height() + button_size.height() + self.EXPANSION_GAP
            x = button_position.x() + button_size.width() - width
            y = button_position.y() - panel_size.height() - self.EXPANSION_GAP
            if y < area.top():
                y = button_position.y() + button_size.height() + self.EXPANSION_GAP
            button_offset = (width - button_size.width(), panel_size.height() + self.EXPANSION_GAP)
            panel_offset = (0, 0)

        x = max(area.left(), min(x, area.right() - width + 1))
        y = max(area.top(), min(y, area.bottom() - height + 1))
        return x, y, width, height, panel_size, button_offset, panel_offset

    def _collapse(self):
        button_position = self._button_position()
        edge = self.docked_edge
        self.expanded = False
        self.conversation.hide()
        self.window.resize(self.button.size())
        self.button.move(0, 0)
        if edge is None:
            self._button_global_position = button_position
            self.window.move(button_position)
        else:
            area = self._screen_area(button_position)
            if area is not None:
                self.window.move(button_position)
                self._dock(edge, area)
        self.button.raise_()

    def toggle(self, checked=False):
        if self.expanded:
            self._collapse()
        else:
            self.show()

    def show_button(self, checked=False):
        if self._button_global_position is None:
            self.position_button()
        self.window.show()
        self.button.show()
        self.button.raise_()

    def hide_button(self, checked=False):
        if self.expanded:
            self._collapse()
        self.window.hide()

    def show(self, checked=False):
        self.show_button()
        geometry = self._expanded_geometry(self._button_position())
        if geometry is None:
            return
        x, y, width, height, panel_size, button_offset, panel_offset = geometry
        self.window.resize(width, height)
        self.window.move(x, y)
        self.button.setGeometry(*button_offset, self.button.width(), self.button.height())
        self.conversation.setGeometry(
            *panel_offset, panel_size.width(), panel_size.height()
        )
        self.conversation.show()
        self.expanded = True
        self.button.raise_()
        self.window.raise_()
        self.window.activateWindow()
        self.conversation.input.setFocus()
