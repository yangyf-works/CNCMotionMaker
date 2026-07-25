from __future__ import annotations

import math
import re
from enum import Enum, auto

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.qt_style import TitleBar, apply_common_dark_theme

class ProgramState(Enum):
    STOPPED = auto()
    RUNNING = auto()
    PAUSED = auto()
    
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(
            self.editor.line_number_area_width(), 0,)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class ProgramParseError(ValueError):
    def __init__(
        self,
        line_index: int,
        message: str,
    ):
        super().__init__(message)

        self.line_index = line_index
        self.message = message

    def __str__(self):
        return (
            f"Line {self.line_index + 1}: "
            f"{self.message}"
        )

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
            "X1 Y2 Z1 B-90 F600\n"
            "Tool OFF\n"
            "WAIT 1.5\n"
            "X-1 Y-1 B30 F400\n"
            "Work ON\n"
            "Y0 Z2 B45 C90 F300\n"
            "Z-2 F200"
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
    
    def highlight_error_line(self, line_index):
        block = self.document().findBlockByNumber(
            line_index
        )

        if not block.isValid():
            return

        cursor = self.textCursor()
        cursor.setPosition(block.position())
        cursor.clearSelection()

        self.setTextCursor(cursor)
        self.centerCursor()

        selection = QTextEdit.ExtraSelection()

        selection.format.setBackground(
            QColor(150, 45, 45)
        )
        selection.format.setProperty(
            QTextFormat.FullWidthSelection,
            True,
        )

        selection.cursor = cursor

        self.setExtraSelections([selection])

    def clear_line_highlight(self):
        self.setExtraSelections([])
        self.highlight_current_line()

    def replace_program_text(self, text: str):
        cursor = self.textCursor()
        old_position = cursor.position()

        self.blockSignals(True)

        try:
            self.setPlainText(text)
        finally:
            self.blockSignals(False)

        cursor = self.textCursor()
        cursor.setPosition(
            min(
                old_position,
                len(text),
            )
        )

        self.setTextCursor(cursor)
        self.highlight_current_line()

