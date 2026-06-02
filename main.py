from app.main_window import MainWindow
import open3d.visualization.gui as gui # type: ignore


def main():

    gui.Application.instance.initialize()

    MainWindow()

    gui.Application.instance.run()


if __name__ == "__main__":
    main()