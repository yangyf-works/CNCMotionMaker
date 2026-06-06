import os
import colorsys
import copy
import numpy as np
import open3d as o3d

from core.scene_node import SceneNode
from core.transform import (
    make_transform,
    parse_joint,
    make_joint_transform,
)


HIDE_T = np.eye(4)
HIDE_T[0, 0] = 0.00001
HIDE_T[1, 1] = 0.00001
HIDE_T[2, 2] = 0.00001
HIDE_T[3, 3] = 1


COLOR_LIST = [[0.7, 0.7, 0.7]]

for i in range(10):
    h = i / 10
    s = 0.4
    v = 0.9
    COLOR_LIST.append(colorsys.hsv_to_rgb(h, s, v))


def rotation_from_direction(direction, up=np.array([0, 1, 0])):
    z = direction / np.linalg.norm(direction)
    x = np.cross(up, z)

    if np.linalg.norm(x) < 1e-6:
        up = np.array([1, 0, 0])
        x = np.cross(up, z)

    x /= np.linalg.norm(x)
    y = np.cross(z, x)

    R = np.eye(4)
    R[:3, 0] = x
    R[:3, 1] = y
    R[:3, 2] = z

    return R


def compute_array_transform(defn, i):
    mode = defn["mode"]
    align = defn.get("align_to_path", False)

    if mode == "line":
        direction = np.array(defn["direction"], dtype=float)
        direction /= np.linalg.norm(direction)

        start = np.array(defn.get("start", [0, 0, 0]), dtype=float)
        spacing = defn["spacing"]

        pos = start + direction * spacing * i

        T = np.eye(4)
        T[:3, 3] = pos

        if align:
            return T @ rotation_from_direction(direction)

        return T

    if mode == "arc":
        center = np.array(defn["center"], dtype=float)
        radius = defn["radius"]

        axis = np.array(defn["axis"], dtype=float)
        axis /= np.linalg.norm(axis)

        a0 = defn["start_angle"]
        a1 = defn["end_angle"]

        t = i / max(defn["count"] - 1, 1)
        angle = a0 + (a1 - a0) * t
        rad = np.radians(angle)

        K = np.array([
            [0, -axis[2], axis[1]],
            [axis[2], 0, -axis[0]],
            [-axis[1], axis[0], 0]
        ])

        R3 = np.eye(3) + np.sin(rad) * K + (1 - np.cos(rad)) * (K @ K)

        base = np.array([radius, 0, 0])
        pos = R3 @ base

        T = np.eye(4)
        T[:3, 3] = center + pos

        if align:
            tangent = np.cross(axis, pos)
            if np.linalg.norm(tangent) > 0:
                tangent /= np.linalg.norm(tangent)

            return T @ rotation_from_direction(tangent)

        return T

    raise ValueError(f"Unknown array mode: {mode}")


def expand_array(defn, defs, base_dir, path, flip_normal):
    nodes = []
    count = defn["count"]
    ref = defn["ref"]

    for i in range(count):
        array_T = compute_array_transform(defn, i)
        extra_T = make_transform(defn.get("transform"))

        # 行列を直接渡したいので専用キーにする
        child_node = {
            "ref": ref,
            "_local_T": array_T @ extra_T
        }

        node = build_node(
            child_node,
            defs,
            base_dir,
            f"{path}_arr{i}",
            flip_normal
        )

        nodes.append(node)

    return nodes

def build_node(node_def, defs, base_dir, path="", flip_normal=False):
    ref = node_def["ref"]
    defn = defs[ref]

    current_path = f"{path}.{ref}" if path else ref

    node = SceneNode(current_path)

    if "_local_T" in node_def:
        node.local_T = node_def["_local_T"]
    else:
        node.local_T = make_transform(node_def.get("transform"))
        
    def_T = make_transform(defn.get("transform"))

    det = np.linalg.det((node.local_T @ def_T)[:3, :3])
    current_flip = flip_normal if det > 0 else not flip_normal

    if defn["type"] == "mesh":
        mesh_path = os.path.join(base_dir, defn["file"])

        mesh = o3d.io.read_triangle_mesh(mesh_path)

        if current_flip:
            triangles = np.asarray(mesh.triangles)
            triangles[:] = triangles[:, [0, 2, 1]]

        mesh.compute_triangle_normals()

        node.meshes.append(mesh)
        node.def_T = def_T

    elif defn["type"] == "node":
        node.joint = parse_joint(defn.get("joint"))

        if node.joint is not None and node.joint.type == "signal":
            node.joint_value = 1

        for child_def in defn.get("children", []):
            child = build_node(
                child_def,
                defs,
                base_dir,
                current_path,
                current_flip
            )
            node.children.append(child)

    elif defn["type"] == "array":
        children = expand_array(
            defn,
            defs,
            base_dir,
            current_path,
            current_flip
        )
        node.children.extend(children)

    return node


def update_world_transform(node, parent_T=np.eye(4)):
    joint_T = make_joint_transform(node.joint, node.joint_value)

    node.world_T = parent_T @ node.local_T @ joint_T

    for child in node.children:
        update_world_transform(child, node.world_T)


def paint_meshes(node, color_index=0):
    if node.joint is not None:
        color_index += 1

    color = COLOR_LIST[color_index % len(COLOR_LIST)]

    for mesh in node.meshes:
        mesh.paint_uniform_color(color)

    for child in node.children:
        paint_meshes(child, color_index)


def collect_meshes(node, out_list, hidden=False):
    if (
        node.joint is not None
        and node.joint.type == "signal"
        and node.joint_value == 0
    ):
        hidden = True

    for mesh in node.meshes:
        if hidden:
            out_list.append((mesh, HIDE_T))
        else:
            out_list.append((mesh, node.world_T @ node.def_T))

    for child in node.children:
        collect_meshes(child, out_list, hidden)


def build_geometry_list_from_model_json(data, base_dir):
    defs = data["definitions"]

    roots = []

    for scene_node in data["scene"]:
        root = build_node(
            scene_node,
            defs,
            base_dir
        )
        roots.append(root)

    for root in roots:
        update_world_transform(root)

    for root in roots:
        paint_meshes(root)

    all_meshes = []

    for root in roots:
        collect_meshes(root, all_meshes)

    geometry_list = []

    for mesh, world_T in all_meshes:
        m = o3d.geometry.TriangleMesh(mesh)
        m.transform(world_T)
        geometry_list.append(m)

    return roots, geometry_list

def collect_joint_info(node, out_list):
    if node.joint is not None:
        out_list.append({
            "node": node,
            "name": (
                getattr(node.joint, "name", None)
                or node.name
            ),
            "type": node.joint.type,
            "axisno": node.joint.axisno,
            "value": node.joint_value,
        })

    for child in node.children:
        collect_joint_info(child, out_list)


def collect_all_joint_info(roots):
    result = []

    for root in roots:
        collect_joint_info(root, result)

    return result

def collect_export_meshes(roots):
    merged = o3d.geometry.TriangleMesh()

    all_meshes = []

    for root in roots:
        collect_meshes(root, all_meshes)

    for mesh, world_T in all_meshes:
        # HIDE_T のメッシュは出力しない
        if np.allclose(world_T, HIDE_T):
            continue

        mesh_copy = copy.deepcopy(mesh)
        mesh_copy.transform(world_T)
        merged += mesh_copy

    return merged