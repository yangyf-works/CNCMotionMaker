from pathlib import Path
import os
import traceback
from uuid import uuid4

import open3d.visualization.gui as gui  # type: ignore
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from app.scene_view import SceneView
from app.control_panel import ControlPanel
from app.axis_window import AxisControlWindowQt
from app.program_window_qt import MachinePanelQt
from app.scene_view_manager import SceneViewManager
from app.native_window import NativeWindowApi
from app.open3d_host import Open3DHost
from app.open3d_event_loop import Open3DEventLoop
from core.model_builder import collect_all_joint_info


# Open3D 0.19's Window::FLAG_HIDDEN is not exported as a Python constant.
OPEN3D_WINDOW_HIDDEN = 1 << 0


class MainWindow(QMainWindow):
    def __init__(self, root_path=None, json_dir=None):
        super().__init__()
        self.project_root = Path(root_path) if root_path else Path(__file__).resolve().parent.parent
        self.window_gap = 1
        self.sub_window_width = 300
        self.window_w, self.window_h = 1000, 720
        self.window = None
        self.scene_view = None
        self.axis_window = None
        self.program_window = None
        self._panels_to_restore = None
        self.native_api = None
        self.host = None
        self.extra_windows = []
        self.extra_scene_views = []
        self.extra_view_numbers = {}
        self._closing_extra = set()
        self._closing = False
        self._shutdown_complete = False
        self._allow_native_close = False
        self._started = False
        self.exit_code = 0
        self.current_json_path = None
        self._last_program_position = None
        self.scene_manager = SceneViewManager()
        self.event_loop = Open3DEventLoop(gui.Application.instance, self)
        self.event_loop.shutdown_ready.connect(self._finish_shutdown)
        self.event_loop.failed.connect(self._on_event_error)
        # Names remain unique even if several instances of the app are running.
        self._native_title = f"CNCMotionMaker renderer {os.getpid()} {uuid4().hex}"
        self.setWindowTitle("CNCMotionMaker")
        self.setWindowIcon(QIcon(str(self.project_root / "assets" / "icon.ico")))
        self.resize(self.window_w, self.window_h)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose)

        try:
            self.native_api = NativeWindowApi()
            self.window = self._create_offscreen_window(self._native_title)
            # Qt will show the renderer once it has a native container.
            self.window.show(False)
            self.window.set_on_close(self._on_native_close)

            central = QWidget(self)
            layout = QHBoxLayout(central)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            viewport = QVBoxLayout()
            viewport.setContentsMargins(0, 0, 0, 0)
            viewport.setSpacing(0)
            viewport.addWidget(self._create_viewport_toolbar(central))
            self.host = Open3DHost(self.native_api, central)
            self.scene_view = SceneView(
                self.window,
                on_mouse_down=self.host.focus_renderer,
                on_fixed_joint_label_changed=self.fixed_joint_label.setText,
            )
            self.scene_manager.add_view(self.scene_view)
            self.window.add_child(self.scene_view.widget)
            self.window.set_on_layout(self._on_layout)
            viewport.addWidget(self.host, 1)
            layout.addLayout(viewport, 1)
            self.control_panel = ControlPanel(
                json_dir=json_dir or self.project_root / "JSON",
                on_json_selected=self.on_json_selected,
                parent=central,
            )
            layout.addWidget(self.control_panel)
            self.setCentralWidget(central)
            self.host.attach(self._native_title)
            self.scene_manager.on_trajectory_state_changed = self._on_trajectory_state_changed
            self._on_trajectory_state_changed(self.scene_manager.trajectory_enabled)

            self.axis_window = AxisControlWindowQt(on_joint_move=self.on_joint_move)
            self.program_window = MachinePanelQt(on_position_sample=self.apply_program_position)
            # Preserve the two tool windows and their contents, with Qt ownership.
            for panel in (self.axis_window, self.program_window):
                panel.setParent(self, panel.windowFlags())
                panel.setWindowIcon(self.windowIcon())
            screen = self.screen()
            if screen is not None:
                # The old Open3D window was sized in Windows device pixels.
                area = screen.availableGeometry()
                scale = screen.devicePixelRatio()
                width = round(self.window_w / scale)
                height = round(self.window_h / scale)
                self.setGeometry(
                    area.x() + (area.width() - width) // 2,
                    area.y() + (area.height() - height) // 2,
                    width,
                    height,
                )
        except BaseException:
            self.shutdown()
            raise

    def _create_offscreen_window(self, title):
        # Explicit coordinates disable Open3D's first-draw auto-centering.
        # AddWindow shows the HWND even with FLAG_HIDDEN, so start offscreen.
        x, y = self.native_api.offscreen_origin()
        return gui.Application.instance.create_window(
            title, self.window_w, self.window_h, x=x, y=y, flags=OPEN3D_WINDOW_HIDDEN,
        )

    def start(self):
        if self._started or self._closing:
            return
        self._started = True
        self.show()
        self.host.verify_embedding()
        self.host.start_keyboard_routing()
        self._move_sub_window()
        self.axis_window.show()
        self.program_window.show()
        self.window.set_needs_layout()
        self.scene_view.widget.force_redraw()
        self.event_loop.start()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            # Wait for Qt to finish restoring the active window's focus.
            QTimer.singleShot(0, self, self._focus_main_view)

    def _focus_main_view(self):
        if not self._closing and self.host is not None:
            self.host.focus_renderer()

    def _on_event_error(self, message):
        self.exit_code = 1
        print(message)
        self.shutdown()

    def _create_viewport_toolbar(self, parent):
        # Keep the controls outside the native child so Qt receives their clicks.
        toolbar = QWidget(parent)
        toolbar.setObjectName("ViewportToolbar")
        toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        toolbar.setStyleSheet("""
            QWidget#ViewportToolbar { background-color: black; }
            QLabel { background-color: transparent; color: #ff991a;
                     font-size: 10.5pt; font-weight: 600; }
            QPushButton { color: #e0e0e0; border: 1px solid #606060; padding: 0;
                          font-size: 10.5pt; font-weight: 600; }
            QPushButton#TraceButton { background-color: #4d4d4d; }
            QPushButton#TraceButton:hover { background-color: #666666; }
            QPushButton#TraceButton:checked { background-color: #337fe6; }
            QPushButton#TraceButton:checked:hover { background-color: #4592f2; }
            QPushButton#AddViewButton { background-color: #267326; }
            QPushButton#AddViewButton:hover { background-color: #328b32; }
            QPushButton#AddViewButton:disabled { background-color: #303030; color: #808080; }
            QPushButton#PanelVisibilityButton { background-color: #68458c; }
            QPushButton#PanelVisibilityButton:hover { background-color: #7a549e; }
        """)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(8)

        self.fixed_joint_label = QLabel(toolbar)
        self.fixed_joint_label.setTextFormat(Qt.TextFormat.PlainText)
        self.fixed_joint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.fixed_joint_label, 1)

        self.trajectory_button = QPushButton("Trace ON", toolbar)
        self.trajectory_button.setObjectName("TraceButton")
        self.trajectory_button.setCheckable(True)
        self.trajectory_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.trajectory_button.setFixedSize(88, 28)
        self.trajectory_button.clicked.connect(self._on_trajectory_button_clicked)
        layout.addWidget(self.trajectory_button)

        self.add_view_button = QPushButton("+ View", toolbar)
        self.add_view_button.setObjectName("AddViewButton")
        self.add_view_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_view_button.setFixedSize(60, 28)
        self.add_view_button.clicked.connect(self._on_add_view_clicked)
        layout.addWidget(self.add_view_button)

        self.panel_visibility_button = QPushButton("Hide Panels", toolbar)
        self.panel_visibility_button.setObjectName("PanelVisibilityButton")
        self.panel_visibility_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.panel_visibility_button.setFixedSize(104, 28)
        self.panel_visibility_button.clicked.connect(self._toggle_tool_panels)
        layout.addWidget(self.panel_visibility_button)
        return toolbar

    def _on_trajectory_button_clicked(self):
        if not self._closing:
            self.scene_manager.toggle_trajectory()

    def _on_trajectory_state_changed(self, enabled):
        self.trajectory_button.setChecked(enabled)
        self.trajectory_button.setText("Trace ON" if enabled else "Trace OFF")

    def _toggle_tool_panels(self):
        if self._closing:
            return
        if self._panels_to_restore is None:
            panels = tuple(
                panel for panel in (self.axis_window, self.program_window) if panel.isVisible()
            )
            if not panels:
                return
            self._panels_to_restore = panels
            for panel in panels:
                panel.hide()
            self.panel_visibility_button.setText("Show Panels")
        else:
            for panel in self._panels_to_restore:
                panel.show()
            self._panels_to_restore = None
            self.panel_visibility_button.setText("Hide Panels")

    def _on_layout(self, _):
        self.scene_view.widget.frame = self.window.content_rect

    def _on_add_view_clicked(self):
        if self._closing or not self.add_view_button.isEnabled():
            return
        self.add_view_button.setEnabled(False)
        self.event_loop.defer(self._add_extra_view)

    def _get_next_view_no(self):
        used = set(self.extra_view_numbers.values())
        return next((number for number in range(2, 5) if number not in used), None)

    def _add_extra_view(self):
        if self._closing:
            return
        extra_window = None
        extra_scene_view = None
        try:
            view_no = self._get_next_view_no()
            if view_no is None:
                return
            title = f"SubView {view_no - 1} [{os.getpid()} {uuid4().hex}]"
            extra_window = self._create_offscreen_window(title)
            # Register immediately so initialization failure still closes this window.
            self.extra_windows.append(extra_window)
            self.extra_view_numbers[id(extra_window)] = view_no
            extra_window.set_on_close(lambda w=extra_window: self._on_extra_native_close(w))
            extra_window.show(False)
            extra_scene_view = SceneView(
                extra_window, default_camera_view={2: "front", 3: "right", 4: "top"}[view_no]
            )
            self.extra_scene_views.append(extra_scene_view)
            close_button = gui.Button("×")
            close_button.background_color = gui.Color(0.50, 0.08, 0.08, 1.0)
            close_button.set_on_clicked(lambda w=extra_window: self._request_close_extra(w))
            extra_window.add_child(extra_scene_view.widget)
            extra_window.add_child(close_button)
            extra_window.add_child(extra_scene_view.fixed_joint_label)
            extra_window.set_on_layout(
                lambda _, w=extra_window, v=extra_scene_view, b=close_button: self._on_extra_layout(w, v, b)
            )
            # add_view already loads the current model and restores shared markers.
            self.scene_manager.add_view(extra_scene_view)
            if self.current_json_path is not None:
                self._copy_joint_values(self.scene_view, extra_scene_view)
                extra_scene_view.refresh_model(model_reset=True)
            handle = self.native_api.find_window(title)
            self.native_api.set_tool_owner(handle, int(self.winId()))
            self.native_api.set_icon(handle, self.project_root / "assets" / "icon.ico")
            extra_window.title = f"SubView {view_no - 1}"
            extra_window.set_needs_layout()
            extra_scene_view.widget.force_redraw()
            self._arrange_open3d_windows()
            if self.current_json_path is not None:
                extra_scene_view.fit_camera_to_model()
            extra_window.show(True)
        except Exception:
            traceback.print_exc()
            if extra_window is not None:
                self._close_extra_view(extra_window, extra_scene_view)
        finally:
            self._view_add_remove_btn_update()

    @staticmethod
    def _collect_joint_nodes(roots):
        result = []

        def walk(node):
            if node.joint is not None:
                result.append(node)
            for child in node.children:
                walk(child)

        for root in roots:
            walk(root)
        return result

    def _copy_joint_values(self, source_view, target_view):
        source = self._collect_joint_nodes(source_view.roots)
        target = self._collect_joint_nodes(target_view.roots)
        if len(source) != len(target):
            raise ValueError("Joint count mismatch between views")
        for source_node, target_node in zip(source, target):
            target_node.joint_value = source_node.joint_value

    def _on_extra_layout(self, window, view, button):
        rect = window.content_rect
        em = window.theme.font_size
        size, margin = int(2 * em), int(0.5 * em)
        view.widget.frame = rect
        button.frame = gui.Rect(rect.x + rect.width - size - margin, rect.y + margin, size, size)
        view.fixed_joint_label.frame = gui.Rect(rect.x + margin, rect.y + margin, int(8 * em), int(2 * em))

    def _on_extra_native_close(self, window):
        if id(window) in self._closing_extra or self._allow_native_close:
            return True
        self._request_close_extra(window)
        return False

    def _request_close_extra(self, window):
        self.event_loop.defer(lambda: self._close_extra_view(window))

    def _close_extra_view(self, window, view=None):
        if window not in self.extra_windows:
            return
        # Do not rely on parallel-list indexes when creation failed halfway through.
        if view is None:
            view = next((v for v in self.extra_scene_views if v.window is window), None)
        if view is not None:
            self.scene_manager.remove_view(view)
            if view in self.extra_scene_views:
                self.extra_scene_views.remove(view)
        self.extra_windows.remove(window)
        self.extra_view_numbers.pop(id(window), None)
        self._closing_extra.add(id(window))
        try:
            window.close()
        finally:
            self._closing_extra.discard(id(window))
        if not self._closing:
            self._arrange_open3d_windows()
            self._view_add_remove_btn_update()

    def _view_add_remove_btn_update(self):
        self.add_view_button.setEnabled(not self._closing and len(self.extra_windows) < 3)

    def _arrange_open3d_windows(self):
        # Preserve the main/extra-view tiling, using logical Qt coordinates for
        # the host and device pixels only for the separate Open3D windows.
        # Never assign os_frame to the embedded HWND itself.
        if not self.extra_windows:
            return
        screen = self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        # On Windows Qt scales screen sizes, but keeps screen origins in native pixels.
        origin = screen.geometry().topLeft()
        scale = screen.devicePixelRatio()
        gap, side, title_height, margin = self.window_gap, self.sub_window_width, 30, 40
        available_width = area.width() - margin * 2
        available_height = area.height() - margin * 2
        layout_scale = min(
            1.0,
            (available_width - side * 2 - gap * 2) / self.width(),
            (available_height - title_height * 2 - gap) / (self.height() * 2),
        )
        main_width = max(self.minimumSizeHint().width(), int(self.width() * layout_scale))
        main_height = max(self.minimumSizeHint().height(), int(self.height() * layout_scale))
        total_height = min(available_height, main_height * 2 + title_height * 2 + gap)
        x = area.x() + (area.width() - main_width) // 2
        y = area.y() + (area.height() - total_height) // 2
        self.setGeometry(x, y, main_width, main_height)
        self._move_sub_window()

        # The main window and side panels can exceed a small monitor's work area.
        # Fit the extra-view row separately, leaving room for its native frame.
        row_width = min(available_width, main_width + side * 2 + gap * 2)
        row_left = area.x() + (area.width() - row_width) // 2
        row_bottom = area.y() + area.height() - margin
        min_row_height = min(main_height, available_height, 80)
        row_top = min(y + title_height + main_height + gap, row_bottom - min_row_height)
        row_height = min(main_height, row_bottom - row_top)
        count = len(self.extra_windows)
        width = max(1, (row_width - gap * (count - 1)) // count)
        top = origin.y() + round((row_top - origin.y()) * scale)
        height = round(row_height * scale)
        for index, window in enumerate(self.extra_windows):
            sub_x = row_left + index * (width + gap)
            sub_width = row_width - (sub_x - row_left) if index == count - 1 else width
            left = round((sub_x - origin.x()) * scale)
            right = round((sub_x + sub_width - origin.x()) * scale)
            window.os_frame = gui.Rect(origin.x() + left, top, right - left, height)

    def on_json_selected(self, json_path):
        if not self._closing:
            # Open3D repaints the target window after the callback.
            gui.Application.instance.post_to_main_thread(
                self.window, lambda: self._load_json_model(json_path)
            )

    def _load_json_model(self, json_path):
        if self._closing:
            return
        try:
            self.program_window.stop_all_processing()
            self.axis_window.stop_all_processing()
            self._last_program_position = None
            self.scene_manager.load_json_model(json_path)
            self.current_json_path = json_path
            joint_info = collect_all_joint_info(self.scene_view.roots)
            self.axis_window.set_axis_info(joint_info)
            self.program_window.update_axis_info(joint_info)
            QTimer.singleShot(0, self, self._focus_main_view)
        except Exception:
            traceback.print_exc()

    def on_joint_move(self, joint_info, direction):
        if self._closing:
            return
        node = joint_info["node"]
        joint = node.joint
        if joint is None:
            return
        if joint.type in ("rotate", "linear", "chain"):
            value = node.joint_value + direction
        elif joint.type == "signal":
            value = 1 if direction > 0 else 0
        else:
            return
        self.apply_program_position({joint.name: value})

    def apply_program_position(self, position):
        if self._closing or self._last_program_position == position:
            return
        self._last_program_position = position.copy()
        position = position.copy()

        def update():
            if self._closing:
                return
            model_reset = False
            for name, value in position.items():
                if self.scene_manager.set_joint_value_by_name(name, value):
                    model_reset = True
            if self.axis_window is not None:
                self.axis_window.refresh_axis_values()
            self.scene_manager.refresh_model(model_reset)

        # Keep the existing Open3D update path and shared machine state.
        gui.Application.instance.post_to_main_thread(self.window, update)

    def _move_sub_window(self):
        if self._panels_to_restore is not None:
            return
        rect = self.frameGeometry()
        for panel, x in (
            (self.axis_window, rect.right() + 1 + self.window_gap),
            (self.program_window, rect.left() - self.sub_window_width - self.window_gap),
        ):
            if panel is not None:
                panel.resize(self.sub_window_width, self.height())
                panel.move(x, rect.top())

    def _on_native_close(self):
        if self._allow_native_close:
            return True
        if not self._closing:
            self._closing = True
            # Qt can dispatch Open3D's keys directly, outside run_one_tick().
            QTimer.singleShot(0, self, self.shutdown)
        return False

    def closeEvent(self, event):
        if self._shutdown_complete:
            event.accept()
        else:
            event.ignore()
            self.shutdown()
            if self._shutdown_complete:
                event.accept()

    def shutdown(self):
        if self._shutdown_complete:
            return
        self._closing = True
        # A final call after QApplication.exec() returns also completes a
        # deferred shutdown if Qt exited before the queued callback ran.
        self.event_loop.request_shutdown()

    def _finish_shutdown(self):
        if self._shutdown_complete:
            return
        self._closing = True

        def cleanup(action):
            try:
                action()
            except Exception:
                self.exit_code = 1
                traceback.print_exc()

        # Stop every source of machine updates before releasing any GUI resources.
        for panel in (self.program_window, self.axis_window):
            if panel is not None:
                cleanup(panel.stop_all_processing)
        if self.native_api is not None:
            cleanup(self.native_api.stop_keyboard_routing)
        # The HWND must remain owned by Open3D until Qt has relinquished its wrapper.
        if self.host is not None:
            cleanup(self.host.release)
        self.scene_manager.on_trajectory_state_changed = None
        self.scene_manager.clear_views()
        self._allow_native_close = True
        for window in list(self.extra_windows):
            cleanup(window.close)
        self.extra_windows.clear()
        self.extra_scene_views.clear()
        self.extra_view_numbers.clear()
        if self.window is not None:
            cleanup(self.window.close)
        self.scene_view = None
        self.window = None
        # Python Open3D 0.19 defers Filament engine destruction to its C++ atexit
        # hook. Drain native window destruction here, then let main.py exit normally.
        cleanup(gui.Application.instance.quit)
        cleanup(gui.Application.instance.run_one_tick)
        if self.native_api is not None:
            cleanup(self.native_api.close)
        for panel in (self.axis_window, self.program_window):
            if panel is not None:
                cleanup(panel.close)
        self._shutdown_complete = True
        self.close()
        if self._started:
            QApplication.instance().exit(self.exit_code)
