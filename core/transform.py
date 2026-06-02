import numpy as np

from core.scene_node import Joint


def make_transform(transform_def):
    T = np.eye(4)

    if transform_def is None:
        return T

    pos = transform_def.get("position", [0, 0, 0])
    T[:3, 3] = pos

    scale = transform_def.get("scale", [1, 1, 1])
    S = np.eye(4)
    S[0, 0] = scale[0]
    S[1, 1] = scale[1]
    S[2, 2] = scale[2]

    rot = transform_def.get("rotation", [0, 0, 0])
    rx, ry, rz = np.radians(rot)

    Rx = np.array([
        [1, 0, 0, 0],
        [0, np.cos(rx), -np.sin(rx), 0],
        [0, np.sin(rx), np.cos(rx), 0],
        [0, 0, 0, 1]
    ])

    Ry = np.array([
        [np.cos(ry), 0, np.sin(ry), 0],
        [0, 1, 0, 0],
        [-np.sin(ry), 0, np.cos(ry), 0],
        [0, 0, 0, 1]
    ])

    Rz = np.array([
        [np.cos(rz), -np.sin(rz), 0, 0],
        [np.sin(rz), np.cos(rz), 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
    ])

    return T @ Rz @ Ry @ Rx @ S


def parse_joint(joint_def):
    if joint_def is None:
        return None

    return Joint(
        joint_type=joint_def["type"],
        name=joint_def.get("name"),
        axis=joint_def.get("axis"),
        pivot=joint_def.get("pivot", [0, 0, 0]),
        path=joint_def.get("path"),
        axisno=joint_def.get("axisno"),
        signal=joint_def.get("signal", "")
    )


def make_joint_transform(joint, value):
    if joint is None:
        return np.eye(4)

    if joint.type == "signal":
        return np.eye(4)

    if joint.type == "linear":
        T = np.eye(4)
        T[:3, 3] = joint.axis * value
        return T

    if joint.type == "rotate":
        axis = joint.axis
        pivot = joint.pivot
        rad = np.radians(value)

        x, y, z = axis
        c = np.cos(rad)
        s = np.sin(rad)

        R = np.array([
            [c + x*x*(1-c), x*y*(1-c) - z*s, x*z*(1-c) + y*s, 0],
            [y*x*(1-c) + z*s, c + y*y*(1-c), y*z*(1-c) - x*s, 0],
            [z*x*(1-c) - y*s, z*y*(1-c) + x*s, c + z*z*(1-c), 0],
            [0, 0, 0, 1]
        ])

        T1 = np.eye(4)
        T1[:3, 3] = -pivot

        T2 = np.eye(4)
        T2[:3, 3] = pivot

        return T2 @ R @ T1

    return np.eye(4)