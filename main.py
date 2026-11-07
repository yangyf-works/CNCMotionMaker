import sys
from pathlib import Path

import open3d.visualization.gui as gui  # type: ignore
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.qt_style import apply_common_dark_theme


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

def main():
    qt_app = QApplication.instance()

    if qt_app is None:
        qt_app = QApplication(sys.argv)

    apply_common_dark_theme(qt_app)

    # Tool windows must not terminate Qt while the main window is being built.
    qt_app.setQuitOnLastWindowClosed(False)
    window = None
    try:
        gui.Application.instance.initialize()
        window = MainWindow(root_path=get_app_root(), json_dir=get_JSON_path())
        qt_app.aboutToQuit.connect(window.shutdown)
        window.start()
        return qt_app.exec()
    finally:
        if window is not None:
            window.shutdown()
        else:
            gui.Application.instance.quit()


if __name__ == "__main__":
    sys.exit(main())
