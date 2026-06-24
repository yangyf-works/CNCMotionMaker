from __future__ import annotations
import math
from PySide6.QtCore import Qt, QRect, QSize, QTimer, QEvent
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFormLayout,
    QLineEdit,
    QGridLayout
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

class MachinePanelQt(QMainWindow):
    def __init__(self, on_position_sample=None, on_window_activated=None):
        super().__init__()
        self.on_position_sample = on_position_sample
        self.on_window_activated = on_window_activated

        self.setWindowTitle("Machine Panel")
        self.resize(300, 720)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
        )

        self.samples = []
        self.sample_index = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)

        self.machine_timer = QTimer(self)
        self.machine_timer.timeout.connect(self.poll_machine)

        self._drag_start_pos = None

        title_bar = self.create_title_bar("Machine Panel")

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

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(title_bar)
        main_layout.addWidget(self.tabs)

        root = QWidget()
        root.setLayout(main_layout)

        self.setCentralWidget(root)
        self.apply_dark_theme()

    def create_program_tab(self):
        self.editor = ProgramEditor()

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.step_forward_button = QPushButton("Next Step")
        self.step_back_button = QPushButton("Back Step")

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

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor, 1)
        layout.addWidget(side_widget)

        tab = QWidget()
        tab.setLayout(layout)

        return tab
    
    def create_digital_twin_tab(self):
        self.ip_edit = QLineEdit()
        self.ip_edit.setText("127.0.0.1")
        self.port_edit = QLineEdit()
        self.port_edit.setText("8193")
        
        IP_layout = QGridLayout()
        IP_layout.addWidget(QLabel("IP Address"),0 ,0)
        IP_layout.addWidget(self.ip_edit, 0, 1)
        IP_layout.addWidget(QLabel("Port"),0 ,2)
        IP_layout.addWidget(self.port_edit, 0, 3)
        

        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.start_sync_button = QPushButton("Start Sync")
        self.stop_sync_button = QPushButton("Stop Sync")

        self.connect_button.clicked.connect(self.connect_machine)
        self.disconnect_button.clicked.connect(self.disconnect_machine)
        self.start_sync_button.clicked.connect(self.start_machine_sync)
        self.stop_sync_button.clicked.connect(self.stop_machine_sync)

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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        layout.addLayout(IP_layout)

        connect_layout = QHBoxLayout()
        left_layout = QHBoxLayout()
        center_layout = QHBoxLayout()
        right_layout = QHBoxLayout()
        left_layout.addWidget(self.connect_button)
        center_layout.addWidget(self.disconnect_button)
        right_layout.addStretch()
        right_layout.addWidget(self.connection_status_label)
        connect_layout.addLayout(left_layout, 1)
        connect_layout.addLayout(center_layout, 1)
        connect_layout.addLayout(right_layout, 1)

        layout.addLayout(connect_layout)

        sync_layout = QHBoxLayout()
        left_layout = QHBoxLayout()
        center_layout = QHBoxLayout()
        right_layout = QHBoxLayout()
        left_layout.addWidget(self.start_sync_button)
        center_layout.addWidget(self.stop_sync_button)
        right_layout.addStretch()
        right_layout.addWidget(self.machine_status_label)
        sync_layout.addLayout(left_layout, 1)
        sync_layout.addLayout(center_layout, 1)
        sync_layout.addLayout(right_layout, 1)
        layout.addLayout(sync_layout)

        layout.addSpacing(8)
        polling_layout = QHBoxLayout()
        polling_layout.addWidget(QLabel("Polling Interval"))
        polling_layout.addWidget(self.machine_interval_combo)
        layout.addLayout(polling_layout)

        layout.addSpacing(8)
        self.axis_table = QTableWidget()
        self.axis_table.setColumnCount(4)
        self.axis_table.setHorizontalHeaderLabels(
            ["Name", "Type", "Path", "AxisNo / Signal"]
        )

        self.axis_table.verticalHeader().setVisible(False)
        self.axis_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.axis_table.setSelectionMode(QTableWidget.NoSelection)
        self.axis_table.setAlternatingRowColors(True)

        self.axis_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.axis_table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(QLabel("Axis Info"))
        layout.addWidget(self.axis_table)

        tab = QWidget()
        tab.setLayout(layout)

        return tab
    
    def on_tab_changed(self, index):
        self.stop()
        self.stop_machine_sync()
    
    def get_machine_interval_ms(self):
        text = self.machine_interval_combo.currentText()
        return int(text.replace(" ms", ""))

    def connect_machine(self):
        self.connection_status_label.setText("Connected")
        ip_address = self.ip_edit.text().strip()

        if not ip_address:
            self.connection_status_label.setText("Invalid IP")
            return
        # TODO:
        # FOCAS NC接続

    def disconnect_machine(self):
        # TODO:
        # FOCAS NC接続切断
        self.stop_machine_sync()
        self.connection_status_label.setText("Disconnected")

    def start_machine_sync(self):
        self.stop()
        interval_ms = self.get_machine_interval_ms()
        self.machine_timer.start(interval_ms)
        self.machine_status_label.setText("Syncing")

    def stop_machine_sync(self):
        self.machine_timer.stop()
        self.machine_status_label.setText("Idle")

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
                
    def create_title_bar(self, title_text):
        title_bar = QWidget()
        title_bar.setObjectName("TitleBar")
        title_bar.setFixedHeight(28)

        layout = QHBoxLayout()
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel(title_text)

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
           QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #232323;
            }

            QTabBar::tab {
                background-color: #303030;
                color: #aaaaaa;
                padding: 2px 0px;
                border: 1px solid #555555;
                border-bottom: none;
                min-width: 100px;
            }

            QTabBar::tab:selected {
                background-color: #2d4b55;
                color: white;
                border-top: 2px solid #00d0ff;
            }

            QTabBar::tab:hover {
                background-color: #0078d7;
                color: white;
            }

            QTabBar::tab:!selected {
                margin-top: 3px;
            }
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

    window = MachinePanelQt()
    window.show()

    app.exec()