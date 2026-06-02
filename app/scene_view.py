import json
from pathlib import Path
import numpy as np

import open3d as o3d
import open3d.visualization.gui as gui
import open3d.visualization.rendering as rendering

from core.model_builder import build_geometry_list_from_model_json
import traceback

class SceneView:

    def __init__(self, window):

        self.window = window

        self.widget = gui.SceneWidget()

        self.widget.scene = rendering.Open3DScene(
            self.window.renderer
        )

        self.material = rendering.MaterialRecord()
        self.material.shader = "defaultLit"
        
        self.widget.scene.set_background([0, 0, 0, 1])
        

        self.widget.scene.scene.enable_sun_light(True)

        self.geometry_names = []

        self._create_test_geometry()

        self.widget.set_on_mouse(self._on_mouse)
        self.roots = []
        self.realtime_sun_dir = np.array([0.0, -1.0, 0.0], dtype=float)
        self.cur_sun_dir = np.array([0.0, -1.0, 0.0], dtype=float)
        self.sun_dragging = False
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        self.widget.scene.scene.set_sun_light(
            self.cur_sun_dir,
            [1.0, 1.0, 1.0],      # 色
            50000                 # 強度
        )
        

    def _create_test_geometry(self):

        axis = o3d.geometry.TriangleMesh.create_coordinate_frame(
            size=1.0
        )

        self.widget.scene.add_geometry(
            "axis",
            axis,
            self.material
        )

        self.geometry_names.append("axis")

        bbox = axis.get_axis_aligned_bounding_box()

        self.widget.setup_camera(
            60,
            bbox,
            bbox.get_center()
        )

    def clear_scene(self):

        for name in self.geometry_names:
            self.widget.scene.remove_geometry(name)

        self.geometry_names.clear()

    def load_json_model(self, json_path: Path):
        try:
            self.clear_scene()

            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            geometries = self._build_model_from_json(
                data,
                json_path
            )

            if not geometries:
                print("表示できるgeometryがありません")
                return

            merged_bbox = None

            for i, geom in enumerate(geometries):

                name = f"model_{i}"

                self.widget.scene.add_geometry(
                    name,
                    geom,
                    self.material
                )

                self.geometry_names.append(name)

                bbox = geom.get_axis_aligned_bounding_box()

                if merged_bbox is None:
                    merged_bbox = bbox
                else:
                    merged_bbox += bbox

            self.widget.setup_camera(
                60,
                merged_bbox,
                merged_bbox.get_center()
            )

            print("Model loaded:", json_path.name)

        except Exception:
            traceback.print_exc()
        
    def _build_model_from_json(self, data, json_path):

        roots, geometry_list = build_geometry_list_from_model_json(
            data,
            str(json_path.parent)
        )

        self.roots = roots

        return geometry_list

    def _on_mouse(self, event):

        if event.type == gui.MouseEvent.Type.BUTTON_DOWN: 
            if event.is_button_down(gui.MouseButton.LEFT):
                print(
                    f"Left Click ({event.x}, {event.y})"
                )
            
            if event.is_button_down(gui.MouseButton.MIDDLE):
                print(
                    f"Middle Click ({event.x}, {event.y})"
                )
                self.sun_dragging = True
                self.last_mouse_x = event.x
                self.last_mouse_y = event.y
                return gui.Widget.EventCallbackResult.HANDLED

        if event.type == gui.MouseEvent.Type.BUTTON_UP:
            if self.sun_dragging:
                self.sun_dragging = False
                self.cur_sun_dir = self.realtime_sun_dir.copy()
                return gui.Widget.EventCallbackResult.HANDLED

        if event.type == gui.MouseEvent.Type.DRAG:
            if self.sun_dragging:
                dx = event.x - self.last_mouse_x
                dy = event.y - self.last_mouse_y

                self._rotate_sun_by_mouse(dx, dy)

                return gui.Widget.EventCallbackResult.HANDLED

        return gui.Widget.EventCallbackResult.IGNORED
    
    
    def _rotate_sun_by_mouse(self, dx, dy):

        deg_per_pixel = 0.25
        yaw = np.radians(dx * deg_per_pixel)
        pitch = np.radians(dy * deg_per_pixel)

        # 現在のカメラ行列を取得
        view = np.asarray(
            self.widget.scene.camera.get_view_matrix()
        )

        R_cam = view[:3, :3].T

        right = R_cam[:, 0]
        up    = R_cam[:, 1]

        right = right / np.linalg.norm(right)
        up = up / np.linalg.norm(up)

        # 画面左右ドラッグ → カメラUp軸まわり
        R_yaw = self._rotation_matrix_axis_angle(
            up,
            yaw
        )

        # 画面上下ドラッグ → カメラRight軸まわり
        R_pitch = self._rotation_matrix_axis_angle(
            right,
            pitch
        )

        # カメラ基準でライト方向を回転
        self.realtime_sun_dir = (
            R_yaw @ R_pitch @ self.cur_sun_dir
        )

        self.realtime_sun_dir = (
            self.realtime_sun_dir / np.linalg.norm(self.realtime_sun_dir)
        )

        self.widget.scene.scene.set_sun_light(
            self.realtime_sun_dir.tolist(),
            [1.0, 1.0, 1.0],
            50000
        )

        print("realtime_sun_dir:", self.realtime_sun_dir)
        
    def _rotation_matrix_axis_angle(self, axis, angle):

        axis = np.asarray(axis, dtype=float)
        axis = axis / np.linalg.norm(axis)

        x, y, z = axis

        c = np.cos(angle)
        s = np.sin(angle)
        C = 1.0 - c

        return np.array([
            [c + x*x*C,     x*y*C - z*s, x*z*C + y*s],
            [y*x*C + z*s,   c + y*y*C,   y*z*C - x*s],
            [z*x*C - y*s,   z*y*C + x*s, c + z*z*C],
        ])
    
    def move_joint(self, node, direction):
        if node.joint.type == "rotate":

            node.joint_value += (
                direction * 50.0
            )

        elif node.joint.type == "linear":

            node.joint_value += (
                direction * 10.0
            )
        
        elif node.joint.type == "signal":
            node.joint_value = 1 if direction > 0 else 0

        self.refresh_model()
    
    def refresh_model(self):

        from core.model_builder import (
            update_world_transform,
            collect_meshes,
        )

        for root in self.roots:
            update_world_transform(root)

        self.clear_scene()

        geometry_list = []

        for root in self.roots:
            collect_meshes(
                root,
                geometry_list
            )

        for i, (mesh, world_T) in enumerate(geometry_list):

            m = o3d.geometry.TriangleMesh(mesh)

            m.transform(world_T)
            m.compute_triangle_normals()

            name = f"model_{i}"

            self.widget.scene.add_geometry(
                name,
                m,
                self.material
            )

            self.geometry_names.append(name)