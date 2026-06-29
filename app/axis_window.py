from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QFrame
)
from PySide6.QtCore import Qt, QTimer
from app.qt_style import apply_common_dark_theme, TitleBar

override_items = [
    ("x0.0001", 0.0001),
    ("x0.001", 0.001),
    ("x0.01", 0.01),
    ("x0.1", 0.1),
    ("x1", 1.0),
    ("x10", 10.0),
    ("x100", 100.0),
]

class AxisControlWindowQt(QWidget):
    def __init__(self, on_joint_move):
        super().__init__()

        self.on_joint_move = on_joint_move
        self._setting_axis_info = False

        self.jog_override_index = 4
        self.jog_override = override_items[self.jog_override_index][1]

        self.motion_joints = []
        self.signal_joints = []
        self.motion_axis_rows = []
        self.signal_axis_rows = []
        self.button_size = 20

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.resize(300, 720)
        
        self.setWindowTitle("Joint Panel")
        self.setWindowFlags(Qt.WindowType.Tool |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint)

        self.content_widget = QWidget()
        self.create_content_ui(self.content_widget)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.content_widget)

        self.jog_timer = QTimer(self)
        self.jog_timer.timeout.connect(self._repeat_jog)
        self._repeat_joint = None
        self._repeat_row = None
        self._repeat_amount = 0.0

        apply_common_dark_theme(self)
    
    def create_content_ui(self, parent):
        root_layout = QHBoxLayout(parent)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(4)

        self.motion_panel = QWidget()
        self.motion_layout = QVBoxLayout(self.motion_panel)
        self.motion_layout.setContentsMargins(0, 0, 0, 0)
        self.motion_layout.setSpacing(5)

        self.signal_panel = QWidget()
        self.signal_layout = QVBoxLayout(self.signal_panel)
        self.signal_layout.setContentsMargins(0, 0, 0, 0)
        self.signal_layout.setSpacing(5)

        self._build_motion_panel_header()
        self._build_signal_panel_header()
        self.motion_layout.addStretch()
        self.signal_layout.addStretch()

        root_layout.addWidget(self.motion_panel, 1)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setLineWidth(1)
        root_layout.addWidget(separator)
        root_layout.addWidget(self.signal_panel, 1)

    def _build_motion_panel_header(self):
        self.motion_layout.addWidget(QLabel("[Motion Axis]"))

        override_row = QHBoxLayout()
        override_row.setContentsMargins(0, 0, 0, 0)
        override_row.setSpacing(2)
        override_row.addWidget(QLabel("Override"))

        self.override_combo = QComboBox()
        for text, value in override_items:
            self.override_combo.addItem(text)

        self.override_combo.setCurrentIndex(self.jog_override_index)
        self.override_combo.currentIndexChanged.connect(
            self._on_override_changed
        )

        self.override_minus_btn = QPushButton("-")
        self.override_plus_btn = QPushButton("+")
        self.override_minus_btn.setFixedSize(self.button_size, self.button_size)
        self.override_plus_btn.setFixedSize(self.button_size, self.button_size)

        self.override_minus_btn.clicked.connect(self._on_override_minus)
        self.override_plus_btn.clicked.connect(self._on_override_plus)

        override_row.addWidget(self.override_combo)
        override_row.addStretch()
        override_row.addWidget(self.override_minus_btn)
        override_row.addWidget(self.override_plus_btn)
        self.motion_layout.addLayout(override_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        self.motion_layout.addWidget(separator)

    def _build_signal_panel_header(self):
        self.signal_layout.addWidget(QLabel("[Signal]"))
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        self.signal_layout.addWidget(separator)

    def set_axis_info(self, joint_info_list):
        self._setting_axis_info = True

        signal_joints = []
        motion_joints = []

        for joint in joint_info_list:
            node = joint.get("node")

            if node is None or node.joint is None:
                continue

            joint_def = node.joint
            joint_type = getattr(joint_def, "type", "")

            if joint_type == "signal":
                signal_joints.append(joint)
            else:
                motion_joints.append(joint)

        try:
            self.set_motion_axis_info(motion_joints)
            self.set_signal_axis_info(signal_joints)
        finally:
            self._setting_axis_info = False

    def set_motion_axis_info(self, joint_info_list):
        while len(self.motion_axis_rows) < len(joint_info_list):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)

            name_label = QLabel("")
            name_label.setFixedWidth(28)
            name_label.setAlignment(Qt.AlignLeft  | Qt.AlignVCenter)

            value_edit = QLineEdit()
            value_edit.setAlignment(Qt.AlignRight)
            value_edit.setFixedWidth(80)
            value_edit.setText(self._value_format(0))

            minus_btn = QPushButton("-")
            plus_btn = QPushButton("+")
            minus_btn.setFixedSize(self.button_size, self.button_size)
            plus_btn.setFixedSize(self.button_size, self.button_size)

            row_dict = {
                "row": row_widget,
                "label": name_label,
                "value": value_edit,
                "minus": minus_btn,
                "plus": plus_btn,
                "joint": None,
                "connected": False,
            }

            value_edit.editingFinished.connect(
                lambda row=row_dict:
                    self._apply_value_text(
                        row,
                        row["value"].text()
                    )
            )

            row_layout.addWidget(name_label)
            row_layout.addStretch()
            row_layout.addWidget(value_edit)
            row_layout.addWidget(minus_btn)
            row_layout.addWidget(plus_btn)

            row_widget.setVisible(False)
            insert_index = self.motion_layout.count() - 1
            self.motion_layout.insertWidget(insert_index, row_widget)
            self.motion_axis_rows.append(row_dict)

        name_counts = {}

        for r in self.motion_axis_rows:
            r["row"].setVisible(False)
            r["joint"] = None

        for i, joint in enumerate(joint_info_list):
            r = self.motion_axis_rows[i]

            r["joint"] = joint

            base_name = joint.get("name", "")
            count = name_counts.get(base_name, 0)
            name_counts[base_name] = count + 1

            display_name = base_name if count == 0 else f"{base_name}{count}"

            r["label"].setText(display_name)

            node = joint.get("node")
            if node is None:
                continue

            current_value = node.joint_value

            r["value"].setText(self._value_format(current_value))
            r["row"].setVisible(True)

            if r["connected"]:
                r["minus"].pressed.disconnect()
                r["minus"].released.disconnect()
                r["plus"].pressed.disconnect()
                r["plus"].released.disconnect()

            r["minus"].pressed.connect(
                lambda j=joint, row=r:
                    self._start_repeat_jog(
                        j,
                        row,
                        -self.jog_override
                    )
            )

            r["minus"].released.connect(
                self._stop_repeat_jog
            )

            r["plus"].pressed.connect(
                lambda j=joint, row=r:
                    self._start_repeat_jog(
                        j,
                        row,
                        self.jog_override
                    )
            )

            r["plus"].released.connect(
                self._stop_repeat_jog
            )

            r["connected"] = True

    def _start_repeat_jog(self, joint, row, amount):
        self._repeat_joint = joint
        self._repeat_row = row
        self._repeat_amount = amount

        # 押した瞬間に1回実行
        self._move_joint(joint, row, amount)

        # 長押し判定まで少し待つ
        self.jog_timer.start(300)


    def _repeat_jog(self):
        if self._repeat_joint is None:
            return

        self._move_joint(
            self._repeat_joint,
            self._repeat_row,
            self._repeat_amount
        )

        # 2回目以降は速くする
        if self.jog_timer.interval() != 100:
            self.jog_timer.start(100)

    def _stop_repeat_jog(self):
        self.jog_timer.stop()

        self._repeat_joint = None
        self._repeat_row = None
        self._repeat_amount = 0.0

    def set_signal_axis_info(self, joint_info_list):
        while len(self.signal_axis_rows) < len(joint_info_list):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            name_label = QLabel("")
            signal_check = QCheckBox("")

            row_dict = {
                "row": row_widget,
                "label": name_label,
                "check": signal_check,
                "joint": None,
                "connected": False,
            }

            row_layout.addWidget(name_label)
            row_layout.addStretch()
            row_layout.addWidget(signal_check)

            row_widget.setVisible(False)
            insert_index = self.signal_layout.count() - 1
            self.signal_layout.insertWidget(insert_index, row_widget)
            self.signal_axis_rows.append(row_dict)

        name_counts = {}

        for r in self.signal_axis_rows:
            r["row"].setVisible(False)
            r["joint"] = None

        for i, joint in enumerate(joint_info_list):
            r = self.signal_axis_rows[i]

            r["joint"] = joint

            base_name = joint.get("name", "")
            count = name_counts.get(base_name, 0)
            name_counts[base_name] = count + 1

            display_name = base_name if count == 0 else f"{base_name}{count}"

            r["label"].setText(display_name)

            node = joint.get("node")
            if node is None:
                continue

            r["check"].blockSignals(True)
            r["check"].setChecked(bool(node.joint_value))
            r["check"].blockSignals(False)

            r["row"].setVisible(True)

            if r["connected"]:
                r["check"].toggled.disconnect()
            r["check"].toggled.connect(
                lambda checked, j=joint:
                    self._signal_changed(j, checked)
            )
            r["connected"] = True

    def _apply_value_text(self, row, text):
        if self._setting_axis_info:
            return

        joint = row["joint"]

        if joint is None:
            return

        try:
            target_value = float(text.strip())
        except ValueError:
            self._restore_current_value(row)
            return

        current_value = joint["node"].joint_value
        amount = target_value - current_value

        self.on_joint_move(joint, amount)
        self._restore_current_value(row)

    def _restore_current_value(self, row):
        joint = row.get("joint")
        if joint is None:
            return

        node = joint.get("node")
        if node is None:
            return

        row["value"].setText(
            self._value_format(node.joint_value)
        )

    def _move_joint(self, joint, row, amount):
        self.on_joint_move(joint, amount)

        current_value = joint["node"].joint_value
        row["value"].setText(
            self._value_format(current_value)
        )

    def _signal_changed(self, joint, checked):
        if self._setting_axis_info:
            return

        node = joint.get("node")
        if node is None:
            return

        target_value = 1.0 if checked else 0.0
        current_value = 1.0 if bool(node.joint_value) else 0.0
        amount = target_value - current_value
        if amount == 0:
            return
        self.on_joint_move(joint, amount)

    def _set_override_index(self, index):
        index = max(0, min(index, len(override_items) - 1))

        self.jog_override_index = index
        self.jog_override = override_items[index][1]

        self.override_combo.blockSignals(True)
        self.override_combo.setCurrentIndex(index)
        self.override_combo.blockSignals(False)

    def _on_override_changed(self, index):
        self._set_override_index(index)

    def _on_override_minus(self):
        self._set_override_index(
            self.jog_override_index - 1
        )

    def _on_override_plus(self):
        self._set_override_index(
            self.jog_override_index + 1
        )

    def refresh_axis_values(self):
        if self._setting_axis_info:
            return

        self._setting_axis_info = True
        try:
            for r in self.motion_axis_rows:
                joint = r.get("joint")
                if joint is None:
                    continue

                node = joint.get("node")
                if node is None:
                    continue

                r["value"].setText(
                    self._value_format(node.joint_value)
                )

            for r in self.signal_axis_rows:
                joint = r.get("joint")
                if joint is None:
                    continue

                node = joint.get("node")
                if node is None:
                    continue

                r["check"].blockSignals(True)
                r["check"].setChecked(bool(node.joint_value))
                r["check"].blockSignals(False)

        finally:
            self._setting_axis_info = False

    def _value_format(self, value):
        return f"{value:.4f}"