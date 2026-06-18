import sys
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
import open3d.visualization.gui as gui # type: ignore


def main():
    qt_app = QApplication.instance()

    if qt_app is None:
        qt_app = QApplication(sys.argv)

    gui.Application.instance.initialize()

    MainWindow()

    gui.Application.instance.run()


if __name__ == "__main__":
    main()