class MachinePanelQt(QMainWindow):
    NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    
    def __init__(self, on_position_sample=None):
        super().__init__()
        self.on_position_sample = on_position_sample

        self.resize(300, 720)
        self.setWindowTitle("Machine Panel")
        self.setWindowFlags(Qt.WindowType.Tool |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint)

        self.samples = []
        self.sample_index = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)

        self.machine_timer = QTimer(self)
        self.machine_timer.timeout.connect(self.poll_machine)

        self._drag_start_pos = None
        
        self.program_state = ProgramState.STOPPED

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)

        self.program_tab = self.create_program_tab()
        self.digital_twin_tab = self.create_digital_twin_tab()

        self.tabs.addTab(self.program_tab, "NC Program")
        self.tabs.addTab(self.digital_twin_tab, "Digital Twin")

        self.tabs.currentChanged.connect(
            self.on_tab_changed
        )

        self.step_hold_timer = QTimer(self)
        self.step_hold_timer.timeout.connect(self._on_step_hold_timer)
        self.step_hold_action = None
        self.step_repeat_mode = False

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.tabs)

        root = QWidget()
        root.setLayout(main_layout)

        self.setCentralWidget(root)
        apply_common_dark_theme(self)

    def on_close_clicked(self):
        pass
    
    def create_program_tab(self):
        self.editor = ProgramEditor()

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setStyleSheet("""
            QPushButton:pressed {
                background-color: #B71C1C;
                color: white;
            }
            """)
        self.step_forward_button = QPushButton("Next Step")
        self.step_back_button = QPushButton("Back Step")

        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.stop)
        self.step_forward_button.pressed.connect(
            lambda: self.start_step_hold(self.step_forward)
        )
        self.step_forward_button.released.connect(self.stop_step_hold)

        self.step_back_button.pressed.connect(
            lambda: self.start_step_hold(self.step_back)
        )
        self.step_back_button.released.connect(self.stop_step_hold)

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
        self.interval_combo.currentIndexChanged.connect(
            self.on_interval_changed
        )
        self.interval_combo.setFixedHeight(24)

        buttons = [
            self.play_button,
            self.stop_button,
            self.step_back_button,
            self.step_forward_button,
        ]

        for button in buttons:
            button.setFixedHeight(26)

        side_layout = QVBoxLayout()
        side_layout.setContentsMargins(0,0,0,0)
        
        side_layout.setSpacing(4)

        side_layout.addWidget(self.play_button)
        side_layout.addWidget(self.step_forward_button)
        side_layout.addWidget(self.step_back_button)
        side_layout.addWidget(self.stop_button)

        side_layout.addSpacing(4)
        side_layout.addWidget(QLabel("Interval"))
        side_layout.addWidget(self.interval_combo)
        side_layout.addStretch()

        side_widget = QWidget()
        side_widget.setLayout(side_layout)
        side_widget.setFixedWidth(70)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor, 1)
        layout.addWidget(side_widget)

        tab = QWidget()
        tab.setLayout(layout)

        return tab
    
    def start_step_hold(self, action):
        self.step_hold_action = action
        self.step_repeat_mode = False

        action()

        if self.step_hold_action is None:
            return

        # 300ms後にリピート開始判定
        self.step_hold_timer.start(300)

    def stop_step_hold(self):
        self.step_hold_timer.stop()
        self.step_hold_action = None
        self.step_repeat_mode = False

    def _on_step_hold_timer(self):
        if self.step_hold_action is None:
            return

        if not self.step_repeat_mode:
            self.step_repeat_mode = True

            interval_ms = int(self.get_interval_sec() * 1000)
            self.step_hold_timer.start(interval_ms)
            return

        self.step_hold_action()

    def create_digital_twin_tab(self):
        self.ip_edit = QLineEdit()
        self.ip_edit.setText("127.0.0.1")
        self.port_edit = QLineEdit()
        self.port_edit.setText("8193")
        
        self.connect_toggle_button = QPushButton("Connect")
        self.sync_toggle_button = QPushButton("Start Sync")
        self.connect_toggle_button.setFixedWidth(100)
        self.sync_toggle_button.setFixedWidth(100)

        self.connect_toggle_button.clicked.connect(
            self.toggle_machine_connection
        )
        self.sync_toggle_button.clicked.connect(
            self.toggle_machine_sync
        )
        self.sync_toggle_button.setEnabled(False)

        self.machine_interval_combo = QComboBox()
        self.machine_interval_combo.addItems([
            "10 ms",
            "50 ms",
            "100 ms",
            "200 ms",
            "500 ms",
            "1000 ms",
        ])
        self.machine_interval_combo.setCurrentText("200 ms")

        self.connection_status_label = QLabel("Disconnected")
        self.machine_status_label = QLabel("Idle")
        self.machine_axis_info = []

        layout = QVBoxLayout()
        layout.setContentsMargins(5,0,2,0)
        layout.setSpacing(2)

        self.ip_edit.setMinimumWidth(95)
        self.port_edit.setFixedWidth(45)
        network_layout = QHBoxLayout()
        network_layout.addWidget(QLabel("IP"))
        network_layout.addWidget(self.ip_edit)
        network_layout.addWidget(QLabel("Port"))
        network_layout.addWidget(self.port_edit)
        network_layout.addStretch()
        network_layout.addWidget(self.connect_toggle_button)
        layout.addLayout(network_layout)
        layout.addSpacing(4)

        polling_layout = QHBoxLayout()
        polling_layout.addWidget(QLabel("Polling Interval: "))
        polling_layout.addStretch()
        polling_layout.addWidget(self.machine_interval_combo)
        polling_layout.addStretch()
        polling_layout.addWidget(self.sync_toggle_button)
        layout.addLayout(polling_layout)
        layout.addSpacing(4)

        status_layout = QHBoxLayout()
        status_layout.addStretch()
        status_layout.addSpacing(8)
        status_layout.addWidget(self.connection_status_label)
        status_layout.addSpacing(16)
        status_layout.addWidget(self.machine_status_label)
        layout.addLayout(status_layout)
        layout.addSpacing(4)

        self.axis_table = QTableWidget()
        self.axis_table.setColumnCount(4)
        self.axis_table.setHorizontalHeaderLabels(
            ["Name", "Type", "Path", "No/Signal"]
        )

        self.axis_table.verticalHeader().setVisible(False)
        self.axis_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.axis_table.setSelectionMode(QTableWidget.NoSelection)
        self.axis_table.setAlternatingRowColors(True)

        self.axis_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.Stretch
        )
        self.axis_table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.axis_table)

        tab = QWidget()
        tab.setLayout(layout)

        return tab
    
    def is_machine_connected(self):
        return self.connection_status_label.text() == "Connected"

    def toggle_machine_connection(self):
        if self.is_machine_connected():
            self.disconnect_machine()
        else:
            self.connect_machine()

    def toggle_machine_sync(self):
        if self.machine_timer.isActive():
            self.stop_machine_sync()
        else:
            self.start_machine_sync()
            
    def on_tab_changed(self, index):
        if index != 0:
            self.stop()
        if index != 1 and self.is_machine_connected():
            self.disconnect_machine()
    
    def get_machine_interval_ms(self):
        text = self.machine_interval_combo.currentText()
        return int(text.replace(" ms", ""))

    def connect_machine(self):
        ip_address = self.ip_edit.text().strip()

        if not ip_address:
            self.connection_status_label.setText("Invalid IP")
            return

        # TODO:
        # FOCAS NC接続

        self.connection_status_label.setText("Connected")
        self.connect_toggle_button.setText("Disconnect")
        self.sync_toggle_button.setEnabled(True)
        self.ip_edit.setEnabled(False)
        self.port_edit.setEnabled(False)

    def disconnect_machine(self):
        self.stop_machine_sync()

        # TODO:
        # FOCAS NC接続切断

        self.connection_status_label.setText("Disconnected")
        self.connect_toggle_button.setText("Connect")
        self.sync_toggle_button.setEnabled(False)
        self.ip_edit.setEnabled(True)
        self.port_edit.setEnabled(True)

    def start_machine_sync(self):
        if not self.is_machine_connected():
            self.machine_status_label.setText("Not Connected")
            return

        self.stop()

        interval_ms = self.get_machine_interval_ms()
        self.machine_timer.start(interval_ms)

        self.machine_status_label.setText("Syncing")
        self.sync_toggle_button.setText("Stop Sync")
        self.machine_interval_combo.setEnabled(False)

    def stop_machine_sync(self):
        self.machine_timer.stop()
        self.machine_status_label.setText("Idle")
        self.sync_toggle_button.setText("Start Sync")
        self.machine_interval_combo.setEnabled(True)

    def poll_machine(self):
        position = {}
        try:
            for axis_info in self.machine_axis_info:
                name = axis_info["name"]
                joint_type = axis_info["type"]
                path = axis_info["path"]
                axisno = axis_info["axisno"]
                signal = axis_info["signal"]

                if joint_type == "signal":
                    value = self.read_machine_signal(signal)
                else:
                    value = self.read_machine_axis_position(path, axisno)

                position[name] = value

            self.send_position(position)

        except Exception as e:
            self.machine_status_label.setText(
                f"Read Error: {e}"
            )
            self.stop_machine_sync()

    def read_machine_axis_position(self, path, axisno):
        if path is None or axisno is None:
            return 0.0

        # TODO:
        # FOCASなどでNC座標を読む
        #
        # 例:
        # value = self.focas_client.read_axis_position(
        #     path=path,
        #     axisno=axisno
        # )
        #
        # return value

        print(
            f"Read Axis: path={path}, axisno={axisno}"
        )

        return 0.0
    
    def read_machine_signal(self, signal):
        if signal is None:
            return 0.0

        # TODO:
        # FOCAS PMCなどで信号を読む
        #
        # 例:
        # value = self.focas_client.read_signal(signal)
        #
        # return 1.0 if value else 0.0

        print(
            f"Read Signal: signal={signal}"
        )

        return 0.0

    def update_axis_info(self, joint_info_list):
        self.axis_table.setRowCount(0)
        self.machine_axis_info = []

        if not joint_info_list:
            return

        row_index = 0
        for joint in joint_info_list:
            node = joint.get("node")

            if node is None or node.joint is None:
                continue

            joint_def = node.joint

            name = joint.get("name", "")
            joint_type = getattr(joint_def, "type", "")

            path = getattr(joint_def, "path", None)
            axisno = getattr(joint_def, "axisno", None)
            signal = getattr(joint_def, "signal", None)

            if path is None:
                path = "-"

            if joint_type == "signal":
                target_info = signal if signal is not None else "-"
            else:
                target_info = axisno if axisno is not None else "-"
            
            self.machine_axis_info.append({
                "name": name,
                "type": joint_type,
                "path": path,
                "axisno": axisno,
                "signal": signal,
            })

            self.axis_table.insertRow(row_index)
            self.axis_table.setItem(row_index, 0, QTableWidgetItem(str(name)) )
            self.axis_table.setItem(row_index, 1, QTableWidgetItem(str(joint_type)))
            self.axis_table.setItem(row_index, 2, QTableWidgetItem(str(path)))
            self.axis_table.setItem(row_index, 3, QTableWidgetItem(str(target_info)))
            row_index += 1
                
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

    def prepare_program_samples(self):
        if self.samples:
            return None

        (
            samples,
            normalized_text,
            parse_error,
        ) = self.parse_program()

        self.editor.replace_program_text(normalized_text)

        if parse_error is not None:
            self.samples = []
            self.sample_index = 0
            return parse_error

        self.samples = samples
        self.sample_index = 0

        if not self.samples:
            return None

        self.interval_combo.setEnabled(False)

        return None

    def format_program_value(self, value: float) -> str:
        if math.isfinite(value) and value.is_integer():
            return str(int(value))

        return format(value, ".12g")

    def parse_program(self):
        interval_sec = self.get_interval_sec()

        axis_name_map, signal_names = self.get_program_axis_info()

        current = {}
        current_feed = 1000.0  # mm/min
        samples = []

        source_lines = self.get_program_text().splitlines()
        normalized_lines = []
        first_error = None

        for line_index, source_line in enumerate(source_lines):
            line = source_line .strip()

            if not line:
                normalized_lines.append("")
                continue
            
            try:
                line_upper = line.upper()
                if line_upper.startswith("WAIT"):
                    wait_text = line[4:].strip()

                    if not wait_text:
                        raise ValueError(
                            "WAIT requires exactly one value"
                        )

                    if not re.fullmatch(
                        self.NUMBER_PATTERN,
                        wait_text,
                    ):
                        raise ValueError(
                            f"Invalid WAIT value: {wait_text}"
                        )

                    wait_sec = float(wait_text)

                    if not math.isfinite(wait_sec):
                        raise ValueError(
                            "WAIT value must be finite"
                        )

                    if wait_sec < 0:
                        raise ValueError(
                            "WAIT value must not be negative"
                        )

                    normalized_lines.append(
                        f"WAIT {self.format_program_value(wait_sec)}"
                    )

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
                    normalized_name = parts[0].upper()

                    actual_name = axis_name_map.get(normalized_name)

                    if actual_name is None:
                        raise ValueError(
                            f"Unknown signal: {parts[0]}"
                        )

                    if normalized_name not in signal_names:
                        raise ValueError(
                            f"Axis is not a signal: {actual_name}"
                        )

                    signal_value = (
                        1.0
                        if parts[1].upper() == "ON"
                        else 0.0
                    )

                    current[actual_name] = signal_value

                    samples.append({
                        "position": current.copy(),
                        "line_index": line_index,
                    })

                    normalized_lines.append(f"{actual_name} {parts[1].upper()}")

                    continue
                
                normalized_words = []
                for part in parts:
                    word_type, key, value = self.parse_program_word(
                        part,
                        axis_name_map,
                    )

                    value_text = self.format_program_value(
                        value
                    )

                    if word_type == "feed":
                        feed = value

                        normalized_words.append(
                            f"F{value_text}"
                        )
                    else:
                        target[key] = value

                        if key not in current:
                            current[key] = 0.0

                        normalized_words.append(
                            f"{key}={value_text}"
                        )
                normalized_line = " ".join(
                    normalized_words
                )

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

                    normalized_lines.append(
                        normalized_line
                    )
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

                normalized_lines.append(normalized_line)

            except ProgramParseError:
                raise

            except (ValueError, IndexError) as e:
                first_error = ProgramParseError(line_index, str(e))

                normalized_lines.extend(source_lines[line_index:])
                break

        normalized_text = "\n".join(
            normalized_lines
        )

        return samples, normalized_text, first_error
    
    def play(self):
        if self.program_state == ProgramState.RUNNING:
            return
            
        self.editor.clear_line_highlight()

        try:
            parse_error = self.prepare_program_samples()
            if parse_error is not None:
                self.editor.highlight_error_line(
                    parse_error.line_index
                )
                print(f"Program error: {parse_error}")
                return
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
        self.program_state = ProgramState.RUNNING
        self.update_button_state()
    
    def stop(self):
        self.timer.stop()
        self.stop_step_hold()
        self.samples = []
        self.sample_index = 0

        self.interval_combo.setEnabled(True)

        self.program_state = ProgramState.STOPPED
        self.update_button_state()

        self.editor.highlight_program_line(None)
        self.set_program_editable(True)
    
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

        try:
            parse_error = self.prepare_program_samples()

            if parse_error is not None:
                self.editor.highlight_error_line(
                    parse_error.line_index
                )
                print(f"Program error: {parse_error}")
                self.stop_step_hold()
                return

        except ValueError as e:
            print(f"Program error: {e}")
            self.stop_step_hold()
            return


        if self.sample_index >= len(self.samples):
            return

        self.set_program_editable(False)
        sample_info = self.samples[self.sample_index]

        self.editor.highlight_program_line(sample_info["line_index"])
        self.send_position(sample_info["position"])

        self.sample_index += 1
        self.program_state = ProgramState.PAUSED
        self.update_button_state()

    def step_back(self):
        self.pause_playback()

        try:
            parse_error = self.prepare_program_samples()

            if parse_error is not None:
                self.editor.highlight_error_line(
                    parse_error.line_index
                )
                print(f"Program error: {parse_error}")
                self.stop_step_hold()
                return

        except ValueError as e:
            print(f"Program error: {e}")
            self.stop_step_hold()
            return

        if not self.samples:
            return

        self.set_program_editable(False)
        self.sample_index = max(0, self.sample_index - 2)

        sample_info = self.samples[self.sample_index]

        self.editor.highlight_program_line(
            sample_info["line_index"]
        )

        self.send_position(
            sample_info["position"]
        )

        self.sample_index += 1
        self.program_state = ProgramState.PAUSED
        self.update_button_state()

    def pause_playback(self):
        if self.timer.isActive():
            self.timer.stop()
        
        if self.samples:
            self.program_state = ProgramState.PAUSED
        else:
            self.program_state = ProgramState.STOPPED

        self.update_button_state()

    def set_program_editable(self, editable: bool):
        self.editor.setReadOnly(not editable)
        if editable:
            self.editor.highlight_current_line()
    
    def on_interval_changed(self, index):
        self.stop()

    def get_program_axis_info(self):
        axis_name_map = {}
        signal_names = set()

        for axis_info in self.machine_axis_info:
            name = str(axis_info.get("name", "")).strip()

            if not name:
                continue

            normalized_name = name.upper()

            if normalized_name in axis_name_map:
                raise ValueError(
                    f"Duplicate axis name: {name}"
                )

            axis_name_map[normalized_name] = name

            if axis_info.get("type") == "signal":
                signal_names.add(normalized_name)

        return axis_name_map, signal_names

    def parse_program_word(self, word, axis_name_map):
        word = word.strip()

        if not word:
            raise ValueError("Empty program word")

        # 推奨形式:
        # X=100
        # WH1=-30
        if "=" in word:
            name_text, value_text = word.split("=", 1)

            normalized_name = name_text.upper()

            if not re.fullmatch(
                self.NUMBER_PATTERN,
                value_text,
            ):
                raise ValueError(
                    f"Invalid value: {word}"
                )

            if normalized_name == "F":
                return "feed", "F", float(value_text)

            actual_name = axis_name_map.get(normalized_name)

            if actual_name is None:
                raise ValueError(
                    f"Unknown axis: {name_text}"
                )

            return "axis", actual_name, float(value_text)

        word_upper = word.upper()

        # F600
        if word_upper.startswith("F"):
            value_text = word[1:]

            if re.fullmatch(
                self.NUMBER_PATTERN,
                value_text,
            ):
                return "feed", "F", float(value_text)

        # 長い軸名から照合する。
        # WH1とWHがある場合にWH1を先に判定する。
        sorted_axis_names = sorted(
            axis_name_map.keys(),
            key=len,
            reverse=True,
        )

        for normalized_name in sorted_axis_names:
            if not word_upper.startswith(normalized_name):
                continue

            value_text = word[len(normalized_name):]

            if not value_text:
                continue

            if not re.fullmatch(
                self.NUMBER_PATTERN,
                value_text,
            ):
                continue

            actual_name = axis_name_map[normalized_name]

            return "axis", actual_name, float(value_text)

        raise ValueError(
            f"Invalid or unknown word: {word}"
        )

    def update_button_state(self):
        if self.program_state == ProgramState.RUNNING:
            # 実行中：緑
            self.play_button.setStyleSheet(
                """
                QPushButton {
                    background-color: #2E7D32;
                    color: white;
                    border: 1px solid #4CAF50;
                    border-radius: 3px;
                    font-weight: bold;
                }

                QPushButton:hover {
                    background-color: #388E3C;
                }

                QPushButton:pressed {
                    background-color: #1B5E20;
                }

                QPushButton:disabled {
                    background-color: #355E38;
                    color: #BDBDBD;
                    border-color: #48784C;
                }
                """
            )

        elif self.program_state == ProgramState.PAUSED:
            # 一時停止中：黄色
            self.play_button.setStyleSheet(
                """
                QPushButton {
                    background-color: #C49000;
                    color: black;
                    border: 1px solid #FFD54F;
                    border-radius: 3px;
                    font-weight: bold;
                }

                QPushButton:hover {
                    background-color: #D9A600;
                }

                QPushButton:pressed {
                    background-color: #A67C00;
                }

                QPushButton:disabled {
                    background-color: #7A651F;
                    color: #BDBDBD;
                    border-color: #927D32;
                }
                """
            )

        else:
            # 停止中：共通テーマの通常色へ戻す
            self.play_button.setStyleSheet("")

if __name__ == "__main__":
    app = QApplication([])

    window = MachinePanelQt()
    window.show()

    app.exec()