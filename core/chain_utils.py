from __future__ import annotations
import numpy as np

EPS = 1e-9

def normalize(v, eps=EPS):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)

    if n < eps:
        return v

    return v / n


def get_sprocket_value(sprocket, key, default=None):
    if isinstance(sprocket, dict):
        return sprocket.get(key, default)

    return getattr(sprocket, key, default)


def point_on_sprocket(sprocket, angle_deg):
    center = np.asarray(
        get_sprocket_value(sprocket, "center", [0, 0, 0]),
        dtype=float,
    )

    axis = normalize(
        get_sprocket_value(sprocket, "axis", [0, 0, 1])
    )

    ref_dir = normalize(
        get_sprocket_value(sprocket, "ref_dir", [1, 0, 0])
    )

    radius = float(
        get_sprocket_value(sprocket, "radius", 1.0)
    )

    # ref_dir を axis に垂直な平面へ投影
    ref_dir = ref_dir - np.dot(ref_dir, axis) * axis
    ref_dir = normalize(ref_dir)

    # ref_dir が axis と平行だった場合の保険
    if np.linalg.norm(ref_dir) < EPS:
        if abs(axis[0]) < 0.9:
            ref_dir = normalize(np.cross(axis, [1, 0, 0]))
        else:
            ref_dir = normalize(np.cross(axis, [0, 1, 0]))

    side_dir = normalize(np.cross(axis, ref_dir))

    angle_rad = np.deg2rad(angle_deg)

    return center + radius * (
        np.cos(angle_rad) * ref_dir
        + np.sin(angle_rad) * side_dir
    )


def sample_sprocket_arc(sprocket, arc_step_deg=5.0):
    start_angle = float(
        get_sprocket_value(sprocket, "start_angle", 0.0)
    )
    end_angle = float(
        get_sprocket_value(sprocket, "end_angle", 360.0)
    )

    angle_range = end_angle - start_angle

    steps = max(
        2,
        int(abs(angle_range) / arc_step_deg) + 1
    )

    points = []

    for i in range(steps):
        t = i / (steps - 1)
        angle = start_angle + angle_range * t
        points.append(point_on_sprocket(sprocket, angle))

    return points


def append_point_unique(points, p, eps=EPS):
    p = np.asarray(p, dtype=float)

    if not points:
        points.append(p)
        return

    if np.linalg.norm(points[-1] - p) > eps:
        points.append(p)


def build_chain_points_from_sprockets(
    sprockets,
    loop=True,
    arc_step_deg=5.0,
):
    points = []

    if not sprockets:
        return points

    count = len(sprockets)

    for i, sprocket in enumerate(sprockets):
        # 1. sprocket の円弧部分
        arc_points = sample_sprocket_arc(
            sprocket,
            arc_step_deg=arc_step_deg,
        )

        for p in arc_points:
            append_point_unique(points, p)

        # 2. 次の sprocket までの直線部分
        if i < count - 1:
            next_sprocket = sprockets[i + 1]
        elif loop:
            next_sprocket = sprockets[0]
        else:
            break

        p0 = point_on_sprocket(
            sprocket,
            get_sprocket_value(sprocket, "end_angle", 360.0),
        )

        p1 = point_on_sprocket(
            next_sprocket,
            get_sprocket_value(next_sprocket, "start_angle", 0.0),
        )

        append_point_unique(points, p0)
        append_point_unique(points, p1)

    return points


def build_chain_lines(points, loop=True):
    if len(points) < 2:
        return []

    lines = []

    for i in range(len(points) - 1):
        lines.append([i, i + 1])

    if loop:
        lines.append([len(points) - 1, 0])

    return lines


def calc_polyline_lengths(points):
    if len(points) < 2:
        return [], [0.0], 0.0

    segment_lengths = []
    cumulative_lengths = [0.0]

    total = 0.0

    for p0, p1 in zip(points[:-1], points[1:]):
        length = float(np.linalg.norm(p1 - p0))
        segment_lengths.append(length)
        total += length
        cumulative_lengths.append(total)

    return segment_lengths, cumulative_lengths, total


def point_on_chain(points, distance, loop=True):
    if not points:
        return None

    points = [np.asarray(p, dtype=float) for p in points]

    if len(points) == 1:
        return points[0]

    segment_lengths, cumulative_lengths, total_length = calc_polyline_lengths(points)

    if total_length < EPS:
        return points[0]

    if loop:
        distance = distance % total_length
    else:
        distance = max(0.0, min(distance, total_length))

    for i, seg_len in enumerate(segment_lengths):
        start_len = cumulative_lengths[i]

        if distance <= start_len + seg_len:
            if seg_len < EPS:
                return points[i]

            t = (distance - start_len) / seg_len
            return points[i] + (points[i + 1] - points[i]) * t

    return points[-1]