import open3d.visualization.gui as gui # type: ignore

overridetable = {
    "x0.001": 0.001,
    "x0.01": 0.01,
    "x0.1": 0.1,
    "x0.5": 0.5,
    "x1": 1.0,
    "x2": 2.0,
    "x5": 5.0,
    "x10": 10.0,
}

class AxisControlWindow:

    def __init__(self, on_joint_move):

        self.on_joint_move = on_joint_move

        self.window = gui.Application.instance.create_window(
            "Axis Control",
            200,
            720
        )

        self.layout = gui.Vert(
            5,
            gui.Margins(10, 10, 10, 10)
        )

        self.window.add_child(self.layout)

        self.window.set_on_layout(
            self._on_layout
        )

        #
        # タイトル
        #
        self.layout.add_child(
            gui.Label("== Axis Control ==")
        )
        self.jog_override = 1.0

        self.layout.add_child(
            gui.Label("Override")
        )

        self.override_combo = gui.Combobox()

        for text in overridetable.keys():
            self.override_combo.add_item(text)

        self.override_combo.selected_index = 2  # x1

        self.override_combo.set_on_selection_changed(
            self._on_override_changed
        )

        self.layout.add_child(self.override_combo)

        #
        # 固定行を事前作成
        #
        self.axis_rows = []

        for _ in range(10):

            name_label = gui.Label("")

            button_row = gui.Horiz()

            minus_btn = gui.Button("-")
            plus_btn = gui.Button("+")

            button_row.add_child(minus_btn)
            button_row.add_child(plus_btn)

            name_label.visible = False
            button_row.visible = False

            self.layout.add_child(name_label)
            self.layout.add_child(button_row)

            self.axis_rows.append({
                "label": name_label,
                "row": button_row,
                "minus": minus_btn,
                "plus": plus_btn,
                "joint": None,
            })

    def _on_layout(self, layout_context):

        self.layout.frame = self.window.content_rect

    def set_axis_info(self, joint_info_list):

        #
        # 全部非表示
        #
        for r in self.axis_rows:

            r["label"].visible = False
            r["row"].visible = False
            r["joint"] = None

        #
        # Joint表示
        #
        for i, joint in enumerate(joint_info_list):

            if i >= len(self.axis_rows):
                break

            r = self.axis_rows[i]

            r["joint"] = joint

            r["label"].text = joint["name"]

            r["label"].visible = True
            r["row"].visible = True

            r["minus"].set_on_clicked(
                lambda j=joint:
                    self.on_joint_move(j, +self.jog_override)
            )

            r["plus"].set_on_clicked(
                lambda j=joint:
                    self.on_joint_move(j, -self.jog_override)
            )

        self.window.set_needs_layout()

    def _on_override_changed(self, text, index):

        self.jog_override = overridetable.get(text, 1.0)

        print("Jog Override:", self.jog_override)