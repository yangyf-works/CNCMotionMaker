from pathlib import Path
import traceback
import open3d.visualization.gui as gui # type: ignore

from app.scene_view import SceneView
from app.control_panel import ControlPanel
from app.axis_window import AxisControlWindow
from core.model_builder import collect_all_joint_info

class MainWindow:

    def __init__(self):

        self.window = gui.Application.instance.create_window(
            "CNCMotionMaker",
            1280,
            720
        )

        self.scene_view = SceneView(self.window)

        project_root = Path(__file__).resolve().parent.parent
        json_dir = project_root / "JSON"

        self.control_panel = ControlPanel(
            json_dir=json_dir,
            on_json_selected=self.on_json_selected
        )

        self.window.add_child(self.scene_view.widget)
        self.window.add_child(self.control_panel.widget)

        self.window.set_on_layout(self._on_layout)
        self.window.set_on_close(
            self._on_close
        )

        self.axis_window = AxisControlWindow(
            on_joint_move=self.on_joint_move
        )
        self._move_sub_window()

        gui.Application.instance.post_to_main_thread(
            self.window,
            self._initial_refresh
        )

    def _initial_refresh(self):
        self.window.set_needs_layout()
        self.scene_view.widget.force_redraw()

    def _on_layout(self, layout_context):

        rect = self.window.content_rect
        panel_width = 225

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

            self.scene_view.load_json_model(json_path)

            joint_info = collect_all_joint_info(
                self.scene_view.roots
            )
            
            gui.Application.instance.post_to_main_thread(
                self.axis_window.window,
                lambda: self.axis_window.set_axis_info(joint_info)
            )
        except Exception:
            traceback.print_exc()

    def on_joint_move(self, joint_info, direction):

        self.scene_view.move_joint(
            joint_info["node"],
            direction
        )

    def _move_sub_window(self):
        main_rect = self.window.os_frame

        axis_rect = self.axis_window.window.os_frame
        axis_rect.x = main_rect.x + main_rect.width + 10
        axis_rect.y = main_rect.y
        self.axis_window.window.os_frame = axis_rect
        
    def _on_close(self):
        if self.axis_window is not None:
            self.axis_window.window.close_from_main()

        return True