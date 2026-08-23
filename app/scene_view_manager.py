import time

import numpy as np
import open3d.visualization.gui as gui  # type: ignore


class SceneViewManager:
    def __init__(self):
        self.views = []
        self.current_json_path = None

        self.markers = []
        self.next_marker_id = 0

        # Trajectory recording state
        self.trajectory_enabled = True
        self.trajectory_interval = 0.05  # 50 ms
        self.last_trajectory_sample_time = 0.0
        self.trajectory_min_distance = 1e-6

        # Optional UI callback: callback(enabled: bool)
        self.on_trajectory_state_changed = None

    def clear_views(self):
        self.views.clear()

    def add_view(self, view):
        if view in self.views:
            return

        self.views.append(view)

        view.on_marker_added = self.add_marker
        view.on_clear_markers = self.clear_markers
        view.on_toggle_trajectory = self.toggle_trajectory
        view.on_trajectory_reference_changed = self.clear_trajectories

        # Open3D GUI tick callback. Multiple windows may call this callback,
        # but the manager-side time gate prevents duplicate sampling.
        view.window.set_on_tick_event(self._on_trajectory_tick)

        if self.current_json_path is not None:
            view.load_json_model(
                self.current_json_path,
                apply_fixed_joint=(view is self.views[0]),
            )

            # Restore existing markers and their trajectories in the new view.
            for marker in self.markers:
                view.add_marker(marker)
                view.update_trajectory(marker)

            view.widget.force_redraw()

    def _create_marker(
        self,
        node_path,
        local_position,
        source="manual",
    ):
        marker = {
            "id": self.next_marker_id,
            "node_path": tuple(node_path),
            "local_position": np.asarray(local_position, dtype=float).copy(),
            "trajectory_points": [],
            "last_trajectory_position": None,
            "source": source,
        }

        self.next_marker_id += 1
        self.markers.append(marker)
        return marker

    def add_marker(self, node_path, local_position):
        # Used by manual Ctrl + double-click marker creation.
        marker = self._create_marker(
            node_path,
            local_position,
            source="manual",
        )

        for view in list(self.views):
            window = view.window

            def update_view(v=view, m=marker):
                if v not in self.views:
                    return

                v.add_marker(m)
                v.widget.force_redraw()
                v.window.set_needs_layout()

            gui.Application.instance.post_to_main_thread(
                window,
                update_view,
            )

    def set_trajectory_enabled(self, enabled):
        enabled = bool(enabled)

        if self.trajectory_enabled == enabled:
            return

        self.trajectory_enabled = enabled

        if enabled:
            # Start a new trajectory from the current marker positions.
            self.last_trajectory_sample_time = 0.0
            for marker in self.markers:
                marker["last_trajectory_position"] = None
        else:
            # OFF means recording stops and all existing trajectory history
            # and trajectory geometry are cleared. Markers themselves remain.
            self.clear_trajectories()

        if self.on_trajectory_state_changed is not None:
            self.on_trajectory_state_changed(self.trajectory_enabled)

        print(
            "Trajectory:",
            "ON" if self.trajectory_enabled else "OFF",
        )

    def toggle_trajectory(self):
        self.set_trajectory_enabled(
            not self.trajectory_enabled
        )

    def set_trajectory_interval(self, interval_seconds):
        interval_seconds = float(interval_seconds)
        if interval_seconds <= 0.0:
            raise ValueError("Trajectory interval must be greater than 0.")

        self.trajectory_interval = interval_seconds
        self.last_trajectory_sample_time = 0.0

        print(
            f"Trajectory interval: {self.trajectory_interval * 1000.0:.0f} ms"
        )

    def clear_trajectories(self):
        self.last_trajectory_sample_time = 0.0

        for marker in self.markers:
            marker["trajectory_points"].clear()
            marker["last_trajectory_position"] = None

        for view in list(self.views):
            window = view.window

            def update_view(v=view):
                if v not in self.views:
                    return

                v.clear_trajectories()
                v.widget.force_redraw()

            gui.Application.instance.post_to_main_thread(
                window,
                update_view,
            )

    def _on_trajectory_tick(self):
        if not self.trajectory_enabled:
            return False

        if not self.views or not self.markers:
            return False

        now = time.monotonic()

        if (
            now - self.last_trajectory_sample_time
            < self.trajectory_interval
        ):
            return False

        self.last_trajectory_sample_time = now
        return self.sample_trajectories()

    def _append_trajectory_references(self, marker):
        for view in list(self.views):
            view.append_trajectory_reference(marker)

    def sample_trajectories(self):
        if not self.views or not self.markers:
            return False

        source_view = self.views[0]
        changed_markers = []

        for marker in self.markers:
            world_position = (
                source_view.get_marker_world_position(marker)
            )

            if world_position is None:
                continue

            world_position = np.asarray(
                world_position,
                dtype=float,
            )

            marker_changed = False

            for view in list(self.views):
                sample_position = (
                    view.get_marker_trajectory_position(marker)
                )

                if sample_position is None:
                    continue

                sample_position = np.asarray(
                    sample_position,
                    dtype=float,
                )

                marker_id = marker["id"]

                last_position = (
                    view.trajectory_last_sample_positions.get(
                        marker_id
                    )
                )

                if last_position is None:
                    marker_changed = True
                else:
                    distance = float(
                        np.linalg.norm(
                            sample_position - last_position
                        )
                    )

                    if (
                        distance
                        > self.trajectory_min_distance
                    ):
                        marker_changed = True

            if not marker_changed:
                continue

            marker["trajectory_points"].append(
                world_position.copy()
            )

            marker["last_trajectory_position"] = (
                world_position.copy()
            )

            for view in list(self.views):
                sample_position = (
                    view.get_marker_trajectory_position(marker)
                )

                if sample_position is None:
                    continue

                view.trajectory_last_sample_positions[
                    marker["id"]
                ] = np.asarray(
                    sample_position,
                    dtype=float,
                ).copy()

            self._append_trajectory_references(marker)

            changed_markers.append(marker)

        if not changed_markers:
            return False

        for view in list(self.views):
            for marker in changed_markers:
                view.update_trajectory(marker)

            view.widget.force_redraw()

        return True

    def clear_markers(self):
        json_markers = [
            marker
            for marker in self.markers
            if marker.get("source") == "json"
        ]

        self.markers = json_markers
        self.last_trajectory_sample_time = 0.0

        if self.markers:
            self.next_marker_id = (
                max(marker["id"] for marker in self.markers) + 1
            )
        else:
            self.next_marker_id = 0

        for marker in self.markers:
            marker["trajectory_points"].clear()
            marker["last_trajectory_position"] = None

        for view in list(self.views):
            window = view.window

            def update_view(v=view):
                if v not in self.views:
                    return

                # Rebuild marker geometry from the retained JSON marker set.
                v.clear_markers()

                for marker in self.markers:
                    v.add_marker(marker)

                v.widget.force_redraw()
                v.window.set_needs_layout()

            gui.Application.instance.post_to_main_thread(
                window,
                update_view
            )

    def clear_all_markers(self):
        self.markers.clear()
        self.next_marker_id = 0
        self.last_trajectory_sample_time = 0.0

        for view in list(self.views):
            window = view.window

            def update_view(v=view):
                if v not in self.views:
                    return

                v.clear_markers()
                v.widget.force_redraw()
                v.window.set_needs_layout()

            gui.Application.instance.post_to_main_thread(
                window,
                update_view
            )

    def remove_view(self, view):
        if view in self.views:
            self.views.remove(view)

    def view_count(self):
        return len(self.views)

    def sub_view_count(self):
        return max(0, len(self.views) - 1)

    def load_json_model(self, json_path):
        self.markers.clear()
        self.next_marker_id = 0
        self.last_trajectory_sample_time = 0.0
        self.current_json_path = json_path

        if not self.views:
            return

        main_view = self.views[0]
        main_view.clear_markers()
        main_view.load_json_model(json_path, apply_fixed_joint=True)
        main_view.widget.force_redraw()

        for request in main_view.get_json_marker_requests():
            marker = self._create_marker(
                request["node_path"],
                request["local_position"],
                source="json",
            )
            main_view.add_marker(marker)

        for view in self.views[1:]:
            def update_view(v=view, path=json_path):
                if v not in self.views:
                    return

                v.clear_markers()
                v.load_json_model(path)

                for marker in self.markers:
                    v.add_marker(marker)

                v.widget.force_redraw()
                v.window.set_needs_layout()

            gui.Application.instance.post_to_main_thread(
                view.window,
                update_view
            )

    def set_joint_value_by_name(self, axis_name, value):
        model_reset = False

        for view in list(self.views):
            if view.set_joint_value_by_name(axis_name, value):
                model_reset = True

        return model_reset

    def refresh_model(self, model_reset=False):
        for view in list(self.views):
            window = view.window

            def update_view(v=view):
                if v not in self.views:
                    return

                v.refresh_model(model_reset)
                v.widget.force_redraw()

            gui.Application.instance.post_to_main_thread(
                window,
                update_view
            )