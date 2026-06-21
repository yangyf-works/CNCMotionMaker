from __future__ import annotations
import math
from PySide6.QtCore import Qt, QRect, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import re

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(
            self.editor.line_number_area_width(), 0,)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class ProgramEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()

        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(
            self.update_line_number_area_width
        )
        self.updateRequest.connect(
            self.update_line_number_area
        )
        self.cursorPositionChanged.connect(
            self.highlight_current_line
        )

        self.update_line_number_area_width(0)
        self.highlight_current_line()

        font = QFont("Consolas", 10)
        self.setFont(font)

        self.setPlainText(
            "X1 Y2 Z1 F60\n"
            "Tool OFF\n"
            "WAIT 2.5\n"
            "X-1 Y-1\n"
            "Work ON\n"
            "Y0 Z2 F12\n"
            "Z-2 F20"
        )

    def line_number_area_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(
            self.line_number_area_width(),
            0,
            0,
            0,
        )

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0,
                rect.y(),
                self.line_number_area.width(),
                rect.height(),
            )

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(
                cr.left(),
                cr.top(),
                self.line_number_area_width(),
                cr.height(),
            )
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(
            event.rect(),
            QColor(70, 70, 70),
        )

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(
            self.blockBoundingGeometry(block)
            .translated(self.contentOffset())
            .top()
        )
        bottom = top + int(
            self.blockBoundingRect(block).height()
        )

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)

                painter.setPen(QColor(180, 180, 180))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + int(
                self.blockBoundingRect(block).height()
            )
            block_number += 1

    def highlight_current_line(self):
        if self.isReadOnly():
            return

        extra_selection = QTextEdit.ExtraSelection()

        extra_selection.format.setBackground(
            QColor(45, 75, 85)
        )
        extra_selection.format.setProperty(
            QTextFormat.FullWidthSelection,
            True,
        )

        extra_selection.cursor = self.textCursor()
        extra_selection.cursor.clearSelection()

        self.setExtraSelections([extra_selection])

    def highlight_program_line(self, line_index):
        selections = []

        if line_index is not None and line_index >= 0:
            block = self.document().findBlockByNumber(line_index)

            if block.isValid():
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(QColor(120, 150, 100))
                selection.format.setProperty(
                    QTextFormat.FullWidthSelection,
                    True,
                )
                selection.cursor = self.textCursor()
                selection.cursor.setPosition(block.position())
                selection.cursor.clearSelection()
                selections.append(selection)

                self.setTextCursor(selection.cursor)
                self.centerCursor()

        self.setExtraSelections(selections)

