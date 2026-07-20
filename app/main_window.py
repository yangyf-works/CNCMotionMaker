from pathlib import Path
import sys
import traceback
import open3d.visualization.gui as gui # type: ignore
from PySide6.QtWidgets import QApplication

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
    def __init__(self, root_path=None, json_dir=None):
        
        self.window_gap = 1
        self.sub_window_width = 300

        self.window_w = 1000
        self.window_h = 720

        screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        scale = screen.devicePixelRatio()

        screen_x = int(geometry.x() * scale)
        screen_y = int(geometry.y() * scale)
        screen_w = int(geometry.width() * scale)
        screen_h = int(geometry.height() * scale)

        window_x = screen_x + (screen_w - self.window_w) // 2
        window_y = screen_y + (screen_h - self.window_h) // 2

        self.window = gui.Application.instance.create_window(
            "CNCMotionMaker",
            self.window_w,
            self.window_h,
            window_x,
            window_y,
        )
        
        self.project_root = root_path
        self.scene_manager = SceneViewManager()

        self.control_panel_collapsed = False
        self.scene_view = SceneView(self.window)
        self.scene_manager.add_view(self.scene_view)
        
        self.extra_windows = []
        self.extra_scene_views = []
        self.extra_view_numbers = {}

        self.current_json_path = None

        set_open3d_window_icon(
            "CNCMotionMaker",
            self.project_root / "assets" / "icon.ico"
        )

        self.control_panel = ControlPanel(
            json_dir=json_dir,
            on_json_selected=self.on_json_selected,
            on_toggle_panel=self.toggle_control_panel,
        )
        self.add_view_button = gui.Button("+ View")
        self.add_view_button.background_color = gui.Color(
            0.15, 0.45, 0.15, 1.0
        )
        self.add_view_button.set_on_clicked(
            self._on_add_view_clicked
        )
        self.remove_view_button = gui.Button("- View")
        self.remove_view_button.background_color = gui.Color(
            0.50, 0.08, 0.08, 1.0,
        )
        self.remove_view_button.set_on_clicked(
            self._on_remove_view_clicked
        )
        self.remove_view_button.enabled = False

        self.window.add_child(self.scene_view.widget)
        self.window.add_child(self.control_panel.widget)
        self.window.add_child(self.add_view_button)
        self.window.add_child(self.remove_view_button)

        self.window.set_on_layout(self._on_layout)
        self.window.set_on_close(self._on_close)

        self.axis_window = AxisControlWindowQt(
            on_joint_move=self.on_joint_move
        )
        self.program_window = MachinePanelQt(
            on_position_sample=self.apply_program_position
        )
        self._last_program_position = None

        gui.Application.instance.post_to_main_thread(
            self.window,
            self._initialize_window_layout
        )

    def _on_add_view_clicked(self):
        if len(self._get_open3d_windows()) >= 4:
            print("Open3D views are limited to 4.")
            return

        self.add_view_button.enabled = False
        self.remove_view_button.enabled = False

        gui.Application.instance.post_to_main_thread(
            self.window,
            self._add_extra_view
        )
    
    def _add_extra_view(self):
        try:
            view_no = self._get_next_view_no()
            if view_no is None:
                return

            extra_window, extra_scene_view = self._create_extra_view(view_no)
            self.scene_manager.add_view(extra_scene_view)

            if self.current_json_path is not None:
                extra_scene_view.load_json_model(self.current_json_path)
                self._copy_joint_values(self.scene_view, extra_scene_view)
                extra_scene_view.refresh_model(model_reset=True)

            extra_window.set_needs_layout()
            extra_scene_view.widget.force_redraw()

            self._arrange_open3d_windows()
            self._move_sub_window()

            gui.Application.instance.post_to_main_thread(
                extra_window,
                lambda w=extra_window:
                    self._finish_extra_window(w)
            )

        except Exception:
            traceback.print_exc()

        finally:
            self._view_add_remove_btn_update()

    def _copy_joint_values(
        self,
        source_view,
        target_view,
    ):
        source_nodes = self._collect_joint_nodes(source_view.roots)
        target_nodes = self._collect_joint_nodes(target_view.roots)

        if len(source_nodes) != len(target_nodes):
            print(
                "Joint count mismatch:",
                len(source_nodes),
                len(target_nodes),
            )
            return

        for source_node, target_node in zip(
            source_nodes,
            target_nodes,
        ):
            target_node.joint_value = source_node.joint_value

    def _collect_joint_nodes(self, roots):
        result = []

        def walk(node):
            if node.joint is not None:
                result.append(node)

            for child in node.children:
                walk(child)

        for root in roots:
            walk(root)

        return result

    def _get_next_view_no(self):
        used_numbers = set(
            self.extra_view_numbers.values()
        )

        for view_no in range(2, 5):
            if view_no not in used_numbers:
                return view_no

        return None

    def _finish_extra_window(self, extra_window):
        view_no = self.extra_view_numbers.get(id(extra_window))
        if view_no is None:
            return
    
        title = f"SubView {self.extra_view_numbers.get(id(extra_window)) - 1}"

        extra_window.set_needs_layout()

        make_tool_window(
            child_title=title,
            owner_title=self.window.title,
        )

        if self.project_root is not None:
            set_open3d_window_icon(
                title,
                self.project_root / "assets" / "icon.ico"
            )
            
    def _initialize_window_layout(self):
        self.window.set_needs_layout()
        self.scene_view.widget.force_redraw()
        self._move_sub_window()

        self.axis_window.show()
        self.program_window.show()

        make_tool_window(
            child_title=self.axis_window.windowTitle(),
            owner_title=self.window.title,
        )

        make_tool_window(
            child_title=self.program_window.windowTitle(),
            owner_title=self.window.title,
        )

    def _arrange_open3d_windows(self):
        windows = self._get_open3d_windows()
        count = len(windows)

        if not 2 <= count <= 4:
            return

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

    def _get_open3d_windows(self):
        return [self.window] + list(self.extra_windows)
    
    def _view_add_remove_btn_update(self):
        sub_count = self.scene_manager.sub_view_count()
        self.remove_view_button.enabled = sub_count > 0
        self.add_view_button.enabled = sub_count < 3

    def _on_remove_view_clicked(self):
        if not self.extra_windows:
            return
        
        self.add_view_button.enabled = False
        self.remove_view_button.enabled = False

        gui.Application.instance.post_to_main_thread(
            self.window,
            self._remove_last_view
        )

    def _remove_last_view(self):
        if not self.extra_windows:
            return

        self._close_extra_view(
            self.extra_windows[-1],
            self.extra_scene_views[-1],
        )

    def _create_extra_view(self, view_no):
        title = f"SubView {view_no - 1}"

        camera_views = {
            2: "front",
            3: "right",
            4: "top",
        }

        default_camera_view = camera_views.get(view_no, "default")
        
        extra_window = gui.Application.instance.create_window(
            title,
            self.window_w,
            self.window_h
        )

        extra_scene_view = SceneView(
            extra_window,
            on_mouse_down=None,
            default_camera_view=default_camera_view
        )

        close_button = gui.Button("×")
        close_button.background_color = gui.Color(
            0.50, 0.08, 0.08, 1.0,
        )
        close_button.set_on_clicked(
            lambda w=extra_window, v=extra_scene_view:
                self._on_extra_close_button(w, v)
        )

        extra_window.add_child(extra_scene_view.widget)
        extra_window.add_child(close_button)

        extra_window.set_on_layout(
            lambda layout_context,
            w=extra_window,
            v=extra_scene_view,
            b=close_button:
                self._on_extra_layout(w, v, b)
        )

        extra_window.set_needs_layout()

        self.extra_windows.append(extra_window)
        self.extra_scene_views.append(extra_scene_view)

        self.extra_view_numbers[id(extra_window)] = view_no

        return extra_window, extra_scene_view

    def _on_extra_layout(
        self,
        extra_window,
        extra_scene_view,
        close_button,
    ):
        rect = extra_window.content_rect
        em = extra_window.theme.font_size

        button_size = int(2.0 * em)
        margin = int(0.5 * em)

        extra_scene_view.widget.frame = gui.Rect(
            rect.x,
            rect.y,
            rect.width,
            rect.height
        )

        close_button.frame = gui.Rect(
            rect.x + rect.width - button_size - margin,
            rect.y + margin,
            button_size,
            button_size,
        )

    def _on_extra_close_button(
        self,
        extra_window,
        extra_scene_view,
    ):
        gui.Application.instance.post_to_main_thread(
            self.window,
            lambda: self._close_extra_view(
                extra_window,
                extra_scene_view,
            )
        )

    def _close_extra_view(
        self,
        extra_window,
        extra_scene_view,
    ):
        if extra_window not in self.extra_windows:
            return

        index = self.extra_windows.index(extra_window)

        self.scene_manager.remove_view(
            extra_scene_view
        )

        self.extra_windows.pop(index)
        self.extra_scene_views.pop(index)
        self.extra_view_numbers.pop(id(extra_window), None)

        extra_window.close()

        self._arrange_open3d_windows()
        self._move_sub_window()
        self._view_add_remove_btn_update()
        
    def toggle_control_panel(self):
        self.control_panel_collapsed = not self.control_panel_collapsed
        self.window.set_needs_layout()
        
    def _on_layout(self, layout_context):

        rect = self.window.content_rect
        em = self.window.theme.font_size

        if self.control_panel_collapsed:
            panel_width = int(1.5 * em)
        else:
            panel_width = int(10 * em)

        button_width = int(4 * em)
        button_height = int(2 * em)
        margin = int(0.5 * em)

        self.remove_view_button.frame = gui.Rect(
            rect.x + rect.width
            - panel_width
            - button_width
            - margin,
            rect.y + margin * 2 + button_height,
            button_width,
            button_height,
        )

        self.add_view_button.frame = gui.Rect(
            rect.x + rect.width
            - panel_width
            - button_width
            - margin,
            rect.y + margin,
            button_width,
            button_height
        )

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

        self.current_json_path = json_path
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

        app = QApplication.instance()
        if app is not None:
            app.processEvents()

        for view in list(self.extra_scene_views):
            self.scene_manager.remove_view(view)

        self.extra_scene_views.clear()
        self.extra_windows.clear()
        self.extra_view_numbers.clear()

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
