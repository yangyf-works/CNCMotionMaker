import copy
import json
from pathlib import Path
import numpy as np
import math

import open3d as o3d
import open3d.visualization.gui as gui # type: ignore
import open3d.visualization.rendering as rendering # type: ignore

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

        self.window.set_on_key(self._on_key)
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
        
        self.default_sun_dir = self.cur_sun_dir.copy()
        self.camera_fov = 60.0
        self.camera_fov_step = 5.0
        self.camera_pan_step = 1.0
        self._init_key_state()

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
    
    def _init_key_state(self):
        self.ctrl_down = False
        self.shift_down = False
        self.alt_down = False

    def _on_key(self, event):
        KEY_ALT = 256
        KEY_CTRL = 258
        KEY_SHIFT = 260
        if event.key == KEY_CTRL:
            self.ctrl_down = event.type == gui.KeyEvent.DOWN
            return True
        if event.key == KEY_ALT:
            self.alt_down = event.type == gui.KeyEvent.DOWN
            return True
        if event.key == KEY_SHIFT:
            self.shift_down = event.type == gui.KeyEvent.DOWN
            return True

        if event.type != gui.KeyEvent.DOWN:
            return False
        
        if self.ctrl_down:
            if event.key == gui.KeyName.LEFT:
                self.on_camera_roll(+5.0)   # CCW
            if event.key == gui.KeyName.RIGHT:
                self.on_camera_roll(-5.0)   # CW
            if event.key == gui.KeyName.UP:
                self.set_camera_fov(self.camera_fov - self.camera_fov_step)
            if event.key == gui.KeyName.DOWN:
                self.set_camera_fov(self.camera_fov + self.camera_fov_step)
            return True
        
        if event.key == gui.KeyName.LEFT:
            self.on_camera_pan(1, 0)
            return True

        if event.key == gui.KeyName.RIGHT:
            self.on_camera_pan(-1, 0)
            return True

        if event.key == gui.KeyName.UP:
            self.on_camera_pan(0, -1)
            return True

        if event.key == gui.KeyName.DOWN:
            self.on_camera_pan(0, 1)
            return True

        keymap = {
            gui.KeyName.R: self.on_reset_camera,
            gui.KeyName.S: self.on_save_stl,
            gui.KeyName.L: self.on_reset_light,
        }

        action = keymap.get(event.key)

        if action:
            action()
            return True

        return False
    
    def _on_mouse(self, event):
        alt = event.is_modifier_down(gui.KeyModifier.ALT)

        if event.type == gui.MouseEvent.Type.BUTTON_DOWN: 
            if event.is_button_down(gui.MouseButton.MIDDLE) or alt:
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
                direction * 1.0
            )

        elif node.joint.type == "linear":

            node.joint_value += (
                direction * 1.0
            )
        
        elif node.joint.type == "signal":
            node.joint_value = 1 if direction > 0 else 0

        gui.Application.instance.post_to_main_thread(
            self.window,
            self.refresh_model
        )
    
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
    
    def on_reset_camera(self):
        print("Reset Camera")

        bounds = self.widget.scene.bounding_box

        self.widget.setup_camera(
            60.0,
            bounds,
            bounds.get_center()
        )

    def on_save_stl(self):
        print("Save STL")
        self.export_current_model()


    def export_current_model(self):
        merged = o3d.geometry.TriangleMesh()

        for root in self.roots:
            self._collect_meshes_for_export(root, merged)

        if len(merged.vertices) == 0:
            print("No mesh found")
            return

        merged.compute_vertex_normals()

        filename = "export.stl"

        ok = o3d.io.write_triangle_mesh(
            filename,
            merged,
            write_ascii=False
        )

        if ok:
            print(f"Saved: {filename}")
        else:
            print("Save failed")


    def _collect_meshes_for_export(self, node, merged):
        for mesh in node.meshes:
            mesh_copy = copy.deepcopy(mesh)
            mesh_copy.transform(node.world_T)
            merged += mesh_copy

        for child in node.children:
            self._collect_meshes_for_export(child, merged)

    def on_reset_light(self):
        print("Reset Light")

        self.cur_sun_dir = self.default_sun_dir.copy()
        self.realtime_sun_dir = self.default_sun_dir.copy()

        self.widget.scene.scene.set_sun_light(
            self.cur_sun_dir,
            [1.0, 1.0, 1.0],
            100000
        )
        self.widget.scene.scene.enable_sun_light(True)
        self.widget.force_redraw()

    def on_camera_roll(self, angle_deg):
        camera = self.widget.scene.camera

        # camera-to-world 行列
        model = np.asarray(camera.get_model_matrix())

        # 現在のカメラ姿勢
        eye = model[:3, 3]
        right = model[:3, 0]
        up = model[:3, 1]
        backward = model[:3, 2]

        forward = -backward

        # 回転中心は SceneWidget の現在の回転中心を使う
        center = np.asarray(self.widget.center_of_rotation)

        angle = math.radians(angle_deg)

        # up/right を視線方向 forward まわりに回す
        up2 = self._rotate_vector(up, forward, angle)

        self.widget.look_at(center, eye, up2)
        self.widget.force_redraw()


    def _rotate_vector(self, v, axis, angle):
        axis = axis / np.linalg.norm(axis)

        return (
            v * math.cos(angle)
            + np.cross(axis, v) * math.sin(angle)
            + axis * np.dot(axis, v) * (1.0 - math.cos(angle))
        )
    
    def set_camera_fov(self, fov_deg):
        camera = self.widget.scene.camera

        model = np.asarray(camera.get_model_matrix())

        eye = model[:3, 3]
        up = model[:3, 1]
        center = np.asarray(self.widget.center_of_rotation)

        old_fov = self.camera_fov
        new_fov = max(5.0, min(90.0, float(fov_deg)))

        view_vec = eye - center
        old_dist = np.linalg.norm(view_vec)

        if old_dist <= 1e-9:
            return

        view_dir = view_vec / old_dist

        old_rad = math.radians(old_fov)
        new_rad = math.radians(new_fov)

        # 画面上の見かけサイズを維持するための距離補正
        new_dist = old_dist * math.tan(old_rad / 2.0) / math.tan(new_rad / 2.0)

        new_eye = center + view_dir * new_dist

        self.camera_fov = new_fov

        bounds = self.widget.scene.bounding_box

        self.widget.setup_camera(
            self.camera_fov,
            bounds,
            center
        )

        self.widget.look_at(center, new_eye, up)
        self.widget.force_redraw()

        print(f"Camera FOV: {self.camera_fov:.1f}, distance: {new_dist:.1f}")
    
    def on_camera_pan(self, dx, dy):
        camera = self.widget.scene.camera

        model = np.asarray(camera.get_model_matrix())

        eye = model[:3, 3]
        right = model[:3, 0]
        up = model[:3, 1]

        center = np.asarray(self.widget.center_of_rotation)

        pan_step = self.camera_pan_step

        move = right * dx * pan_step + up * dy * pan_step

        new_eye = eye + move
        new_center = center + move

        self.widget.look_at(new_center, new_eye, up)
        self.widget.center_of_rotation = new_center

        self.widget.force_redraw()