class ProgramWindowQt(QMainWindow):
    def __init__(self, on_position_sample=None):
        super().__init__()
        self.on_position_sample = on_position_sample

        self.setWindowTitle("NC Program")
        self.resize(300, 720)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
        )

        self.editor = ProgramEditor()

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.step_forward_button = QPushButton("Next Step")
        self.step_back_button = QPushButton("Back Step")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)

        self.samples = []
        self.sample_index = 0

        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.stop)
        self.step_forward_button.clicked.connect(self.step_forward)
        self.step_back_button.clicked.connect(self.step_back)

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(
            [
                "10 ms",
                "20 ms",
                "50 ms",
                "100 ms",
                "200 ms",
                "500 ms",
                "1000 ms",
            ]
        )
        self.interval_combo.setCurrentText("100 ms")
        
        buttons = [
            self.play_button,
            self.stop_button,
            self.step_back_button,
            self.step_forward_button,
        ]

        for button in buttons:
            button.setFixedHeight(26)
        
        self.interval_combo.setFixedHeight(24)
        self.interval_combo.currentIndexChanged.connect(
            self.on_interval_changed
        )

        side_layout = QVBoxLayout()
        side_layout.setContentsMargins(0,0,0,0)
        
        side_layout.setSpacing(4)

        side_layout.addWidget(self.play_button)
        side_layout.addWidget(self.stop_button)
        side_layout.addWidget(self.step_back_button)
        side_layout.addWidget(self.step_forward_button)

        side_layout.addSpacing(4)

        side_layout.addWidget(QLabel("Interval"))
        side_layout.addWidget(self.interval_combo)

        side_layout.addStretch()

        side_widget = QWidget()
        side_widget.setLayout(side_layout)
        side_widget.setFixedWidth(70)

        root_layout = QHBoxLayout()
        root_layout.addWidget(self.editor, 1)
        root_layout.addWidget(side_widget)

        self._drag_start_pos = None
        title_bar = self.create_title_bar()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(title_bar)
        main_layout.addLayout(root_layout)

        root = QWidget()
        root.setLayout(main_layout)

        self.setCentralWidget(root)
        self.apply_dark_theme()

    def create_title_bar(self):
        title_bar = QWidget()
        title_bar.setObjectName("TitleBar")
        title_bar.setFixedHeight(28)

        layout = QHBoxLayout()
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("NC Program")

        close_button = QPushButton("✕")
        close_button.setObjectName("CloseButton")
        close_button.setFixedSize(30, 30)
        close_button.clicked.connect(self.close)

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(close_button)

        title_bar.setLayout(layout)
        title_bar.mousePressEvent = self.title_bar_mouse_press_event
        title_bar.mouseMoveEvent = self.title_bar_mouse_move_event
        title_bar.mouseReleaseEvent = self.title_bar_mouse_release_event

        return title_bar
    
    def title_bar_mouse_press_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()


    def title_bar_mouse_move_event(self, event):
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
        ):
            self.move(
                event.globalPosition().toPoint()
                - self._drag_start_pos
            )
            event.accept()


    def title_bar_mouse_release_event(self, event):
        self._drag_start_pos = None
        event.accept()

    def get_program_text(self):
        return self.editor.toPlainText()

    def get_interval_sec(self):
        text = self.interval_combo.currentText()
        ms = int(text.replace(" ms", ""))
        return ms / 1000.0
    
    def send_position(self, position):
        print(position)

        if self.on_position_sample is not None:
            self.on_position_sample(position)

    def parse_program(self):
        interval_sec = self.get_interval_sec()

        current = {}
        current_feed = 1000.0  # mm/min
        samples = []

        for line_index, line in enumerate(self.get_program_text().splitlines()):
            line = line.strip()

            if not line:
                continue

            line_upper = line.upper()
            if line_upper.startswith("WAIT "):
                wait_sec = float(line.split()[1])

                step_count = max(
                    1,
                    math.ceil(wait_sec / interval_sec)
                )

                for _ in range(step_count):
                    samples.append({
                        "position": current.copy(),
                        "line_index": line_index,
                    })

                continue

            target = current.copy()
            feed = current_feed

            parts = line.split()

            if len(parts) == 2 and parts[1].upper() in ("ON", "OFF"):
                signal_name = parts[0]
                signal_value = 1.0 if parts[1].upper() == "ON" else 0.0

                current[signal_name] = signal_value

                samples.append({
                    "position": current.copy(),
                    "line_index": line_index,
                })

                continue

            for part in parts:
                match = re.fullmatch(
                    r"([A-Za-z]{1,2})([-+]?\d*\.?\d+)",
                    part
                )
                if not match:
                    raise ValueError(
                        f"Invalid word: {part}"
                    )

                key = match.group(1).upper()
                value = float(match.group(2))

                if key == "F":
                    feed = value
                else:
                    target[key] = value

                    if key not in current:
                        current[key] = 0.0

            moving_axes = set(current.keys()) | set(target.keys())

            distance_sq = 0.0

            for axis in moving_axes:
                start_value = current.get(axis, 0.0)
                end_value = target.get(axis, start_value)
                diff = end_value - start_value
                distance_sq += diff * diff

            distance = math.sqrt(distance_sq)

            if distance <= 1e-9:
                current = target
                current_feed = feed

                samples.append({
                    "position": current.copy(),
                    "line_index": line_index,
                })
                continue

            feed_mm_per_sec = feed / 60.0

            if feed_mm_per_sec <= 1e-9:
                raise ValueError("Feed must be greater than 0")

            move_time = distance / feed_mm_per_sec
            step_count = max(1, math.ceil(move_time / interval_sec))

            for i in range(1, step_count + 1):
                t = i / step_count

                sample = {}

                for axis in moving_axes:
                    start_value = current.get(axis, 0.0)
                    end_value = target.get(axis, start_value)

                    sample[axis] = start_value + (
                        end_value - start_value
                    ) * t

                samples.append({
                    "position": sample,
                    "line_index": line_index,
                })

            current = target
            current_feed = feed

        return samples
    
    def play(self):
        try:
            if not self.samples:
                self.samples = self.parse_program()
                self.sample_index = 0
        except ValueError as e:
            print(f"Program error: {e}")
            return

        if not self.samples:
            return

        if self.sample_index >= len(self.samples):
            return

        self.set_program_editable(False)

        interval_ms = int(self.get_interval_sec() * 1000)
        self.timer.start(interval_ms)
    
    def stop(self):
        self.timer.stop()
        self.samples = []
        self.sample_index = 0
        self.set_program_editable(True)
        self.editor.highlight_program_line(None)
    
    def _on_timer(self):
        if self.sample_index >= len(self.samples):
            self.stop()
            return

        sample_info = self.samples[self.sample_index]

        position = sample_info["position"]
        line_index = sample_info["line_index"]

        self.editor.highlight_program_line(line_index)
        self.send_position(position)

        self.sample_index += 1

    def step_forward(self):
        self.pause_playback()
        self.set_program_editable(False)
        if not self.samples:
            self.samples = self.parse_program()
            self.sample_index = 0

        if self.sample_index >= len(self.samples):
            return

        sample_info = self.samples[self.sample_index]

        self.editor.highlight_program_line(sample_info["line_index"])
        self.send_position(sample_info["position"])

        self.sample_index += 1

    def step_back(self):
        self.pause_playback()
        self.set_program_editable(False)
        if not self.samples:
            self.samples = self.parse_program()
            self.sample_index = 0

        if not self.samples:
            return

        self.sample_index = max(0, self.sample_index - 2)

        sample_info = self.samples[self.sample_index]

        self.editor.highlight_program_line(
            sample_info["line_index"]
        )

        self.send_position(
            sample_info["position"]
        )

        self.sample_index += 1

    def pause_playback(self):
        if self.timer.isActive():
            self.timer.stop()

    def apply_dark_theme(self):
        self.setStyleSheet("""
            QWidget#TitleBar {
                background-color: #f3f3f3;
                border-bottom: 1px solid #d0d0d0;
            }

            QWidget#TitleBar QLabel {
                background-color: #f3f3f3;
                color: #202020;
                font-size: 12px;
            }

            QWidget#TitleBar QPushButton {
                background-color: #f3f3f3;
                color: #909090;
                border: none;
                font-size: 18px;
            }

            QWidget#TitleBar QPushButton:hover {
                background-color: #e5e5e5;
            }

            QWidget#TitleBar QPushButton:pressed {
                background-color: #d8d8d8;
            }
            QWidget#TitleBar QPushButton#CloseButton:hover {
                background-color: #c42b1c;
                color: white;
            }
            QMainWindow {
                background-color: #232323;
            }

            QWidget {
                background-color: #232323;
                color: white;
            }

            QPlainTextEdit {
                background-color: #1e1e1e;
                color: white;
                selection-background-color: #4678c8;
                selection-color: white;
            }

            QPushButton {
                background-color: #404040;
                color: white;
                border: 1px solid #555555;
                padding: 3px;
            }

            QPushButton:hover {
                background-color: #505050;
            }

            QComboBox {
                background-color: #404040;
                color: white;
                border: 1px solid #555555;
                padding: 2px;
            }

            QLabel {
                color: white;
            }
        """)

    def set_program_editable(self, editable: bool):
        self.editor.setReadOnly(not editable)
        if editable:
            self.editor.highlight_current_line()
    
    def on_interval_changed(self, index):
        self.stop()

if __name__ == "__main__":
    app = QApplication([])

    window = ProgramWindowQt()
    window.show()

    app.exec()