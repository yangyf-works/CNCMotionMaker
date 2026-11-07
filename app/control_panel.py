from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QWidget,
)


MANUAL_SCROLLBAR_GAP = 4


class ControlPanel(QWidget):
    BASE_EXPANDED_WIDTH = 160
    COLLAPSED_WIDTH = 24

    def __init__(self, json_dir: Path, on_json_selected, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet("""
            QWidget { background-color: #2d2d2d; color: #dfdfdf; font-size: 8pt; }
            QLabel#SidebarHeading { font-size: 9.75pt; font-weight: 600; }
            QPushButton#ToggleSidebar { background-color: #646464; padding: 4px 0; }
            QPushButton#ToggleSidebar:hover { background-color: #757575; }
            QSplitter::handle { background-color: #545454; }
            QSplitter::handle:hover { background-color: #707070; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 1, 5)
        layout.setSpacing(2)

        self.toggle_button = QPushButton(">>>")
        self.toggle_button.setObjectName("ToggleSidebar")
        self.toggle_button.setToolTip("Collapse right panel")
        self.toggle_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_button.clicked.connect(self._toggle_sidebar)
        layout.addWidget(self.toggle_button)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(5)
        self.splitter.setChildrenCollapsible(False)
        self.model_panel = ModelSelectionPanel(json_dir, on_json_selected)
        self.manual_panel = ManualPanel()
        self.splitter.addWidget(self.model_panel)
        self.splitter.addWidget(self.manual_panel)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)
        layout.addStretch()
        scrollbar_width = self.manual_panel.scroll.verticalScrollBar().sizeHint().width()
        self.expanded_width = self.BASE_EXPANDED_WIDTH + scrollbar_width + MANUAL_SCROLLBAR_GAP
        self.setFixedWidth(self.expanded_width)

    def _toggle_sidebar(self):
        expanded = self.splitter.isHidden()
        self.splitter.setVisible(expanded)
        self.toggle_button.setText(">>>" if expanded else "<")
        self.toggle_button.setToolTip("Collapse right panel" if expanded else "Expand right panel")
        self.setFixedWidth(self.expanded_width if expanded else self.COLLAPSED_WIDTH)


class ModelSelectionPanel(QWidget):
    def __init__(self, json_dir: Path, on_json_selected, parent=None):
        super().__init__(parent)
        self.on_json_selected = on_json_selected
        json_dir = Path(json_dir)
        json_dir.mkdir(parents=True, exist_ok=True)
        self.json_files = sorted(json_dir.glob("*.json"))
        self.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                color: #202020;
                border: 1px solid #a0a0a0;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                color: #202020;
                selection-background-color: #dcecff;
                selection-color: #202020;
            }
            QPushButton#LoadModel { background-color: #337fe6; color: white; }
            QPushButton#LoadModel:hover { background-color: #4592f2; }
            QPushButton#LoadModel:disabled { background-color: #555555; color: #aaaaaa; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 6, 6)
        layout.setSpacing(3)
        heading = QLabel("Model select")
        heading.setObjectName("SidebarHeading")
        layout.addWidget(heading)
        self.json_combo = QComboBox()
        self.json_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.json_combo.addItems([p.name for p in self.json_files] or ["(None JSON File)"])
        self.json_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for index, path in enumerate(self.json_files):
            self.json_combo.setItemData(index, path.name, Qt.ItemDataRole.ToolTipRole)
        self.json_combo.currentTextChanged.connect(self.json_combo.setToolTip)
        self.json_combo.setToolTip(self.json_combo.currentText())
        layout.addWidget(self.json_combo)
        self.load_button = QPushButton("Load Model")
        self.load_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.load_button.setObjectName("LoadModel")
        self.load_button.setEnabled(bool(self.json_files))
        self.load_button.clicked.connect(self._on_load_clicked)
        layout.addWidget(self.load_button)
        layout.addStretch()

    def _on_load_clicked(self):
        index = self.json_combo.currentIndex()
        if 0 <= index < len(self.json_files):
            self.on_json_selected(self.json_files[index])


class ManualPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget { background-color: #2d2d2d; color: #dfdfdf; }
            QToolButton#GuideHeader {
                background-color: #3b3b3b;
                border: 1px solid #565656;
                padding: 2px 4px;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QToolButton#GuideHeader:hover, QToolButton#GuideHeader:focus {
                background-color: #484848;
            }
            QWidget#GuideRows QLabel { padding: 1px 0; }
            QWidget#GuideRows QLabel#GuideDescription {
                border-left: 1px solid #545454;
                padding-left: 2px;
            }
            QFrame#GuideRowDivider { background-color: #545454; border: none; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(3)
        heading = QLabel("Manual")
        heading.setObjectName("SidebarHeading")
        layout.addWidget(heading)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, MANUAL_SCROLLBAR_GAP, 0)
        content_layout.setSpacing(3)

        for title, rows, expanded in (
            ("Camera", [
                ("Left drag\nArrow keys", "Orbit"),
                ("Right drag\nW/A/S/D", "Pan"),
                ("Wheel\nCtrl + ↑ / ↓", "Zoom in/out"),
                ("Q / E", "Roll"),
                ("Ctrl + ← / →", "FOV −/+"),
                ("Ctrl + C", "Reset view"),
            ], True),
            ("Lighting", [
                ("Middle drag\nAlt + drag", "Rotate light"),
                ("Ctrl + L", "Reset light"),
            ], False),
            ("Joints / Trace", [
                ("Ctrl + A", "Toggle joint axes"),
                ("Shift + left\ndouble-click", "Fix joint\nEmpty space clears"),
                ("Ctrl + left\ndouble-click", "Add marker"),
                ("Ctrl + R", "Clear manual markers"),
                ("Ctrl + T", "Toggle trace"),
            ], False),
            ("Export", [
                ("Ctrl + S", "Save export.stl"),
            ], False),
        ):
            self._add_manual_section(content_layout, title, rows, expanded)
        content_layout.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)

    def _add_manual_section(self, layout, title, rows, expanded):
        section = QVBoxLayout()
        section.setSpacing(2)
        header = QToolButton()
        header.setObjectName("GuideHeader")
        header.setText(title)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setCheckable(True)
        header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        section.addWidget(header)

        body = QWidget()
        body.setObjectName("GuideRows")
        grid = QGridLayout(body)
        grid.setContentsMargins(2, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(1, 1)
        for row, (operation, description) in enumerate(rows):
            grid_row = row * 2
            if row:
                divider = QFrame()
                divider.setObjectName("GuideRowDivider")
                divider.setFixedHeight(1)
                grid.addWidget(divider, grid_row - 1, 0, 1, 2)
            key_label = QLabel(operation)
            description_label = QLabel(description)
            description_label.setObjectName("GuideDescription")
            key_label.setWordWrap(True)
            description_label.setWordWrap(True)
            grid.addWidget(key_label, grid_row, 0)
            grid.addWidget(description_label, grid_row, 1)
        section.addWidget(body)
        layout.addLayout(section)

        def show_rows(visible):
            header.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
            body.setVisible(visible)

        header.setChecked(expanded)
        show_rows(expanded)
        header.toggled.connect(show_rows)

