from pathlib import Path

import open3d.visualization.gui as gui

from app.scene_view import SceneView
from app.control_panel import ControlPanel
from core.model_builder import collect_all_joint_info

class MainWindow:

    def __init__(self):

        self.window = gui.Application.instance.create_window(
            "3D Model Viewer",
            1280,
            720
        )

        self.scene_view = SceneView(self.window)

        project_root = Path(__file__).resolve().parent.parent
        json_dir = project_root / "JSON"

        self.control_panel = ControlPanel(
            json_dir=json_dir,
            on_json_selected=self.on_json_selected,
            on_joint_move=self.on_joint_move
        )

        self.window.add_child(self.scene_view.widget)
        self.window.add_child(self.control_panel.widget)

        self.window.set_on_layout(self._on_layout)

    def _on_layout(self, layout_context):

        rect = self.window.content_rect
        panel_width = 300

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

        self.scene_view.load_json_model(json_path)

        joint_info = collect_all_joint_info(
            self.scene_view.roots
        )

        self.control_panel.set_axis_info(joint_info)
        self.window.set_needs_layout()
    
    def on_joint_move(self, joint_info, direction):

        self.scene_view.move_joint(
            joint_info["node"],
            direction
        )