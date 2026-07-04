from pathlib import Path
import traceback
import open3d.visualization.gui as gui # type: ignore

from app.scene_view import SceneView
from app.control_panel import ControlPanel
from app.axis_window import AxisControlWindowQt
from app.program_window_qt import MachinePanelQt
from app.scene_view_manager import SceneViewManager
from core.model_builder import collect_all_joint_info
import ctypes

def set_open3d_window_icon(window_title, icon_path):
    icon_path = str(Path(icon_path).resolve())

    user32 = ctypes.windll.user32

    hwnd = user32.FindWindowW(None, window_title)
    if not hwnd:
        print("Open3D window not found:", window_title)
        return

    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010

    hicon = user32.LoadImageW(
        None,
        icon_path,
        IMAGE_ICON,
        0,
        0,
        LR_LOADFROMFILE
    )

    if not hicon:
        print("Icon load failed:", icon_path)
        return

    # タイトルバー左上
    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)

    # タスクバー
    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)

class MainWindow:

    def __init__(self):
        self.window = gui.Application.instance.create_window(
            "CNCMotionMaker",
            1000,
            720
        )
        self.control_panel_collapsed = False

        self.scene_manager = SceneViewManager()
        self.scene_view = SceneView(self.window, on_mouse_down=self.raise_all_windows)
        self.scene_manager.add_view(self.scene_view)
        
        self.extra_window = None
        self.extra_scene_view = None
        self._create_extra_view()

        self.project_root = Path(__file__).resolve().parent.parent
        json_dir = self.project_root / "JSON"

        set_open3d_window_icon(
            "CNCMotionMaker",
            self.project_root / "assets" / "icon.ico"
        )

        self.control_panel = ControlPanel(
            json_dir=json_dir,
            on_json_selected=self.on_json_selected,
            on_toggle_panel=self.toggle_control_panel,
        )

        self.window.add_child(self.scene_view.widget)
        self.window.add_child(self.control_panel.widget)

        self.window.set_on_layout(self._on_layout)
        self.window.set_on_close(self._on_close)

        self.axis_window = AxisControlWindowQt(
            on_joint_move=self.on_joint_move
        )
        self.axis_window.show()
        self.program_window = MachinePanelQt(
            on_position_sample=self.apply_program_position
        )
        self._last_program_position = None

        self.program_window.show()
        self._move_sub_window()

        gui.Application.instance.post_to_main_thread(
            self.window,
            self._initial_refresh
        )
            
    def _create_extra_view(self):
        self.extra_window = gui.Application.instance.create_window(
            "CNCMotionMaker SubView",
            1000,
            720
        )

        self.extra_scene_view = SceneView(
            self.extra_window,
            on_mouse_down=None
        )

        self.extra_window.add_child(self.extra_scene_view.widget)
        self.extra_window.set_on_layout(self._on_extra_layout)
        self.extra_window.set_on_close(self._on_extra_close)
        self.extra_window.set_needs_layout()

        self.scene_manager.add_view(self.extra_scene_view)

        gui.Application.instance.post_to_main_thread(
            self.extra_window,
            lambda: set_open3d_window_icon(
                "CNCMotionMaker SubView",
                self.project_root / "assets" / "icon.ico"
            )
        )

    def open_extra_view(self):
        if self.extra_window is None:
            return

    def _on_extra_close(self):
        self.scene_manager.remove_view(self.extra_scene_view)

        self.extra_scene_view = None
        self.extra_window = None
        return True

    def _on_extra_layout(self, layout_context):
        if self.extra_window is None:
            return

        if self.extra_scene_view is None:
            return

        rect = self.extra_window.content_rect

        self.extra_scene_view.widget.frame = gui.Rect(
            rect.x,
            rect.y,
            rect.width,
            rect.height
        )

        if rect.width <= 0 or rect.height <= 0:
            return

    def toggle_control_panel(self):
        self.control_panel_collapsed = not self.control_panel_collapsed
        self.window.set_needs_layout()

    def _initial_refresh(self):
        self.window.set_needs_layout()
        self.scene_view.widget.force_redraw()

    def _on_layout(self, layout_context):

        rect = self.window.content_rect
        em = self.window.theme.font_size

        if self.control_panel_collapsed:
            panel_width = int(1.0 * em)
        else:
            panel_width = int(10 * em)

        self.scene_view.widget.frame = gui.Rect(
            rect.x,
            rect.y,
            rect.width - panel_width,
            rect.height
        )

        self.control_panel.widget.frame = gui.Rect(
            rect.x + rect.width - panel_width,
            rect.y,
            panel_width,
            rect.height
        )
        self.raise_all_windows()

    def on_json_selected(self, json_path):
        print("Load JSON:", json_path)
        try:
            self.scene_manager.load_json_model(json_path)

            joint_info = collect_all_joint_info(
                self.scene_view.roots
            )
            
            self.axis_window.set_axis_info(joint_info)
            
            gui.Application.instance.post_to_main_thread(
                self.window,
                lambda: self.program_window.update_axis_info(joint_info)
            )

        except Exception:
            traceback.print_exc()

    def on_joint_move(self, joint_info, direction):
        node = joint_info["node"]
        joint = node.joint

        if joint is None:
            return

        if joint.type == "rotate":
            new_value = node.joint_value + direction
        elif joint.type == "linear":
            new_value = node.joint_value + direction
        elif joint.type == "chain":
            new_value = node.joint_value + direction
        elif joint.type == "signal":
            new_value = 1 if direction > 0 else 0
        else:
            return

        self.apply_program_position({
            joint.name: new_value
        })

    def _move_sub_window(self):
        window_gap = 2
        sub_window_width = 300

        main_rect = self.window.os_frame
        scale = self.program_window.devicePixelRatioF()

        main_x = int(main_rect.x / scale)
        main_y = int(main_rect.y / scale)
        main_w = int(main_rect.width / scale)
        main_h = int(main_rect.height / scale)

        if self.axis_window is not None:
            self.axis_window.resize(
                sub_window_width,
                main_h
            )

            self.axis_window.move(
                main_x + main_w + window_gap,
                main_y - 30
            )

        if self.program_window is not None:
            self.program_window.resize(
                sub_window_width,
                main_h
            )

            self.program_window.move(
                main_x - sub_window_width - window_gap,
                main_y - 30
            )
            
    def _on_close(self):
        if self.axis_window is not None:
            self.axis_window.close()
        if self.program_window is not None:
            self.program_window.close()

        extra_window = self.extra_window
        self.extra_window = None
        self.extra_scene_view = None

        if extra_window is not None:
            extra_window.close()
        return True
    
    def apply_program_position(self, position):
        if self._last_program_position == position:
            return

        self._last_program_position = position.copy()

        def update():
            model_reset = False

            for axis_name, value in position.items():
                if self.scene_manager.set_joint_value_by_name(axis_name, value):
                    model_reset = True

            if self.axis_window is not None:
                self.axis_window.refresh_axis_values()

            self.scene_manager.refresh_model(model_reset)

        gui.Application.instance.post_to_main_thread(
            self.window,
            update
        )

    def raise_all_windows(self):
        if self.axis_window is not None:
            self.axis_window.raise_()

        if self.program_window is not None:
            self.program_window.raise_()