import open3d.visualization.gui as gui # type: ignore

override_items = [
    ("x0.0001", 0.0001),
    ("x0.001", 0.001),
    ("x0.01", 0.01),
    ("x0.1", 0.1),
    ("x1", 1.0),
    ("x5", 5.0),
    ("x10", 10.0),
    ("x100", 100.0),
]

class AxisControlWindow:

    def __init__(self, on_joint_move):

        self.on_joint_move = on_joint_move

        self.window = gui.Application.instance.create_window(
            "Axis Control",
            230,
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
            gui.Label("===  Axis Control  ===")
        )
        self.jog_override_index = 4  # x1
        self.jog_override = override_items[self.jog_override_index][1]

        self.layout.add_child(gui.Label("Override"))

        self.override_row = gui.Horiz(5)

        self.override_minus_btn = gui.Button("-")
        self.override_plus_btn = gui.Button("+")
        self.override_combo = gui.Combobox()

        # ボタンを小さめにする
        self.override_minus_btn.horizontal_padding_em = 0.2
        self.override_minus_btn.vertical_padding_em = 0.1

        self.override_plus_btn.horizontal_padding_em = 0.2
        self.override_plus_btn.vertical_padding_em = 0.1

        for text, value in override_items:
            self.override_combo.add_item(f"{text:<14}")

        self.override_combo.selected_index = self.jog_override_index

        self.override_combo.set_on_selection_changed(
            self._on_override_changed
        )

        self.override_minus_btn.set_on_clicked(
            self._on_override_minus
        )

        self.override_plus_btn.set_on_clicked(
            self._on_override_plus
        )

        # ボタンを小さめにする
        self.override_minus_btn.horizontal_padding_em = 0.2
        self.override_minus_btn.vertical_padding_em = 0.1

        self.override_plus_btn.horizontal_padding_em = 0.2
        self.override_plus_btn.vertical_padding_em = 0.1

        self.override_row.add_child(self.override_combo)
        self.override_row.add_child(self.override_minus_btn)
        self.override_row.add_child(self.override_plus_btn)

        self.layout.add_child(self.override_row)
        self._setting_axis_info = False
        # 固定行を事前作成
        #
        self.axis_rows = []

        for _ in range(10):

            axis_row = gui.Horiz(5)

            name_label = gui.Label("")

            value_edit = gui.TextEdit()
            value_edit.enabled = False
            value_edit.text_value = "0.000"

            minus_btn = gui.Button("-")
            plus_btn = gui.Button("+")

            minus_btn.horizontal_padding_em = 0.8
            plus_btn.horizontal_padding_em = 0.8
            minus_btn.horizontal_padding_em = 0.2
            minus_btn.vertical_padding_em = 0.1

            plus_btn.horizontal_padding_em = 0.2
            plus_btn.vertical_padding_em = 0.1

            signal_check = gui.Checkbox("")
            signal_check.visible = False

            axis_row.add_child(name_label)
            axis_row.add_stretch()
            axis_row.add_child(value_edit)
            axis_row.add_child(signal_check)
            axis_row.add_child(minus_btn)
            axis_row.add_child(plus_btn)

            axis_row.visible = False

            self.layout.add_child(axis_row)

            self.axis_rows.append({
                "row": axis_row,
                "label": name_label,
                "value": value_edit,
                "check": signal_check,
                "minus": minus_btn,
                "plus": plus_btn,
                "joint": None,
            })

    def _on_layout(self, layout_context):

        self.layout.frame = self.window.content_rect

        content = self.window.content_rect

        margin = 10
        gap = 5

        btn_w = 36
        row_h = 32

        x = content.x + margin
        y = self.override_row.frame.y

        total_w = content.width - margin * 2

        combo_w = total_w - btn_w * 2 - gap * 2

        self.override_minus_btn.frame = gui.Rect(
            x,
            y,
            btn_w,
            row_h
        )

        self.override_combo.frame = gui.Rect(
            x + btn_w + gap,
            y,
            combo_w,
            row_h
        )

        self.override_plus_btn.frame = gui.Rect(
            x + btn_w + gap + combo_w + gap,
            y,
            btn_w,
            row_h
        )

    def set_axis_info(self, joint_info_list):

        self._setting_axis_info = True

        try:
            for r in self.axis_rows:

                r["row"].visible = False
                r["joint"] = None

                r["value"].visible = True
                r["check"].visible = False
                r["minus"].visible = True
                r["plus"].visible = True

            for i, joint in enumerate(joint_info_list):

                if i >= len(self.axis_rows):
                    break

                r = self.axis_rows[i]

                r["joint"] = joint
                r["label"].text = joint.get("name", "")

                node = joint.get("node")

                if node is None:
                    continue

                joint_def = node.joint
                joint_type = getattr(joint_def, "type", "")

                current_value = node.joint_value

                r["row"].visible = True

                if joint_type == "signal":

                    current_value = joint["node"].joint_value

                    r["value"].visible = False
                    r["minus"].visible = False
                    r["plus"].visible = False

                    r["check"].visible = True
                    r["check"].checked = bool(current_value)

                    r["check"].set_on_checked(
                        lambda checked, j=joint:
                            self._signal_changed(j, checked)
                    )

                else:

                    current_value = joint["node"].joint_value

                    r["value"].visible = True
                    r["minus"].visible = True
                    r["plus"].visible = True
                    r["check"].visible = False

                    r["value"].text_value = f"{current_value:10.4f}"

                    r["minus"].set_on_clicked(
                        lambda j=joint, row=r:
                            self._move_joint(j, row, -self.jog_override)
                    )

                    r["plus"].set_on_clicked(
                        lambda j=joint, row=r:
                            self._move_joint(j, row, self.jog_override)
                    )

        finally:
            self._setting_axis_info = False

        self.window.set_needs_layout()

    def _set_override_index(self, index):

        if index < 0:
            index = 0

        if index >= len(override_items):
            index = len(override_items) - 1

        self.jog_override_index = index

        text, value = override_items[self.jog_override_index]

        self.jog_override = value
        self.override_combo.selected_index = self.jog_override_index

        print("Jog Override:", text, value)


    def _on_override_changed(self, text, index):

        self._set_override_index(index)


    def _on_override_minus(self):

        self._set_override_index(
            self.jog_override_index - 1
        )


    def _on_override_plus(self):

        self._set_override_index(
            self.jog_override_index + 1
        )

    def _move_joint(self, joint, row, amount):

        self.on_joint_move(joint, amount)

        current_value = joint["node"].joint_value
        row["value"].text_value = f"{current_value:10.4f}"

    def _signal_changed(self, joint, checked):

        if self._setting_axis_info:
            return

        value = 1.0 if checked else 0.0

        self.on_joint_move(
            joint,
            value
        )