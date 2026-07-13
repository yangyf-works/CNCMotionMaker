import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QInputDialog
from PySide6.QtGui import QIcon

from app.main_window import MainWindow
import open3d.visualization.gui as gui  # type: ignore

from app.qt_style import apply_common_dark_theme, TitleBar

def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).resolve().parent

def get_JSON_path():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).parent / "JSON"
    else:
        return get_app_root() / "JSON"

def ask_view_count():
    dialog = QInputDialog()
    dialog.setWindowTitle("CNCMotionMaker")
    dialog.setLabelText("Open3D Views:")
    dialog.setInputMode(QInputDialog.IntInput)

    dialog.setIntRange(1, 4)
    dialog.setIntValue(1)
    dialog.setIntStep(1)

    icon_path = (
        get_app_root() /
        "assets" /
        "icon.ico"
    )
    dialog.setWindowIcon(QIcon(str(icon_path)))

    if dialog.exec():
        return dialog.intValue()

    return None


def main():
    qt_app = QApplication.instance()

    if qt_app is None:
        qt_app = QApplication(sys.argv)

    apply_common_dark_theme(qt_app)
    view_count = ask_view_count()

    if view_count is None:
        return

    gui.Application.instance.initialize()

    MainWindow(view_count=view_count, 
               root_path = get_app_root(), 
               json_dir = get_JSON_path())

    gui.Application.instance.run()


if __name__ == "__main__":
    main()