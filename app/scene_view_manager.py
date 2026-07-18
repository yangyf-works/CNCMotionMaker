import open3d.visualization.gui as gui # type: ignore

class SceneViewManager:
    def __init__(self):
        self.views = []
        self.current_json_path = None
        
    def clear_views(self):
        self.views.clear()

    def add_view(self, view):
        if view in self.views:
            return

        self.views.append(view)

        if self.current_json_path is not None:
            view.load_json_model(self.current_json_path)
            view.widget.force_redraw()

    def remove_view(self, view):
        if view in self.views:
            self.views.remove(view)

    def view_count(self):
        return len(self.views)

    def sub_view_count(self):
        return max(0, len(self.views) - 1)

    def load_json_model(self, json_path):
        self.current_json_path = json_path

        if not self.views:
            return

        main_view = self.views[0]
        main_view.load_json_model(json_path)
        main_view.widget.force_redraw()

        for view in self.views[1:]:
            def update_view(v=view, path=json_path):
                if v not in self.views:
                    return

                v.load_json_model(path)
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