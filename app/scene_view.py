import copy
import json
from pathlib import Path
from unittest import case
import numpy as np
import math

import open3d as o3d
import open3d.visualization.gui as gui # type: ignore
import open3d.visualization.rendering as rendering # type: ignore
from wcwidth import center # type: ignore

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
        self.camera_fov = 45.0
        self.camera_fov_step = 5.0
        self.camera_pan_step = 10.0
        self._init_key_state()

        self.axis_geometry_names = []
        self.axis_material = rendering.MaterialRecord()
        self.axis_material.shader = "unlitLine"
        self.axis_material.line_width = 1.0

        self.show_axis = False

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

            self._build_model_from_json(
                data,
                json_path
            )
            self.refresh_model()
            self.reset_camera_to_model()

            print("Model loaded:", json_path.name)

        except Exception:
            traceback.print_exc()
            
    def reset_camera_to_model(self):
        bbox = self.get_scene_bbox()
        
        self.widget.setup_camera(
            60,
            bbox,
            bbox.get_center()
        )

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
            gui.KeyName.LEFT: lambda: self.set_camera_fov(self.camera_fov - self.camera_fov_step),
            gui.KeyName.RIGHT:lambda: self.set_camera_fov(self.camera_fov + self.camera_fov_step),
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
    
    def move_joint(self, node, amount):
        if node.joint.type == "rotate":
            node.joint_value += amount * 1.0

        elif node.joint.type == "linear":
            node.joint_value += amount * 1.0

        elif node.joint.type == "chain":
            node.joint_value += amount

        elif node.joint.type == "signal":
            node.joint_value = 1 if amount > 0 else 0

        gui.Application.instance.post_to_main_thread(
            self.window,
            self.refresh_model
        )
    
    def refresh_model(self):
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

        if self.show_axis:
            self.show_joint_axes()
        else:
            self.clear_joint_axes()

    
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
        new_fov = max(1.0, min(90.0, float(fov_deg)))

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

        fov_rad = math.radians(self.camera_fov)

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

            match joint.type:
                case "rotate":
                    self.create_axis_line(
                        name=f"joint_axis_{node.name}",
                        origin=origin,
                        direction=direction,
                        bbox=bbox,
                        color=color,
                    )

                case "linear":
                    self.create_axis_line(
                        name=f"joint_axis_{node.name}_plus",
                        origin=node.world_T[:3, 3],
                        direction=direction,
                        bbox=bbox,
                        color=color,
                        type="plusonly",
                    )
                    self.create_axis_line(
                        name=f"joint_axis_{node.name}_minus",
                        origin=node.world_T[:3, 3],
                        direction=direction,
                        bbox=bbox,
                        color=[1.0 - c for c in color],
                        type="minusonly",
                    )
                case "chain":
                    self.draw_chain_axis(node, color)
                    #self.show_chain_carriers(node)

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
            return (1.0, 0.8, 0.1)   # 黄色
        if joint_type == "chain":
            return (0.2, 0.8, 0.1)   # 緑

        return (0.8, 0.8, 0.8)       # その他
    
    def create_axis_line(self, origin, direction, bbox, color=(1, 0, 0), type="infinite", name=None):
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
    
    def draw_chain_axis(self, node, color):
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
