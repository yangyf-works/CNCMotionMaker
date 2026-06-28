from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QHBoxLayout,
)


class TitleBar(QWidget):
    def __init__(self, parent, title_text, show_close=False,):
        super().__init__(parent)

        self.parent_window = parent
        self._drag_start_pos = None

        self.setObjectName("TitleBar")
        self.setFixedHeight(28)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

        self.title_label = QLabel(title_text)

        layout.addWidget(self.title_label)
        if show_close:
            self.close_button = QPushButton("✕")
            self.close_button.setObjectName("CloseButton")
            self.close_button.setFixedSize(30, 30)
            self.close_button.clicked.connect(parent.close)

            layout.addStretch()
            layout.addWidget(self.close_button)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = (
                event.globalPosition().toPoint()
                - self.parent_window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.LeftButton
            and self._drag_start_pos is not None
        ):
            self.parent_window.move(
                event.globalPosition().toPoint()
                - self._drag_start_pos
            )
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        event.accept()

def apply_common_dark_theme(widget):
    widget.setStyleSheet(COMMON_DARK_STYLE)


COMMON_DARK_STYLE = """
            QTableWidget {
                background-color: #1e1e1e;
                color: white;
                gridline-color: #555555;
                border: 1px solid #555555;
                alternate-background-color: #2a2a2a;
            }

            QHeaderView::section {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #666666;
                padding: 1px;
            }

            QTableWidget::item {
                padding: 1px;
            }
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
            QFrame[frameShape="4"],   /* HLine */
            QFrame[frameShape="5"] {  /* VLine */
                color: #555555;
            }
            QCheckBox {
                spacing: 6px;
            }

            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #777777;
                background-color: #1e1e1e;
            }

            QCheckBox::indicator:hover {
                border: 1px solid #00d0ff;
            }

            QCheckBox::indicator:checked {
                background-color: #2d8cff;
                border: 1px solid #7fc7ff;
            }

            QCheckBox::indicator:checked:hover {
                background-color: #6aa0ff;
            }
        """