import json
import math
import time
import traceback
from pathlib import Path

import numpy as np
import open3d as o3d
import open3d.visualization.rendering as rendering  # type: ignore
from open3d.visualization import gui  # type: ignore

from core.chain_utils import build_chain_points_from_sprockets
from core.model_builder import (
    build_geometry_list_from_model_json,
    collect_export_meshes,
    collect_visible_meshes,
    update_all_world_transforms,
)


class SceneView:
    def __init__(
        self, window, 
        on_mouse_down= None,
        on_model_selected=None,
        default_camera_view="default"
        ):
        self.window = window
        self.default_camera_view = default_camera_view
        self.widget = gui.SceneWidget()

        self.widget.scene = rendering.Open3DScene(
            self.window.renderer
        )

        self.material = rendering.MaterialRecord()
        self.material.shader = "defaultLit"
        
        self.widget.scene.view.set_shadowing(False)
        self.widget.scene.set_background([0, 0, 0, 1])
        self.widget.scene.scene.enable_sun_light(True)

        self.model_geometries = []
        self.geometry_names = set()
        self.roots = []

        self.joint_axis_label_infos = []
        self.axis_geometries = []

        self.window.set_on_key(self._on_key)
        self.on_mouse_down = on_mouse_down
        self.widget.set_on_mouse(self._on_mouse)
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
        self.camera_fov_step = 5.0
        self.camera_pan_step = 10.0
        self._init_key_state()

        self.axis_geometry_names = []
        self.axis_material = rendering.MaterialRecord()
        self.axis_material.shader = "unlitLine"
        self.axis_material.line_width = 1.0

        self.show_axis = False
        self.joint_axis_labels = []

        self.on_model_selected = on_model_selected
        self.selected_joint = None
        self.selected_joint_node = None
        self.selected_joint_lock_T = None

        self.rotation_axis_length_ratio = 0.1
        self.rotation_axis_min_length = 1.0
        self.rotation_axis_probe_min = 1e-4
        self.rotation_arc_radius_ratio = 0.04

        self._last_click_time = 0.0
        self._last_click_pos = None

        self.double_click_interval = 0.3
        self.double_click_distance = 5

        self.on_marker_added = None
        self.on_clear_markers = None

        self.markers = {}

        self.marker_geometry_names = set()

        self.marker_material = rendering.MaterialRecord()
        self.marker_material.shader = "defaultLit"
        self.marker_material.base_color = [1.0, 0.0, 0.0, 1.0]
        self.marker_radius = 1.0

        self.initial_camera_state = None
        self._create_test_geometry()

    def get_node_path(self, target_node):
        result = None

        def walk(node, path):
            nonlocal result

            if node is target_node:
                result = tuple(path)
                return True

            for i, child in enumerate(
                getattr(node, "children", [])
            ):
                if walk(child, path + [i]):
                    return True

            return False

        for root_index, root in enumerate(self.roots):
            if walk(root, [root_index]):
                break

        return result

    def find_node_by_path(self, node_path):
        if not node_path:
            return None

        root_index = node_path[0]

        if root_index < 0 or root_index >= len(self.roots):
            return None

        node = self.roots[root_index]

        for child_index in node_path[1:]:
            children = getattr(node, "children", [])

            if child_index < 0 or child_index >= len(children):
                return None

            node = children[child_index]

        return node
        
    def add_marker(self, marker):
        marker_id = marker["id"]
        name = f"marker_{marker_id}"

        self.markers[marker_id] = marker

        if self.widget.scene.has_geometry(name):
            self.widget.scene.remove_geometry(name)

        sphere = o3d.geometry.TriangleMesh.create_sphere(
            radius=self.marker_radius,
            resolution=16,
        )

        sphere.compute_vertex_normals()
        sphere.paint_uniform_color([1.0, 0.0, 0.0])

        self.widget.scene.add_geometry(
            name,
            sphere,
            self.marker_material,
        )

        self.marker_geometry_names.add(name)

        self.update_marker(marker)
        self.widget.force_redraw()

    def update_marker(self, marker):
        name = f"marker_{marker['id']}"

        if not self.widget.scene.has_geometry(name):
            return

        node = self.find_node_by_path(
            marker["node_path"]
        )

        if node is None:
            return

        local_position = np.asarray(
            marker["local_position"],
            dtype=float,
        )

        display_T = (
            self.get_display_correction_T()
            @ node.world_T
        )

        p = np.array([
            local_position[0],
            local_position[1],
            local_position[2],
            1.0,
        ])

        display_position = (display_T @ p)[:3]

        T = np.eye(4)
        T[:3, 3] = display_position

        self.widget.scene.set_geometry_transform(
            name,
            T,
        )

    def update_markers(self):
        for marker in self.markers.values():
            self.update_marker(marker)

    def clear_markers(self):
        for name in list(self.marker_geometry_names):
            if self.widget.scene.has_geometry(name):
                self.widget.scene.remove_geometry(name)

        self.marker_geometry_names.clear()
        self.markers.clear()

        self.widget.force_redraw()

    def _create_test_geometry(self):
        axis = o3d.geometry.TriangleMesh.create_coordinate_frame(
            size=1.0
        )

        self.widget.scene.add_geometry(
            "axis",
            axis,
            self.material
        )

        self.geometry_names.add("axis")
        self.fit_camera_to_model(axis)
        self.save_initial_camera_state()

    def load_json_model(self, json_path: Path):
        try:
            self.clear_selected_joint(
                refresh=False,
                notify=False,
            )
            
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._build_model_from_json(data, json_path)
            self.refresh_model()

            self.rebuild_joint_axes()
            self.set_joint_axes_visible(self.show_axis)

            self.fit_camera_to_model()
            self.save_initial_camera_state()

            bbox = self.get_scene_bbox()
            scene_size = np.linalg.norm(bbox.get_extent())
            self.marker_radius = scene_size * 0.008

        except Exception:
            traceback.print_exc()

    def update_joint_axis_transforms(self):
        scene = self.widget.scene

        for info in self.axis_geometries:
            name = info["name"]
            node = info["node"]
            initial_display_T = info["initial_display_T"]

            if not scene.has_geometry(name):
                continue

            current_display_T = self.get_joint_axis_display_T(node)

            try:
                delta_T = current_display_T @ np.linalg.inv(initial_display_T)
            except np.linalg.LinAlgError:
                delta_T = np.eye(4)

            scene.set_geometry_transform(name, delta_T, )

    def set_joint_axes_visible(self, visible):
        scene = self.widget.scene

        for name in self.axis_geometry_names:
            if scene.has_geometry(name):
                scene.show_geometry(
                    name,
                    visible,
                )

        if visible:
            self.create_joint_axis_labels()
        else:
            self.clear_joint_axis_labels()

        self.widget.force_redraw()

    def clear_joint_axis_labels(self):
        for label in self.joint_axis_labels:
            self.widget.remove_3d_label(label)

        self.joint_axis_labels.clear()

    def create_joint_axis_labels(self):
        self.clear_joint_axis_labels()

        for info in self.joint_axis_label_infos:
            position = info["position"].copy()
            node = info.get("node")

            if node is not None:
                current_display_T = self.get_joint_axis_display_T(node)
                initial_display_T = info["initial_display_T"]

                try:
                    delta_T = (
                        current_display_T
                        @ np.linalg.inv(initial_display_T)
                    )

                    position_h = np.append(position, 1.0)
                    position = (delta_T @ position_h)[:3]

                except np.linalg.LinAlgError:
                    pass

            label = self.widget.add_3d_label(
                position,
                info["text"],
            )

            color = info["color"]
            label.color = gui.Color(
                color[0],
                color[1],
                color[2],
                1.0,
            )

            self.joint_axis_labels.append(label)

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
        modifier_map = {
            gui.KeyName.LEFT_CONTROL: "ctrl_down",
            gui.KeyName.RIGHT_CONTROL: "ctrl_down",
            gui.KeyName.ALT: "alt_down",
            gui.KeyName.LEFT_SHIFT: "shift_down",
            gui.KeyName.RIGHT_SHIFT: "shift_down",
        }

        if event.key in modifier_map:
            setattr(
                self,
                modifier_map[event.key],
                event.type == gui.KeyEvent.DOWN
            )
            return True

        if event.type != gui.KeyEvent.DOWN:
            return False
        
        ctrlkeymap = {
            gui.KeyName.A: self.switch_show_joint_axes,
            gui.KeyName.C: self.on_reset_camera,
            gui.KeyName.S: self.on_save_stl,
            gui.KeyName.L: self.on_reset_light,
            gui.KeyName.R: self.request_clear_markers,
            gui.KeyName.UP: lambda: self.on_camera_zoom(+1),
            gui.KeyName.DOWN: lambda: self.on_camera_zoom(-1),
            gui.KeyName.LEFT: lambda: self.set_camera_fov(-self.camera_fov_step),
            gui.KeyName.RIGHT:lambda: self.set_camera_fov(self.camera_fov_step),
        }
        shiftkeymap = {
        }

        if self.ctrl_down or self.shift_down or self.alt_down :
            action = ctrlkeymap.get(event.key) 
            if self.ctrl_down and action:
                action()
                return True
            action = shiftkeymap.get(event.key) 
            if self.shift_down and action:
                action()
                return True
            if self.alt_down and action:
                return True
            return True
                
        keymap = {
            gui.KeyName.A: lambda: self.on_camera_pan(1, 0),
            gui.KeyName.D: lambda: self.on_camera_pan(-1, 0),
            gui.KeyName.W: lambda: self.on_camera_pan(0, -1),
            gui.KeyName.S: lambda: self.on_camera_pan(0, 1),
            gui.KeyName.Q: lambda: self.on_camera_roll(+5.0),
            gui.KeyName.E: lambda: self.on_camera_roll(-5.0),
            gui.KeyName.LEFT: lambda:self.on_camera_orbit(1, 0),
            gui.KeyName.RIGHT:lambda:self.on_camera_orbit(-1, 0),
            gui.KeyName.UP:   lambda:self.on_camera_orbit(0, 1),
            gui.KeyName.DOWN: lambda:self.on_camera_orbit(0, -1),
        }

        action = keymap.get(event.key)
        if action:
            action()
            return True

        return False
    
    def _on_mouse(self, event):
        alt = event.is_modifier_down(gui.KeyModifier.ALT)
        ctrl = event.is_modifier_down(gui.KeyModifier.CTRL)
        shift = event.is_modifier_down(gui.KeyModifier.SHIFT)

        if event.type == gui.MouseEvent.Type.BUTTON_DOWN:
            if self.on_mouse_down is not None:
                self.on_mouse_down()
            if (
                event.is_button_down(gui.MouseButton.LEFT)
                and shift
                and self._is_double_click(event)
            ):
                if self.pick_model(event.x, event.y) is None:
                    self.clear_selected_joint()

                return gui.Widget.EventCallbackResult.CONSUMED

            if (event.is_button_down(gui.MouseButton.LEFT)
                and ctrl
                and self._is_double_click(event)
            ):
                self.pick_marker_position(event.x, event.y)

                return gui.Widget.EventCallbackResult.CONSUMED

            if (event.is_button_down(gui.MouseButton.MIDDLE) or alt):
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
    
    def request_clear_markers(self):
        if self.on_clear_markers is not None:
            self.on_clear_markers()

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

        print(f"dx {dx} dy {dy} realtime_sun_dir {self.realtime_sun_dir}")
        
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
    
    def move_joint(self, node, amount):
        if node.joint.type == "rotate":
            node.joint_value += amount * 1.0

        elif node.joint.type == "linear":
            node.joint_value += amount * 1.0

        elif node.joint.type == "chain":
            node.joint_value += amount

        elif node.joint.type == "signal":
            node.joint_value = 1 if amount > 0 else 0

        model_reset = node.joint.type == "signal"
        gui.Application.instance.post_to_main_thread(
            self.window,
            lambda:self.refresh_model(model_reset)
        )

    def get_display_correction_T(self):
        if (
            self.selected_joint_node is None
            or self.selected_joint_lock_T is None
        ):
            return np.eye(4)

        try:
            return (
                self.selected_joint_lock_T
                @ np.linalg.inv(
                    self.selected_joint_node.world_T
                )
            )
        except np.linalg.LinAlgError:
            return np.eye(4)
        
    def refresh_model(self, model_reset=True):
        update_all_world_transforms(self.roots)
        correction_T = self.get_display_correction_T()

        if model_reset:
            self.clear_model_geometries()

            geometry_list = collect_visible_meshes(self.roots)
            for i, item in enumerate(geometry_list):
                node = item["node"]
                mesh = item["mesh"]
                world_T = item["world_T"]
                display_T = correction_T @ world_T

                m = o3d.geometry.TriangleMesh(mesh)
                m.compute_triangle_normals()

                name = f"model_{i}"
                self.widget.scene.add_geometry(
                    name,
                    m,
                    self.material
                )

                self.widget.scene.set_geometry_transform(name, display_T)
                self.geometry_names.add(name)
                self.model_geometries.append(
                    {
                        "name": name,
                        "node": node,
                        "mesh": mesh,
                    }
                )

        else:
            if not self.model_geometries:
                return self.refresh_model(model_reset=True)

            geometry_list = collect_visible_meshes(self.roots)

            if len(geometry_list) != len(self.model_geometries):
                return self.refresh_model(model_reset=True)

            for i, item in enumerate(geometry_list):
                world_T = item["world_T"]
                display_T = correction_T @ world_T

                geometry_info = self.model_geometries[i]
                name = geometry_info["name"]

                if name not in self.geometry_names:
                    return self.refresh_model(model_reset=True)

                self.widget.scene.set_geometry_transform(name, display_T)

        self.update_joint_axis_transforms()

        if self.show_axis:
            self.create_joint_axis_labels()

        self.update_markers()

        self.widget.force_redraw()

    def clear_model_geometries(self):
        if self.widget.scene.has_geometry("axis"):
            self.widget.scene.remove_geometry("axis")
            
        for item in self.model_geometries:
            name = item["name"]

            if self.widget.scene.has_geometry(name):
                self.widget.scene.remove_geometry(name)

            self.geometry_names.discard(name)

        self.model_geometries.clear()

    def get_joint_axis_display_T(self, node):
        return (
            self.get_display_correction_T()
            @ node.world_T
        )

    def save_initial_camera_state(self):
        camera = self.widget.scene.camera
        model = np.asarray(camera.get_model_matrix(), dtype=float)

        self.initial_camera_state = {
            "eye": model[:3, 3].copy(),
            "up": model[:3, 1].copy(),
            "center": np.asarray(
                self.widget.center_of_rotation,
                dtype=float,
            ).copy(),
            "fov": float(
                camera.get_field_of_view()
            ),
        }

    def restore_initial_camera_state(self):
        state = self.initial_camera_state

        if state is None:
            return

        eye = state["eye"].copy()
        center = state["center"].copy()
        up = state["up"].copy()
        fov = state["fov"]

        if self.roots:
            bounds = self.get_scene_bbox()
        else:
            bounds = self.widget.scene.bounding_box

        self.widget.setup_camera(
            fov,
            bounds,
            center,
        )

        self.widget.center_of_rotation = center
        self.widget.look_at(
            center,
            eye,
            up,
        )

        self.widget.force_redraw()

    def fit_camera_to_model(self, geometry=None):
        if geometry is not None:
            bounds = self.widget.scene.bounding_box
        else:
            if not self.roots:
                return

            update_all_world_transforms(self.roots)
            bounds = self.get_scene_bbox()

        center = np.asarray(bounds.get_center(), dtype=float)
        self.widget.setup_camera(
            60.0,
            bounds,
            center
        )
        self.widget.center_of_rotation = center
        camera_model = np.asarray(self.widget.scene.camera.get_model_matrix(), dtype=float)

        current_eye = camera_model[:3, 3]
        distance = np.linalg.norm(current_eye - center)

        if distance <= 1e-9:
            distance = 1.0

        camera_settings = {
            "top": (
                np.array([0.0, 1.0, 0.0]),
                np.array([0.0, 0.0, -1.0]),
            ),
            "right": (
                np.array([1.0, 0.0, 0.0]),
                np.array([0.0, 1.0, 0.0]),
            ),
            "front": (
                np.array([0.0, 0.0, 1.0]),
                np.array([0.0, 1.0, 0.0]),
            ),
        }

        setting = camera_settings.get(self.default_camera_view)

        if setting is not None:
            direction, up = setting
            eye = center + direction * distance
        else:
            direction = np.array([1.0, 1.0, 1.0])
            up = np.array([0.0, 1.0, 0.0])

            direction /= np.linalg.norm(direction)
            eye = center + direction * distance * 1.2

        self.widget.look_at(
            center,
            eye,
            up,
        )

        self.widget.force_redraw()

    def on_reset_camera(self):
        self.restore_initial_camera_state()
        
    def on_save_stl(self):
        print("Save STL")
        merged = collect_export_meshes(self.roots)

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

        old_fov = self.widget.scene.camera.get_field_of_view()
        fov_deg += old_fov
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

        bounds = self.widget.scene.bounding_box

        self.widget.setup_camera(
            new_fov,
            bounds,
            center
        )

        self.widget.look_at(center, new_eye, up)
        self.widget.force_redraw()

        print(f"Camera FOV: {new_fov:.1f}, distance: {new_dist:.1f}")
    
    def on_camera_pan(self, dx, dy):
        dx_px = -dx * self.camera_pan_step
        dy_px = dy * self.camera_pan_step
        camera = self.widget.scene.camera

        model = np.asarray(camera.get_model_matrix())

        eye = model[:3, 3]
        up = model[:3, 1]
        center = np.asarray(self.widget.center_of_rotation)

        view_vec = center - eye
        dist = np.linalg.norm(view_vec)

        if dist <= 1e-9:
            return

        forward = view_vec / dist

        up_norm = np.linalg.norm(up)
        if up_norm <= 1e-9:
            return

        up = up / up_norm

        # カメラの右方向
        right = np.cross(forward, up)
        right_norm = np.linalg.norm(right)

        if right_norm <= 1e-9:
            return

        right = right / right_norm

        height = self.widget.frame.height
        if height <= 0:
            return

        fov_rad = math.radians(self.widget.scene.camera.get_field_of_view())

        # centerまでの距離で、画面1pxがワールドで何mm相当か計算
        view_height_world = 2.0 * dist * math.tan(fov_rad / 2.0)
        world_per_pixel = view_height_world / height

        move = (
            -right * dx_px * world_per_pixel
            + up * dy_px * world_per_pixel
        )

        new_eye = eye + move
        new_center = center + move

        # center_of_rotation も更新する
        self.widget.center_of_rotation = new_center

        self.widget.look_at(new_center, new_eye, up)
        self.widget.force_redraw()
    
    def on_camera_orbit(self, yaw_deg=0.0, pitch_deg=0.0):
        camera = self.widget.scene.camera
        model = np.asarray(camera.get_model_matrix())

        eye = model[:3, 3]
        up = model[:3, 1]
        right = model[:3, 0]

        center = np.asarray(self.widget.center_of_rotation)

        view_vec = eye - center
        dist = np.linalg.norm(view_vec)

        if dist <= 1e-9:
            return

        # 左右回転：画面上方向 up 軸まわり
        if abs(yaw_deg) > 1e-9:
            view_vec = self._rotate_vector(
                view_vec,
                up,
                math.radians(yaw_deg)
            )
            right = self._rotate_vector(
                right,
                up,
                math.radians(yaw_deg)
            )

        # 上下回転：画面右方向 right 軸まわり
        if abs(pitch_deg) > 1e-9:
            view_vec = self._rotate_vector(
                view_vec,
                right,
                math.radians(pitch_deg)
            )
            up = self._rotate_vector(
                up,
                right,
                math.radians(pitch_deg)
            )

        new_eye = center + view_vec

        self.widget.look_at(center, new_eye, up)
        self.widget.force_redraw()

    def on_camera_zoom(self, direction):
        camera = self.widget.scene.camera
        model = np.asarray(camera.get_model_matrix())

        eye = model[:3, 3]
        up = model[:3, 1]
        center = np.asarray(self.widget.center_of_rotation)

        view_vec = eye - center
        dist = np.linalg.norm(view_vec)

        if dist <= 1e-9:
            return

        view_dir = view_vec / dist

        zoom_rate = 0.90

        if direction > 0:
            # ズームイン
            new_dist = dist * zoom_rate
        else:
            # ズームアウト
            new_dist = dist / zoom_rate

        new_eye = center + view_dir * new_dist

        self.widget.look_at(center, new_eye, up)
        self.widget.force_redraw()
    
    def iter_joint_nodes(self):
        def walk(node):
            if getattr(node, "joint", None) is not None:
                yield node

            for child in getattr(node, "children", []):
                yield from walk(child)

        for root in self.roots:
            yield from walk(root)
    
    def switch_show_joint_axes(self):
        self.show_axis = not self.show_axis
        self.set_joint_axes_visible(self.show_axis)

    def get_node_bbox(self, node):
        correction_T = self.get_display_correction_T()
        bbox = None

        for item in collect_visible_meshes([node]):
            mesh_world = o3d.geometry.TriangleMesh(item["mesh"])

            display_T = correction_T @ item["world_T"]
            mesh_world.transform(display_T)

            mesh_bbox = mesh_world.get_axis_aligned_bounding_box()

            if bbox is None:
                bbox = mesh_bbox
            else:
                bbox += mesh_bbox

        return bbox
                
    def clear_joint_axes(self):
        scene = self.widget.scene

        for name in self.axis_geometry_names:
            if scene.has_geometry(name):
                scene.remove_geometry(name)

        self.axis_geometry_names.clear()
        self.axis_geometries.clear()

        self.clear_joint_axis_labels()
        self.joint_axis_label_infos.clear()

    def get_joint_axis_info(self, node, joint):
        axis = getattr(joint, "axis", None)
        joint_type = getattr(joint, "type", None)
        pivot = np.asarray(
            getattr(joint, "pivot", [0, 0, 0]),
            dtype=float,
        )

        local_axis = np.asarray(
            axis if axis is not None else [0, 0, 1],
            dtype=float,
        )

        norm = np.linalg.norm(local_axis)
        if norm < 1e-9:
            return None, None

        local_axis /= norm

        display_T = self.get_joint_axis_display_T(node)
        direction = display_T[:3, :3] @ local_axis
        direction_norm = np.linalg.norm(direction)
        if direction_norm < 1e-9:
            return None, None
        direction /= direction_norm

        if joint_type == "rotate":
            origin = display_T[:3, 3] + display_T[:3, :3] @ pivot
        else:
            origin = display_T[:3, 3]

        return origin, direction
    
    def get_joint_axis_color(self, joint):
        joint_type = getattr(joint, "type", "")

        if joint_type == "linear":
            return (0.2, 0.8, 1.0)   # 水色
        if joint_type == "rotate":
            return (1.0, 0.5, 0.0)   # オレンジ
        if joint_type == "chain":
            return (0.2, 0.8, 0.1)   # 緑

        return (0.8, 0.8, 0.8)       # その他
    
    def create_axis_line(
            self, 
            axis_type, 
            origin, 
            direction, 
            bbox, 
            color=(1, 0, 0), 
            type="infinite", 
            name=None, 
            label=None,
            node=None,
        ):
        origin = np.asarray(origin, dtype=float)
        direction = np.asarray(direction, dtype=float)

        direction_norm = np.linalg.norm(direction)
        if direction_norm <= 1e-9:
            return None

        direction /= direction_norm

        min_bound = bbox.min_bound
        max_bound = bbox.max_bound

        def get_intersection_points(line_origin):
            t_values = []

            for i in range(3):
                if abs(direction[i]) < 1e-9:
                    continue

                t1 = (min_bound[i] - line_origin[i]) / direction[i]
                t2 = (max_bound[i] - line_origin[i]) / direction[i]
                t_values.extend([t1, t2])

            intersection_points = []

            for t in t_values:
                point = line_origin + direction * t

                if np.all(point >= min_bound - 1e-6) and np.all(
                    point <= max_bound + 1e-6
                ):
                    intersection_points.append((t, point))

            return intersection_points
        
        points = get_intersection_points(origin)

        if len(points) < 2:
            origin = bbox.get_center()
            points = get_intersection_points(origin)

        if len(points) < 2:
            return None

        points.sort(key=lambda item: item[0])

        negative_surface = points[0][1]
        positive_surface = points[-1][1]

        scene_size = np.linalg.norm(bbox.get_extent())
        outside_length = max(scene_size * 0.2, 1.0)
        label_offset = max(scene_size * 0.02, 0.2)
        label_position = np.asarray([0,0,0], dtype=float)

        if type == "plusinfinite":
            p1 = origin

            if positive_surface[1] >= negative_surface[1]:
                p2 = positive_surface
                label_direction = direction
            else:
                p2 = negative_surface
                label_direction = -direction

            label_position = p2 + label_direction * label_offset

        elif type == "plusonly":
            p1 = positive_surface
            p2 = positive_surface + direction * outside_length
            label_position = p2 + direction * label_offset

        elif type == "minusonly":
            p1 = negative_surface
            p2 = negative_surface - direction * outside_length
            label_position = p2 - direction * label_offset
        
        else:
            p1 = negative_surface
            p2 = positive_surface
            label_position = p2

        if (
            not np.all(np.isfinite(p1))
            or not np.all(np.isfinite(p2))
            or np.linalg.norm(p2 - p1) <= 1e-6
        ):
            return None

        if label is not None:
            self.joint_axis_label_infos.append(
                {
                    "position": np.asarray(
                        label_position,
                        dtype=float,
                    ).copy(),
                    "text": label,
                    "color": tuple(color),
                    "node": node,
                    "initial_display_T": (
                        self.get_joint_axis_display_T(node).copy()
                        if node is not None
                        else np.eye(4)
                    ),
                }
            )

        line = o3d.geometry.LineSet()
        line.points = o3d.utility.Vector3dVector([p1, p2])
        line.lines = o3d.utility.Vector2iVector([[0, 1]])
        line.colors = o3d.utility.Vector3dVector([color])
        
        self.widget.scene.add_geometry(
            name,
            line,
            self.axis_material,
        )

        self.axis_geometry_names.append(name)

        if node is not None:
            self.axis_geometries.append(
                {
                    "name": name,
                    "node": node,
                    "initial_display_T": (
                        self.get_joint_axis_display_T(node).copy()
                    ),
                }
            )

        if axis_type == "rotate":
            scene_size = np.linalg.norm(bbox.get_extent())
            arc_radius = scene_size * 0.04

            self.create_rotation_direction_arc(
                name=f"{name}_rot_dir1",
                center=p1,
                axis_dir=direction,
                radius=arc_radius,
                color=color,
                node=node,
            )
            self.create_rotation_direction_arc(
                name=f"{name}_rot_dir2",
                center=p2,
                axis_dir=direction,
                radius=arc_radius,
                color=color,
                node=node,
            )

    def create_rotation_direction_arc(self, name, center, axis_dir, radius, color=(1, 0, 0), angle_deg=90, segments=12, node=None,):
        center = np.asarray(center, dtype=float)
        axis_dir = np.asarray(axis_dir, dtype=float)

        norm = np.linalg.norm(axis_dir)
        if norm == 0:
            return

        axis_dir = axis_dir / norm

        # axis_dir に直交する2方向を作る
        tmp = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(axis_dir, tmp)) > 0.9:
            tmp = np.array([0.0, 1.0, 0.0])

        u = np.cross(axis_dir, tmp)
        u = u / np.linalg.norm(u)

        v = np.cross(axis_dir, u)
        v = v / np.linalg.norm(v)

        angle_rad = np.deg2rad(angle_deg)

        points = []
        for i in range(segments + 1):
            t = angle_rad * i / segments
            p = center + radius * (np.cos(t) * u + np.sin(t) * v)
            points.append(p)

        lines = []
        for i in range(len(points) - 1):
            lines.append([i, i + 1])

        # 矢印の先端っぽい2本線
        end = points[-1]
        prev = points[-2]
        tangent = end - prev
        tangent = tangent / np.linalg.norm(tangent)

        arrow_len = radius * 0.4

        arrow_p1 = end - tangent * arrow_len + axis_dir * arrow_len
        arrow_p2 = end - tangent * arrow_len - axis_dir * arrow_len

        end_index = len(points) - 1
        base_index = len(points)
        points.append(arrow_p1)
        points.append(arrow_p2)

        lines.append([end_index, base_index])
        lines.append([end_index, base_index + 1])

        line_set = o3d.geometry.LineSet()
        line_set.points = o3d.utility.Vector3dVector(points)
        line_set.lines = o3d.utility.Vector2iVector(lines)
        line_set.colors = o3d.utility.Vector3dVector([color for _ in lines])

        self.widget.scene.add_geometry(
            name,
            line_set,
            self.axis_material,
        )

        self.axis_geometry_names.append(name)
        if node is not None:
            self.axis_geometries.append(
                {
                    "name": name,
                    "node": node,
                    "initial_display_T": (
                        self.get_joint_axis_display_T(node).copy()
                    ),
                }
            )
        
    def get_scene_bbox(self):
        correction_T = self.get_display_correction_T()
        bbox = None

        for item in collect_visible_meshes(self.roots):
            mesh_world = o3d.geometry.TriangleMesh(
                item["mesh"]
            )

            display_T = correction_T @ item["world_T"]
            mesh_world.transform(display_T)
            mesh_bbox = mesh_world.get_axis_aligned_bounding_box()

            if bbox is None:
                bbox = mesh_bbox
            else:
                bbox += mesh_bbox

        if bbox is None:
            return o3d.geometry.AxisAlignedBoundingBox(
                min_bound=[-50, -50, -50],
                max_bound=[50, 50, 50],
            )

        return bbox
            
    def create_chain_axis_lineset(self, points, loop=True, color=(1.0, 0.6, 0.0)):
        if points is None or len(points) < 2:
            return None

        lines = []

        for i in range(len(points) - 1):
            lines.append([i, i + 1])

        if loop:
            lines.append([len(points) - 1, 0])

        line_set = o3d.geometry.LineSet()
        line_set.points = o3d.utility.Vector3dVector(points)
        line_set.lines = o3d.utility.Vector2iVector(lines)
        line_set.colors = o3d.utility.Vector3dVector(
            [color for _ in lines]
        )

        return line_set
    
    def draw_chain_axis(self, node, color, label=None):
        joint = node.joint

        if joint is None or joint.type != "chain" or not joint.sprockets:
            return

        points = build_chain_points_from_sprockets(
            joint.sprockets,
            loop=joint.loop,
            arc_step_deg=5.0,
        )

        line_set = self.create_chain_axis_lineset(
            points,
            loop=joint.loop,
            color=color,
        )

        if line_set is None:
            return
        
        display_T = (
            self.get_display_correction_T()
            @ node.world_T
        )

        line_set.transform(display_T)

        geom_name = f"axis_chain_{joint.name or node.name}"
        if self.widget.scene.has_geometry(geom_name):
            self.widget.scene.remove_geometry(geom_name)

        self.widget.scene.add_geometry(
            geom_name,
            line_set,
            self.axis_material,
        )
        
        self.axis_geometry_names.append(geom_name)
        self.axis_geometries.append(
            {
                "name": geom_name,
                "node": node,
                "initial_display_T": (
                    self.get_joint_axis_display_T(node).copy()
                ),
            }
        )

        label_text = label or joint.name or node.name

        world_points = np.asarray(line_set.points)

        if len(world_points) > 0:
            self.joint_axis_label_infos.append(
                {
                    "position": world_points.mean(axis=0).copy(),
                    "text": label_text,
                    "color": tuple(color),
                    "node": node,
                    "initial_display_T": (
                        self.get_joint_axis_display_T(node).copy()
                    ),
                }
            )
    
    def set_joint_value_by_name(self, axis_name, value):
        for node in self.iter_joint_nodes():
            joint = node.joint

            if joint is None:
                continue

            if joint.name != axis_name:
                continue

            new_value = float(value)

            if joint.type == "signal":
                changed = (node.joint_value != new_value)
                node.joint_value = new_value
                return changed

            node.joint_value = new_value
            return False

        print(f"Axis not found: {axis_name}")
        return False
    
    def _is_double_click(self, event):
        now = time.monotonic()
        pos = np.array([event.x, event.y], dtype=float)

        is_double = False

        if self._last_click_pos is not None:
            elapsed = now - self._last_click_time
            distance = np.linalg.norm(pos - self._last_click_pos)

            is_double = (
                elapsed <= self.double_click_interval
                and distance <= self.double_click_distance
            )

        if is_double:
            self._last_click_time = 0.0
            self._last_click_pos = None
        else:
            self._last_click_time = now
            self._last_click_pos = pos

        return is_double
    
    def pick_marker_position(
        self,
        mouse_x,
        mouse_y,
    ):
        frame = self.widget.frame

        local_x = int(mouse_x - frame.x)
        local_y = int(mouse_y - frame.y)

        width = int(frame.width)
        height = int(frame.height)

        if (
            width <= 0
            or height <= 0
            or local_x < 0
            or local_y < 0
            or local_x >= width
            or local_y >= height
        ):
            return None

        selectable_meshes = collect_visible_meshes(
            self.roots
        )

        if not selectable_meshes:
            return None

        ray_scene = o3d.t.geometry.RaycastingScene()
        geometry_id_to_item = {}

        correction_T = self.get_display_correction_T()

        for item in selectable_meshes:
            mesh_world = o3d.geometry.TriangleMesh(
                item["mesh"]
            )

            display_T = (
                correction_T
                @ item["world_T"]
            )

            mesh_world.transform(display_T)

            if len(mesh_world.triangles) == 0:
                continue

            tensor_mesh = (
                o3d.t.geometry.TriangleMesh.from_legacy(
                    mesh_world
                )
            )

            geometry_id = ray_scene.add_triangles(
                tensor_mesh
            )

            geometry_id_to_item[
                int(geometry_id)
            ] = item

        if not geometry_id_to_item:
            return None

        camera = self.widget.scene.camera

        camera_model = np.asarray(
            camera.get_model_matrix(),
            dtype=np.float64,
        )

        eye = camera_model[:3, 3]

        world_point = np.asarray(
            camera.unproject(
                local_x + 0.5,
                local_y + 0.5,
                0.5,
                width,
                height,
            ),
            dtype=np.float64,
        )

        ray_direction = world_point - eye

        length = np.linalg.norm(
            ray_direction
        )

        if (
            not np.all(np.isfinite(eye))
            or not np.all(
                np.isfinite(world_point)
            )
            or not np.isfinite(length)
            or length <= 1e-9
        ):
            return None

        ray_direction /= length

        ray = o3d.core.Tensor(
            [[
                eye[0],
                eye[1],
                eye[2],
                ray_direction[0],
                ray_direction[1],
                ray_direction[2],
            ]],
            dtype=o3d.core.Dtype.Float32,
        )

        result = ray_scene.cast_rays(ray)

        geometry_id = int(
            result["geometry_ids"][0].item()
        )

        invalid_id = (
            o3d.t.geometry.RaycastingScene.INVALID_ID
        )

        # ヒット無し
        if geometry_id == invalid_id:
            return None

        t_hit = float(
            result["t_hit"][0].item()
        )

        if not np.isfinite(t_hit):
            return None

        item = geometry_id_to_item.get(
            geometry_id
        )

        if item is None:
            return None

        # 画面表示座標上のヒット位置
        hit_position = (
            eye
            + ray_direction * t_hit
        )

        hit_node = item["node"]

        node_path = self.get_node_path(
            hit_node
        )

        if node_path is None:
            return None

        # Raycastに使用したものと同じTransform
        display_T = (
            correction_T
            @ item["world_T"]
        )

        try:
            inverse_T = np.linalg.inv(
                display_T
            )
        except np.linalg.LinAlgError:
            return None

        hit_h = np.array([
            hit_position[0],
            hit_position[1],
            hit_position[2],
            1.0,
        ])

        # ヒットモデルのローカル座標へ変換
        local_position = (
            inverse_T @ hit_h
        )[:3]

        if self.on_marker_added is not None:
            self.on_marker_added(
                node_path,
                local_position,
            )

        return {
            "node_path": node_path,
            "local_position": local_position,
        }
        
    def pick_model(self, mouse_x, mouse_y):
        frame = self.widget.frame

        local_x = int(mouse_x - frame.x)
        local_y = int(mouse_y - frame.y)

        width = int(frame.width)
        height = int(frame.height)

        if (width <= 0
            or height <= 0
            or local_x < 0
            or local_y < 0
            or local_x >= width
            or local_y >= height
        ):
            return None

        selectable_meshes = collect_visible_meshes(self.roots)

        if not selectable_meshes:
            return None

        ray_scene = o3d.t.geometry.RaycastingScene()
        geometry_id_to_item = {}
        correction_T = self.get_display_correction_T()

        for item in selectable_meshes:
            mesh_world = o3d.geometry.TriangleMesh(item["mesh"])
            display_T = (correction_T @ item["world_T"])
            mesh_world.transform(display_T)

            if len(mesh_world.triangles) == 0:
                continue

            tensor_mesh = (o3d.t.geometry.TriangleMesh.from_legacy(mesh_world))
            geometry_id = ray_scene.add_triangles(tensor_mesh)
            geometry_id_to_item[int(geometry_id)] = item

        if not geometry_id_to_item:
            return None

        camera = self.widget.scene.camera
        camera_model = np.asarray(
            camera.get_model_matrix(),
            dtype=np.float64,
        )
        eye = camera_model[:3, 3]
        world_point = np.asarray(
            camera.unproject(
                local_x + 0.5,
                local_y + 0.5,
                0.5,
                width,
                height,
            ),
            dtype=np.float64,
        )

        ray_direction = world_point - eye
        length = np.linalg.norm(ray_direction)

        if (not np.all(np.isfinite(eye))
            or not np.all(np.isfinite(world_point))
            or not np.isfinite(length)
            or length <= 1e-9
        ):
            print(
                "Invalid pick ray:",
                "eye =", eye,
                "world_point =", world_point,
                "length =", length,
            )
            return None

        ray_direction /= length

        ray = o3d.core.Tensor(
            [[
                eye[0],
                eye[1],
                eye[2],
                ray_direction[0],
                ray_direction[1],
                ray_direction[2],
            ]],
            dtype=o3d.core.Dtype.Float32,
        )

        result = ray_scene.cast_rays(ray)
        geometry_id = int(result["geometry_ids"][0].item())
        invalid_id = o3d.t.geometry.RaycastingScene.INVALID_ID
        if geometry_id == invalid_id:
            return None

        item = geometry_id_to_item.get(geometry_id)
        if item is None:
            return None

        hit_node = item["node"]
        selected = self.find_nearest_joint(hit_node)
        if selected is None:
            return None
        
        joint_node, joint = selected
        self.selected_joint = joint
        self.selected_joint_node = joint_node
        self.selected_joint_lock_T = joint_node.world_T.copy()

        self.refresh_model(model_reset=False)

        print(
            f"Selected joint: {self.selected_joint.name} "
            f"({self.selected_joint.type})"
        )

        if self.on_model_selected is not None:
            self.on_model_selected(self.selected_joint)

        return self.selected_joint
  
    def find_nearest_joint(self, target_node):
        selectable_types = {
            "linear",
            "rotate",
        }

        result = None

        def walk(node, nearest=None):
            nonlocal result

            joint = node.joint

            if (
                joint is not None
                and joint.type in selectable_types
            ):
                nearest = (node, joint)

            if node is target_node:
                result = nearest
                return True

            for child in node.children:
                if walk(child, nearest):
                    return True

            return False

        for root in self.roots:
            if walk(root):
                break

        return result
    
    def clear_selected_joint(
        self,
        refresh=True,
        notify=True,
    ):
        had_selection = (
            self.selected_joint_node is not None
        )

        self.selected_joint = None
        self.selected_joint_node = None
        self.selected_joint_lock_T = None

        if refresh and had_selection and self.roots:
            self.refresh_model(False)

        if notify and self.on_model_selected is not None:
            self.on_model_selected(None)
    
    def build_axis_raycast_context(self):
        combined_scene = o3d.t.geometry.RaycastingScene()
        mesh_scenes = []

        correction_T = self.get_display_correction_T()

        for item in collect_visible_meshes(self.roots):
            mesh_world = o3d.geometry.TriangleMesh(item["mesh"])

            display_T = correction_T @ item["world_T"]
            mesh_world.transform(display_T)

            if len(mesh_world.vertices) == 0:
                continue

            if len(mesh_world.triangles) == 0:
                continue

            tensor_mesh = o3d.t.geometry.TriangleMesh.from_legacy(
                mesh_world
            )

            combined_scene.add_triangles(tensor_mesh)

            mesh_scene = o3d.t.geometry.RaycastingScene()
            mesh_scene.add_triangles(tensor_mesh)
            mesh_scenes.append(mesh_scene)

        scene_bbox = self.get_scene_bbox()
        scene_size = float(np.linalg.norm(scene_bbox.get_extent()))

        return {
            "combined_scene": combined_scene,
            "mesh_scenes": mesh_scenes,
            "scene_size": max(scene_size, 1.0),
        }
    
    def is_point_inside_any_mesh(
        self,
        point,
        mesh_scenes,
    ):
        point = np.asarray(point, dtype=np.float32)

        query = o3d.core.Tensor(
            point.reshape(1, 3),
            dtype=o3d.core.Dtype.Float32,
        )

        for scene in mesh_scenes:
            occupancy = scene.compute_occupancy(query)

            if float(occupancy[0].item()) > 0.5:
                return True

        return False

    def find_first_outside_intersection(
        self,
        origin,
        direction,
        raycast_context,
    ):
        origin = np.asarray(origin, dtype=np.float64)
        direction = np.asarray(direction, dtype=np.float64)

        direction_norm = np.linalg.norm(direction)
        if direction_norm <= 1e-9:
            return None

        direction /= direction_norm

        combined_scene = raycast_context["combined_scene"]
        mesh_scenes = raycast_context["mesh_scenes"]
        scene_size = raycast_context["scene_size"]
        axis_length = self.get_rotation_axis_length(scene_size)

        if not mesh_scenes:
            return None

        ray = o3d.core.Tensor(
            [[
                origin[0],
                origin[1],
                origin[2],
                direction[0],
                direction[1],
                direction[2],
            ]],
            dtype=o3d.core.Dtype.Float32,
        )

        intersections = combined_scene.list_intersections(ray)

        if "t_hit" not in intersections:
            return None

        t_hits = np.asarray(
            intersections["t_hit"].numpy(),
            dtype=np.float64,
        ).reshape(-1)

        t_hits = t_hits[
            np.isfinite(t_hits)
            & (t_hits > 1e-6)
        ]

        if len(t_hits) == 0:
            return None

        t_hits.sort()

        merge_epsilon = max(scene_size * 1e-7, 1e-5)
        unique_t_hits = []

        for t in t_hits:
            if (
                not unique_t_hits
                or abs(t - unique_t_hits[-1]) > merge_epsilon
            ):
                unique_t_hits.append(float(t))

        for i, t_hit in enumerate(unique_t_hits):
            if i + 1 < len(unique_t_hits):
                next_t = unique_t_hits[i + 1]
            else:
                next_t = t_hit + scene_size

            segment_length = next_t - t_hit

            if segment_length <= axis_length:
                continue

            # セグメントの中心点
            segment_center_t = (t_hit + next_t) * 0.5
            segment_center = (
                origin
                + direction * segment_center_t
            )

            inside = self.is_point_inside_any_mesh(
                segment_center,
                mesh_scenes,
            )

            # この交点の後ろにあるセグメントが外部
            if not inside:
                hit_point = origin + direction * t_hit
                return hit_point

        return None

    def rebuild_joint_axes(self):
        self.clear_joint_axes()

        update_all_world_transforms(self.roots)

        scene_bbox = self.get_scene_bbox()
        raycast_context = self.build_axis_raycast_context()

        for node in self.iter_joint_nodes():
            joint = node.joint
            origin, direction = self.get_joint_axis_info(node, joint)

            if origin is None or direction is None:
                continue

            color = self.get_joint_axis_color(joint)
            label_text = joint.name if joint.name else node.name

            match joint.type:
                case "rotate":
                    bbox = self.get_node_bbox(node)
                    if bbox is None:
                        continue

                    reverse_arrow = False
                    draw_direction = direction.copy()

                    if np.dot(draw_direction, [0.0, 1.0, 0.0]) < 0:
                        draw_direction = -draw_direction
                        reverse_arrow = True

                    bbox_points = np.asarray(
                        bbox.get_box_points(),
                        dtype=float,
                    )

                    # 回転軸方向に対して最もマイナス側のBBox頂点
                    projection_values = bbox_points @ draw_direction
                    minus_point = bbox_points[np.argmin(projection_values)]

                    # minus側の点を本来の回転軸へ投影
                    ray_origin = (
                        origin
                        + draw_direction
                        * np.dot(
                            minus_point - origin,
                            draw_direction,
                        )
                    )

                    axis_start = self.find_first_outside_intersection(
                        origin=ray_origin,
                        direction=draw_direction,
                        raycast_context=raycast_context,
                    )

                    self.create_rotation_axis_line(
                        name=f"joint_axis_{node.name}",
                        origin=ray_origin,
                        direction=draw_direction,
                        start=axis_start,
                        bbox=scene_bbox,
                        color=color,
                        label=label_text,
                        node=node,
                        reverse_arrow=reverse_arrow,
                    )

                case "linear":
                    bbox = self.get_node_bbox(node)
                    if bbox is None:
                        continue

                    self.create_axis_line(
                        name=f"joint_axis_{node.name}_minus",
                        axis_type=joint.type,
                        origin=origin,
                        direction=direction,
                        bbox=bbox,
                        color=color,
                        type="minusonly",
                        label=f"-{label_text}",
                        node=node,
                    )

                    self.create_axis_line(
                        name=f"joint_axis_{node.name}_plus",
                        axis_type=joint.type,
                        origin=origin,
                        direction=direction,
                        bbox=bbox,
                        color=[1.0 - c for c in color],
                        type="plusonly",
                        label=f"+{label_text}",
                        node=node,
                    )

                case "chain":
                    self.draw_chain_axis(
                        node,
                        color,
                        label=label_text,
                    )

                case "signal":
                    continue

    def get_rotation_axis_length(self, scene_size):
        scene_size = max(float(scene_size), 1.0)

        return max(
            scene_size * self.rotation_axis_length_ratio,
            self.rotation_axis_min_length,
        )
        
    def create_rotation_axis_line(
        self,
        name,
        origin,
        direction,
        start,
        bbox,
        color=(1.0, 0.5, 0.0),
        label=None,
        node=None,
        reverse_arrow=False,
    ):
        origin = np.asarray(origin, dtype=float)
        direction = np.asarray(direction, dtype=float)

        direction_norm = np.linalg.norm(direction)
        if direction_norm <= 1e-9:
            return None

        direction /= direction_norm

        scene_size = float(np.linalg.norm(bbox.get_extent()))
        scene_size = max(scene_size, 1.0)
        axis_length = self.get_rotation_axis_length(scene_size)

        # レイで有効な出口が見つからなかった場合のフォールバック
        if start is None:
            start = origin.copy()
        else:
            start = np.asarray(start, dtype=float)

        end = start + direction * axis_length

        if (
            not np.all(np.isfinite(start))
            or not np.all(np.isfinite(end))
            or np.linalg.norm(end - start) <= 1e-6
        ):
            return None

        line = o3d.geometry.LineSet()
        line.points = o3d.utility.Vector3dVector(
            [start, end]
        )
        line.lines = o3d.utility.Vector2iVector(
            [[0, 1]]
        )
        line.colors = o3d.utility.Vector3dVector(
            [color]
        )

        self.widget.scene.add_geometry(
            name,
            line,
            self.axis_material,
        )

        self.axis_geometry_names.append(name)

        initial_display_T = (
            self.get_joint_axis_display_T(node).copy()
            if node is not None
            else np.eye(4)
        )

        if node is not None:
            self.axis_geometries.append(
                {
                    "name": name,
                    "node": node,
                    "initial_display_T": initial_display_T,
                }
            )

        # ラベルは終点の少し先
        label_offset = max(scene_size * 0.02, 0.2)
        label_position = end + direction * label_offset

        if label is not None:
            self.joint_axis_label_infos.append(
                {
                    "position": label_position.copy(),
                    "text": label,
                    "color": tuple(color),
                    "node": node,
                    "initial_display_T": initial_display_T,
                }
            )

        # 回転方向表示は現在の処理をそのまま使用
        arc_radius = max(
            scene_size * self.rotation_arc_radius_ratio,
            1.0,
        )
        arrow_direction = -direction if reverse_arrow else direction

        self.create_rotation_direction_arc(
            name=f"{name}_rot_dir",
            center=end,
            axis_dir=arrow_direction,
            radius=arc_radius,
            color=color,
            node=node,
        )

        return {
            "start": start,
            "end": end,
        }