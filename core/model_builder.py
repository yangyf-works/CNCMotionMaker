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
from core.chain_utils import (
    build_chain_points_from_sprockets,
    point_on_chain,
    calc_polyline_lengths,
)

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
    show_when = node_def.get("show_when", None)
    if isinstance(show_when, str):
        s = show_when.strip().lower()
        if s in ("on", "1", "true"):
            show_when = True
        elif s in ("off", "0", "false"):
            show_when = False
        else:
            raise ValueError(
                f"Invalid show_when value: {show_when}"
            )
    node.show_when = show_when

    if "_local_T" in node_def:
        node.local_T = node_def["_local_T"]
    else:
        node.local_T = make_transform(node_def.get("transform"))
    node.local_T = node.local_T@make_transform(defn.get("transform", {}))
    
    det = np.linalg.det(node.local_T[:3,:3])
    current_flip = flip_normal if det > 0 else not flip_normal

    if defn["type"] == "mesh":
        mesh_path = os.path.join(base_dir, defn["file"])
        mesh = o3d.io.read_triangle_mesh(mesh_path)

        if current_flip:
            triangles = np.asarray(mesh.triangles)
            triangles[:] = triangles[:, [0, 2, 1]]

        mesh.compute_triangle_normals()
        node.meshes.append(mesh)

    elif defn["type"] == "node":
        node.joint = parse_joint(defn.get("joint"))

        if node.joint is not None :
            node.joint_value = node.joint.initial_value

        child_defs = defn.get("children", [])

        if node.joint is not None and node.joint.type == "chain":
            node.children = expand_chain_carriers(
                child_defs,
                node.joint,
                defs,
                base_dir,
                current_path,
                current_flip,
            )
        else:
            for child_def in child_defs:
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

def update_all_world_transforms(roots):
    for root in roots:
        update_world_transform(root)

def update_world_transform(node, parent_T=None):
    if parent_T is None:
        parent_T = np.eye(4)

    node.joint_base_T = parent_T @ node.local_T
    joint_T = make_joint_transform(node.joint, node.joint_value)
    node.world_T = node.joint_base_T @ joint_T

    if node.joint is not None and node.joint.type == "chain":
        update_chain_carriers(node)

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

def collect_visible_meshes(roots):
    result = []

    def walk(node, hidden=False):
        if hidden:
            return

        for mesh in node.meshes:
            result.append(
                {
                    "node": node,
                    "mesh": mesh,
                    "world_T": node.world_T.copy(),
                }
            )

        for child in node.children:
            child_hidden = False

            if (
                node.joint is not None
                and node.joint.type == "signal"
                and child.show_when is not None
            ):
                signal_on = bool(
                    node.joint_value
                )
                child_hidden = (
                    child.show_when
                    != signal_on
                )

            walk(child, child_hidden)

    for root in roots:
        walk(root)

    return result

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

    update_all_world_transforms(roots)
    normalize_joint_names(roots)

    for root in roots:
        paint_meshes(root)

    all_meshes = collect_visible_meshes(roots)
    geometry_list = []

    for item in all_meshes:
        mesh = item["mesh"]
        world_T = item["world_T"]

        m = o3d.geometry.TriangleMesh(mesh)
        m.transform(world_T)
        geometry_list.append(m)

    return roots, geometry_list

def normalize_joint_names(roots):
    name_counts = {}

    def walk(node):
        if node.joint is not None:
            base_name = (
                getattr(node.joint, "name", None)
                or node.name
            )

            count = name_counts.get(base_name, 0)
            name_counts[base_name] = count + 1

            unique_name = base_name if count == 0 else f"{base_name}{count}"

            node.joint.name = unique_name

        for child in node.children:
            walk(child)

    for root in roots:
        walk(root)

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

    all_meshes = collect_visible_meshes(roots)

    for item in all_meshes:
        mesh = item["mesh"]
        world_T = item["world_T"]

        mesh_copy = copy.deepcopy(mesh)
        mesh_copy.transform(world_T)
        merged += mesh_copy

    return merged

def expand_chain_carriers(child_defs, joint, defs, base_dir, path, flip_normal):
    carriers_def = getattr(joint, "carriers", None)

    if not carriers_def:
        return []

    count = int(carriers_def.get("count", 0))
    offset = float(carriers_def.get("offset", 0.0))

    if count <= 0:
        return []

    carrier_roots = []

    for i in range(count):
        group_node = SceneNode(f"{path}_carrier{i}")
        group_node.is_chain_carrier = True
        group_node.chain_index = i
        group_node.chain_offset = offset
        group_node.local_T = np.eye(4)

        for child_def in child_defs:
            child = build_node(
                child_def,
                defs,
                base_dir,
                f"{path}_carrier{i}",
                flip_normal,
            )
            group_node.children.append(child)

        carrier_roots.append(group_node)

    return carrier_roots

def update_chain_carriers(chain_node):
    joint = chain_node.joint

    carriers_def = getattr(joint, "carriers", None)
    if not carriers_def:
        return

    carrier_nodes = getattr(chain_node, "children", [])
    if not carrier_nodes:
        return

    points = build_chain_points_from_sprockets(
        joint.sprockets,
        loop=joint.loop,
        arc_step_deg=5.0,
    )
    
    _, _, chain_length = calc_polyline_lengths(points)

    if chain_length <= 1e-9:
        return

    count = int(carriers_def.get("count", 0))
    offset = float(carriers_def.get("offset", 0.0))

    if count <= 0:
        return

    spacing = chain_length / count

    for carrier in carrier_nodes:
        i = carrier.chain_index

        distance = (
            chain_node.joint_value
            + offset
            + i * spacing
        )

        pos, direction = point_on_chain(
            points,
            distance,
            loop=joint.loop,
        )

        if pos is None:
            continue

        old_y = carrier.local_T[:3, 1]
        T = np.eye(4)
        T[:3, :3] = make_axis_rotation(direction, old_y)
        T[:3, 3] = pos

        carrier.local_T = T

def make_axis_rotation(direction, old_y):
    x = np.asarray(direction, dtype=float)
    n = np.linalg.norm(x)

    if n < 1e-9:
        return np.eye(3)

    x = x / n

    y = np.asarray(old_y, dtype=float)
    yn = np.linalg.norm(y)

    if yn < 1e-9:
        y = np.array([0.0, 1.0, 0.0])
    else:
        y = y / yn

    # yからx方向成分を取り除く
    y = y - np.dot(y, x) * x

    yn = np.linalg.norm(y)

    if yn < 1e-9:
        # old_y が x と平行に近い場合の逃げ
        y = np.array([0.0, 1.0, 0.0])
        y = y - np.dot(y, x) * x

        if np.linalg.norm(y) < 1e-9:
            y = np.array([0.0, 0.0, 1.0])
            y = y - np.dot(y, x) * x

    y = y / np.linalg.norm(y)

    z = np.cross(x, y)
    z = z / np.linalg.norm(z)

    R = np.eye(3)
    R[:, 0] = x
    R[:, 1] = y
    R[:, 2] = z

    return R