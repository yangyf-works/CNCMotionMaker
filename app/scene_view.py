import copy
import json
from pathlib import Path
import numpy as np
import math

import open3d as o3d
import open3d.visualization.gui as gui # type: ignore
import open3d.visualization.rendering as rendering # type: ignore

from core.model_builder import build_geometry_list_from_model_json, collect_export_meshes
from core.chain_utils import (
    build_chain_points_from_sprockets,
    get_carrier_positions,
)
from core.model_builder import (
    update_world_transform,
    collect_meshes,
)

import traceback

class SceneView:
    def __init__(self, window, 
                 on_mouse_down= None,
                 default_camera_view="default",):
        self.window = window
        self.default_camera_view = default_camera_view
        self.widget = gui.SceneWidget()

        self.widget.scene = rendering.Open3DScene(
            self.window.renderer
        )

        self.material = rendering.MaterialRecord()
        self.material.shader = "defaultLit"
        
        self.widget.scene.set_background([0, 0, 0, 1])
        self.widget.scene.scene.enable_sun_light(True)

        self.model_geometries = []
        self.geometry_names = set()

        self.roots = []
        self._create_test_geometry()

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
        self.on_reset_camera()

    def clear_scene(self):
        self.geometry_names.clear()
        self.model_geometries.clear()
        self.widget.scene.clear_geometry()

    def load_json_model(self, json_path: Path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._build_model_from_json(
                data,
                json_path
            )
            self.refresh_model()
            self.on_reset_camera()

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

        if event.type == gui.MouseEvent.Type.BUTTON_DOWN: 
            if self.on_mouse_down is not None:
                self.on_mouse_down()
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
    
    def refresh_model(self, model_reset=True):
        for root in self.roots:
            update_world_transform(root)

        if model_reset:
            self.clear_scene()
            geometry_list = []
            self.model_geometries = []

            for root in self.roots:
                collect_meshes(root, geometry_list)

            for i, (mesh, world_T) in enumerate(geometry_list):
                m = o3d.geometry.TriangleMesh(mesh)
                m.compute_triangle_normals()

                name = f"model_{i}"

                self.widget.scene.add_geometry(
                    name,
                    m,
                    self.material
                )

                self.widget.scene.set_geometry_transform(name, world_T)

                self.geometry_names.add(name)
                self.model_geometries.append((name, mesh))
        else:
            if not self.model_geometries:
                return self.refresh_model(model_reset=True)
            
            geometry_list = []

            for root in self.roots:
                collect_meshes(root, geometry_list)

            if len(geometry_list) != len(self.model_geometries):
                return self.refresh_model(model_reset=True)
            
            for i, (_, world_T) in enumerate(geometry_list):
                name, _mesh = self.model_geometries[i]

                if name not in self.geometry_names:
                    return self.refresh_model(model_reset=True)

                self.widget.scene.set_geometry_transform(name, world_T)

        if self.show_axis:
            self.show_joint_axes()
        else:
            self.clear_joint_axes()

    
    def on_reset_camera(self):
        if hasattr(self, "roots") and self.roots:
            for root in self.roots:
                update_world_transform(root)

            bounds = self.get_scene_bbox()
        else:
            bounds = self.widget.scene.bounding_box

        center = np.asarray(bounds.get_center(), dtype=float)
        self.widget.setup_camera(
            60.0,
            bounds,
            center
        )
        self.widget.center_of_rotation = center
        camera_model = np.asarray(self.widget.scene.camera.get_model_matrix())

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

            self.widget.look_at(
                center,
                eye,
                up
            )
        else:
            direction = np.array([1.0, 1.0, 1.0])
            up = np.array([0.0, 1.0, 0.0])
            eye = center + direction * distance * 0.7

            self.widget.look_at(
                center,
                eye,
                up
            )

        self.widget.force_redraw()

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

        if self.show_axis:
            self.show_joint_axes()
        else:
            self.clear_joint_axes()

    def show_joint_axes(self):
        self.clear_joint_axes()

        bbox = self.get_scene_bbox()

        for node in self.iter_joint_nodes():
            joint = node.joint

            origin, direction = self.get_joint_axis_info(node, joint)

            if origin is None or direction is None:
                continue

            color = self.get_joint_axis_color(joint)
            label_text = joint.name if joint.name else node.name

            match joint.type:
                case "rotate":
                    self.create_axis_line(
                        name=f"joint_axis_{node.name}",
                        axistype=joint.type,
                        origin=origin,
                        direction=direction,
                        bbox=bbox,
                        color=color,
                        label=label_text,
                    )

                case "linear":
                    self.create_axis_line(
                        name=f"joint_axis_{node.name}_plus",
                        axistype=joint.type,
                        origin=node.world_T[:3, 3],
                        direction=direction,
                        bbox=bbox,
                        color=color,
                        type="minusonly",
                        label=f"-{label_text}",
                    )

                    self.create_axis_line(
                        name=f"joint_axis_{node.name}_minus",
                        axistype=joint.type,
                        origin=node.world_T[:3, 3],
                        direction=direction,
                        bbox=bbox,
                        color=[1.0 - c for c in color],
                        type="plusonly",
                        label=f"+{label_text}",
                    )

                case "chain":
                    self.draw_chain_axis(node, color, label=label_text,)

                case "signal":
                    continue

                case _:
                    continue

    def clear_joint_axes(self):
        if not hasattr(self, "axis_geometry_names"):
            self.axis_geometry_names = []

        for name in self.axis_geometry_names:
            if self.widget.scene.scene.has_geometry(name):
                self.widget.scene.scene.remove_geometry(name)

        self.axis_geometry_names.clear()

        for label  in self.joint_axis_labels:
            self.widget.remove_3d_label(label )
        self.joint_axis_labels.clear()

    def get_joint_axis_info(self, node, joint):
        # 軸方向を取得
        axis = getattr(joint, "axis", None)
        type = getattr(joint, "type", None)
        pivot = getattr(joint, "pivot", np.array([0.0, 0.0, 0.0]))

        if axis is None:
            local_axis = np.array([0.0, 0.0, 1.0])
        else:
            local_axis = np.asarray(axis, dtype=float)

        norm = np.linalg.norm(local_axis)
        if norm < 1e-9:
            return None, None

        local_axis = local_axis / norm

        world_direction = node.world_T[:3, :3] @ local_axis

        norm = np.linalg.norm(world_direction)
        if norm < 1e-9:
            return None, None

        world_direction = world_direction / norm

        if type == "rotate":
            world_origin = node.world_T[:3, 3] + node.world_T[:3, :3] @ pivot
        else:
            world_origin = node.world_T[:3, 3]

        return world_origin, world_direction
    
    def get_joint_axis_color(self, joint):
        joint_type = getattr(joint, "type", "")

        if joint_type == "linear":
            return (0.2, 0.8, 1.0)   # 水色
        if joint_type == "rotate":
            return (1.0, 0.5, 0.0)   # オレンジ
        if joint_type == "chain":
            return (0.2, 0.8, 0.1)   # 緑

        return (0.8, 0.8, 0.8)       # その他
    
    def create_axis_line(self, axistype, origin, direction, bbox, color=(1, 0, 0), type="infinite", name=None, label=None,):
        origin = np.asarray(origin, dtype=float)
        direction = np.asarray(direction, dtype=float)

        min_bound = bbox.min_bound
        max_bound = bbox.max_bound

        t_values = []

        for i in range(3):
            if abs(direction[i]) < 1e-9:
                continue

            t1 = (min_bound[i] - origin[i]) / direction[i]
            t2 = (max_bound[i] - origin[i]) / direction[i]
            t_values.extend([t1, t2])

        points = []

        for t in t_values:
            p = origin + direction * t

            if np.all(p >= min_bound - 1e-6) and np.all(
                p <= max_bound + 1e-6
            ):
                points.append((t, p))

        if len(points) < 2:
            return None

        points.sort(key=lambda x: x[0])

        if type == "infinite":
            p1 = points[0][1]
            p2 = points[-1][1]
        elif type == "plusonly":
            p1 = origin
            p2 = points[-1][1]
        elif type == "minusonly":
            p1 = origin
            p2 = points[0][1]

        if label is not None:
            label_pos = p2
            label = self.widget.add_3d_label(label_pos, label)
            label.color = gui.Color(color[0], color[1], color[2], 1.0)

            self.joint_axis_labels.append(label)

        line = o3d.geometry.LineSet()
        line.points = o3d.utility.Vector3dVector([p1, p2])
        line.lines = o3d.utility.Vector2iVector([[0, 1]])
        line.colors = o3d.utility.Vector3dVector([color])
        
        self.widget.scene.scene.add_geometry(
            name,
            line,
            self.axis_material,
        )

        self.axis_geometry_names.append(name)

        if axistype == "rotate":
            scene_size = np.linalg.norm(bbox.get_extent())
            arc_radius = scene_size * 0.04

            self.create_rotation_direction_arc(
                name=f"joint_axis_{name}_rot_dir",
                center=p2,
                axis_dir=direction,
                radius=arc_radius,
                color=color,
            )

    def create_rotation_direction_arc(self, name, center, axis_dir, radius, color=(1, 0, 0), angle_deg=270, segments=48,):
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

        self.widget.scene.scene.add_geometry(
            name,
            line_set,
            self.axis_material,
        )

        self.axis_geometry_names.append(name)
        
    def get_scene_bbox(self):
        bboxes = []

        for root in self.roots:
            self._collect_bboxes(root, bboxes)

        if not bboxes:
            return o3d.geometry.AxisAlignedBoundingBox(
                min_bound=[-50, -50, -50],
                max_bound=[50, 50, 50],
            )

        bbox = bboxes[0]
        for b in bboxes[1:]:
            bbox += b

        return bbox

    def _collect_bboxes(self, node, bboxes):
        for mesh in node.meshes:
            mesh_world = copy.deepcopy(mesh)
            mesh_world.transform(node.world_T)

            bboxes.append(
                mesh_world.get_axis_aligned_bounding_box()
            )

        for child in node.children:
            self._collect_bboxes(child, bboxes)
            
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

        line_set.transform(node.world_T)

        geom_name = f"axis_chain_{joint.name or node.name}"

        self.widget.scene.scene.remove_geometry(geom_name)
        self.widget.scene.scene.add_geometry(
            geom_name,
            line_set,
            self.axis_material,
        )
        self.axis_geometry_names.append(geom_name)

        label_text = label or joint.name or node.name

        world_points = np.asarray(line_set.points)
        if len(world_points) > 0:
            label_pos = world_points.mean(axis=0)

            axis_label = self.widget.add_3d_label(
                label_pos,
                label_text
            )
            axis_label.color = gui.Color(
                color[0],
                color[1],
                color[2],
                1.0
            )

            self.joint_axis_labels.append(axis_label)
    
    def show_chain_carriers(self, node):
        joint = node.joint

        if not joint.carriers:
            return

        positions = get_carrier_positions(
            joint.sprockets,
            joint.carriers,
            chain_offset=node.joint_value,
            loop=joint.loop,
        )

        for i, pos in enumerate(positions):

            sphere = o3d.geometry.TriangleMesh.create_sphere(
                radius=0.5
            )

            sphere.translate(pos)

            name = f"carrier_{node.name}_{i}"

            self.widget.scene.scene.add_geometry(
                name,
                sphere,
                self.material,
            )

            self.axis_geometry_names.append(name)

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