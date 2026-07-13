from pathlib import Path
import sys
import traceback
import open3d.visualization.gui as gui # type: ignore

from app.scene_view import SceneView
from app.control_panel import ControlPanel
from app.axis_window import AxisControlWindowQt
from app.program_window_qt import MachinePanelQt
from app.scene_view_manager import SceneViewManager
from core.model_builder import collect_all_joint_info
import ctypes

user32 = ctypes.windll.user32

GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8

WS_SYSMENU = 0x00080000

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

def make_tool_window(
    child_title: str,
    owner_title: str,
) -> bool:
    child_hwnd = user32.FindWindowW(None, child_title)
    owner_hwnd = user32.FindWindowW(None, owner_title)

    if not child_hwnd:
        print("Child window not found:", child_title)
        return False

    if not owner_hwnd:
        print("Owner window not found:", owner_title)
        return False

    # サブ画面をメイン画面の所有ウィンドウにする
    user32.SetWindowLongPtrW(
        child_hwnd,
        GWLP_HWNDPARENT,
        owner_hwnd,
    )

    ex_style = user32.GetWindowLongPtrW(
        child_hwnd,
        GWL_EXSTYLE,
    )

    # タスクバーに独立表示しないツールウィンドウへ変更
    ex_style |= WS_EX_TOOLWINDOW
    ex_style &= ~WS_EX_APPWINDOW

    user32.SetWindowLongPtrW(
        child_hwnd,
        GWL_EXSTYLE,
        ex_style,
    )

    style = user32.GetWindowLongPtrW(
        child_hwnd,
        GWL_STYLE,
    )

    # 閉じるボタンとシステムメニューを削除
    style &= ~WS_SYSMENU

    user32.SetWindowLongPtrW(
        child_hwnd,
        GWL_STYLE,
        style,
    )

    # スタイル変更を反映
    user32.SetWindowPos(
        child_hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE
        | SWP_NOSIZE
        | SWP_NOZORDER
        | SWP_FRAMECHANGED,
    )

    return True

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
    def __init__(self, view_count=1, root_path=None, json_dir=None):
        
        self.window_gap = 2
        self.sub_window_width = 300

        self.project_root = root_path

        self.scene_manager = SceneViewManager()

        self.window = gui.Application.instance.create_window(
            "CNCMotionMaker",
            1000,
            720
        )
        self.control_panel_collapsed = False
        self.scene_view = SceneView(self.window)
        self.scene_manager.add_view(self.scene_view)
        
        self.extra_windows = []
        self.extra_scene_views = []

        for i in range(view_count - 1):
            self._create_extra_view(i + 2)


        for extra_scene_view in self.extra_scene_views:
            self.scene_manager.add_view(extra_scene_view)

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
        make_tool_window(
            child_title=self.axis_window.windowTitle(),
            owner_title=self.window.title,
        )
        self.program_window = MachinePanelQt(
            on_position_sample=self.apply_program_position
        )
        self._last_program_position = None
        self.program_window.show()
        make_tool_window(
            child_title=self.program_window.windowTitle(),
            owner_title=self.window.title,
        )

        gui.Application.instance.post_to_main_thread(
            self.window,
            self._initialize_window_layout
        )
    
    def _initialize_window_layout(self):
        self._arrange_open3d_windows()

        self.window.set_needs_layout()
        self.scene_view.widget.force_redraw()

        for extra_window, extra_view in zip(
            self.extra_windows,
            self.extra_scene_views
        ):
            extra_window.set_needs_layout()
            extra_view.widget.force_redraw()

        self._move_sub_window()

    def _get_open3d_windows(self):
        return [self.window] + list(self.extra_windows)

    def _arrange_open3d_windows(self):
        windows = self._get_open3d_windows()
        count = len(windows)

        if not 2 <= count <= 4:
            return

        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen()
        if screen is None:
            return

        g = screen.availableGeometry()
        scale = screen.devicePixelRatio()

        sx = int(g.x() * scale)
        sy = int(g.y() * scale)
        sw = int(g.width() * scale)
        sh = int(g.height() * scale)

        main = windows[0].os_frame
        original_w = int(main.width)
        original_h = int(main.height)

        gap = int(self.window_gap)
        side = int(self.sub_window_width * scale)
        title_h = int(30 * scale)
        margin = int(40)

        usable_w = sw - margin * 2
        usable_h = sh - margin * 2

        scale_w = (usable_w - side * 2 - gap * 2) / original_w
        scale_h = (usable_h - title_h * 2 - gap) / (original_h * 2)
        layout_scale = min(1.0, scale_w, scale_h)

        main_w = max(1, int(original_w * layout_scale))
        main_h = max(1, int(original_h * layout_scale))

        total_w = main_w + side * 2 + gap * 2
        total_h = main_h * 2 + title_h * 2 + gap

        x = sx + (sw - total_w) // 2
        y = sy + (sh - total_h) // 2 + margin

        main_x = x + side + gap

        windows[0].os_frame = gui.Rect(
            main_x, y, main_w, main_h
        )

        sub_count = count - 1
        sub_y = y + title_h + main_h + gap
        available_w = total_w - gap * (sub_count - 1)
        sub_w = available_w // sub_count

        for i in range(sub_count):
            sub_x = x + i * (sub_w + gap)
            width = total_w - (sub_x - x) if i == sub_count - 1 else sub_w

            windows[i + 1].os_frame = gui.Rect(
                sub_x, sub_y, width, main_h
            )

    def _create_extra_view(self, view_no):
        title = f"SubView {view_no}"

        extra_window = gui.Application.instance.create_window(
            title,
            1000,
            720
        )

        extra_scene_view = SceneView(
            extra_window,
            on_mouse_down=None
        )

        extra_window.add_child(extra_scene_view.widget)

        extra_window.set_on_layout(
            lambda layout_context, w=extra_window, v=extra_scene_view:
                self._on_extra_layout(w, v)
        )

        extra_window.set_on_close(
            lambda w=extra_window, v=extra_scene_view:
                self._on_extra_close(w, v)
        )

        extra_window.set_needs_layout()

        self.extra_windows.append(extra_window)
        self.extra_scene_views.append(extra_scene_view)

        make_tool_window(
            child_title=title,
            owner_title=self.window.title,
        )

    def _on_extra_close(self, extra_window, extra_scene_view):
        self.scene_manager.remove_view(extra_scene_view)

        if extra_window in self.extra_windows:
            self.extra_windows.remove(extra_window)

        if extra_scene_view in self.extra_scene_views:
            self.extra_scene_views.remove(extra_scene_view)

        return True

    def _on_extra_layout(self, extra_window, extra_scene_view):
        rect = extra_window.content_rect

        extra_scene_view.widget.frame = gui.Rect(
            rect.x,
            rect.y,
            rect.width,
            rect.height
        )

    def toggle_control_panel(self):
        self.control_panel_collapsed = not self.control_panel_collapsed
        self.window.set_needs_layout()
        
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
        main_rect = self.window.os_frame
        scale = self.program_window.devicePixelRatioF()

        main_x = int(main_rect.x / scale)
        main_y = int(main_rect.y / scale)
        main_w = int(main_rect.width / scale)
        main_h = int(main_rect.height / scale)

        if self.axis_window is not None:
            self.axis_window.resize(
                self.sub_window_width,
                main_h
            )

            self.axis_window.move(
                main_x + main_w + self.window_gap,
                main_y - 30
            )

        if self.program_window is not None:
            self.program_window.resize(
                self.sub_window_width,
                main_h
            )

            self.program_window.move(
                main_x - self.sub_window_width - self.window_gap,
                main_y - 30
            )

    def _on_close(self):
        if getattr(self, "_closing", False):
            return True

        self._closing = True

        if self.program_window is not None:
            self.program_window.stop_all_processing()

        if self.axis_window is not None:
            self.axis_window.close()
            self.axis_window = None

        if self.program_window is not None:
            self.program_window.close()
            self.program_window = None

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()

        for view in list(self.extra_scene_views):
            self.scene_manager.remove_view(view)

        self.extra_scene_views.clear()

        self.extra_windows.clear()

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
