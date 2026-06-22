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
        app = gui.Application.instance
        em = app.menubar_theme.font_size if hasattr(app, "menubar_theme") else 16

        self.window = app.create_window(
            "Joint Control",
            int(28 * em),
            720
        )

        self.motion_panel = gui.Vert(
            5,
            gui.Margins(10, 10, 10, 10)
        )
        self.signal_panel = gui.Vert(
            5,
            gui.Margins(10, 10, 0, 10)
        )
        self.window.add_child(self.motion_panel)
        self.window.add_child(self.signal_panel)
        self.window.set_on_layout(self._on_layout)
        self.allow_close = False
        self.window.set_on_close(self._on_close)

        #
        # タイトル
        #
        self.motion_panel.add_child(
            gui.Label("[Motion Axis]")
        )
        self.jog_override_index = 4  # x1
        self.jog_override = override_items[self.jog_override_index][1]

        self.motion_panel.add_child(gui.Label("Override"))
        self.signal_panel.add_child(
            gui.Label("[Signal]")
        )

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
            self.override_combo.add_item(f"{text:<16}")

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
        self.override_row.add_stretch()
        self.override_row.add_child(self.override_minus_btn)
        self.override_row.add_child(self.override_plus_btn)

        self.motion_panel.add_child(self.override_row)
        separator = gui.Label("=" *18)
        self.motion_panel.add_child(separator)
        self._setting_axis_info = False
        
        self.motion_axis_rows = []
        self.signal_axis_rows = []
                
        gui.Application.instance.post_to_main_thread(
            self.window,
            self._initial_refresh
        )

    def _initial_refresh(self):
        self.window.set_needs_layout()

    def _apply_value_text(self, row, text):
        if self._setting_axis_info:
            return

        joint = row["joint"]

        if joint is None:
            return

        try:
            target_value = float(text.strip())
        except ValueError:
            self._restore_current_value(row)
            return

        amount = target_value - joint["node"].joint_value
        self.on_joint_move(joint, amount)
        self._restore_current_value(row)
    
    def _restore_current_value(self, row):
        current_value = row["joint"]["node"].joint_value
        row["value"].text_value = self._value_format(current_value)
        self._refresh()

    def _on_layout(self, layout_context):
        content = self.window.content_rect

        margin = 0
        gap = 2
        em = self.window.theme.font_size

        left_w = int(10.5 * em)
        right_w = content.width - left_w - gap - margin * 2

        x = content.x + margin
        y = content.y + margin
        h = content.height - margin * 2

        self.motion_panel.frame = gui.Rect(
            x,
            y,
            left_w,
            h
        )

        self.signal_panel.frame = gui.Rect(
            x + left_w + gap,
            y,
            right_w,
            h
        )

    def _on_close(self):
        return self.allow_close

    def close_from_main(self):
        self.allow_close = True
        self.window.close()
    
    def set_axis_info(self, joint_info_list):
        self._setting_axis_info = True
        signal_joints = []
        motion_joints = []

        for joint in joint_info_list:
            joint_def = joint.get("node").joint
            joint_type = getattr(joint_def, "type", "")

            if joint_type == "signal":
                signal_joints.append(joint)
            else:
                motion_joints.append(joint)

        try:
            self.set_motion_axis_info(motion_joints)
            self.set_signal_axis_info(signal_joints)
        finally:
            self._setting_axis_info = False

        self.window.set_needs_layout()

    def set_motion_axis_info(self, joint_info_list):
        while len(self.motion_axis_rows) < len(joint_info_list):
            axis_row = gui.Horiz(5)
            name_label = gui.Label("")
            value_edit = gui.TextEdit()
            value_edit.enabled = True
            value_edit.text_value = self._value_format(0)

            minus_btn = gui.Button("-")
            plus_btn = gui.Button("+")
            minus_btn.horizontal_padding_em = 0.2
            minus_btn.vertical_padding_em = 0.1
            plus_btn.horizontal_padding_em = 0.2
            plus_btn.vertical_padding_em = 0.1

            row_dict = {
                "row": axis_row,
                "label": name_label,
                "value": value_edit,
                "minus": minus_btn,
                "plus": plus_btn,
                "joint": None,
            }

            value_edit.set_on_value_changed(
                lambda text, row=row_dict:
                    self._apply_value_text(row, text)
            )

            axis_row.add_child(name_label)
            axis_row.add_stretch()
            axis_row.add_child(value_edit)
            axis_row.add_child(minus_btn)
            axis_row.add_child(plus_btn)

            axis_row.visible = False
            self.motion_panel.add_child(axis_row)
            self.motion_axis_rows.append(row_dict)

        name_counts = {}
        for r in self.motion_axis_rows:
            r["row"].visible = False
            r["joint"] = None

        for i, joint in enumerate(joint_info_list):
            r = self.motion_axis_rows[i]

            r["joint"] = joint
            base_name = joint.get("name", "")
            count = name_counts.get(base_name, 0)
            name_counts[base_name] = count + 1

            if count == 0:
                display_name = base_name
            else:
                display_name = f"{base_name}{count}"
            if len(display_name) == 1:
                display_name = " "*2 + display_name
            r["label"].text = display_name

            node = joint.get("node")

            if node is None:
                continue

            r["row"].visible = True

            current_value = joint["node"].joint_value

            r["value"].visible = True
            r["minus"].visible = True
            r["plus"].visible = True
            r["value"].text_value = self._value_format(current_value)
            r["minus"].set_on_clicked(
                lambda j=joint, row=r:
                    self._move_joint(j, row, -self.jog_override)
            )
            r["plus"].set_on_clicked(
                lambda j=joint, row=r:
                    self._move_joint(j, row, self.jog_override)
            )

    def set_signal_axis_info(self, joint_info_list):
        while len(self.signal_axis_rows) < len(joint_info_list):
            axis_row = gui.Horiz(4)
            name_label = gui.Label("")
            signal_check = gui.Checkbox("")
            signal_check.visible = False

            row_dict = {
                "row": axis_row,
                "label": name_label,
                "check": signal_check,
                "joint": None,
            }

            axis_row.add_child(name_label)
            axis_row.add_stretch()
            axis_row.add_child(signal_check)

            axis_row.visible = False

            self.signal_panel.add_child(axis_row)
            self.signal_axis_rows.append(row_dict)

        name_counts = {}
        for r in self.signal_axis_rows:
            r["row"].visible = False
            r["joint"] = None
            r["check"].visible = False

        for i, joint in enumerate(joint_info_list):
            r = self.signal_axis_rows[i]

            r["joint"] = joint
            base_name = joint.get("name", "")
            count = name_counts.get(base_name, 0)
            name_counts[base_name] = count + 1

            if count == 0:
                display_name = base_name
            else:
                display_name = f"{base_name}{count}"

            r["label"].text = display_name

            node = joint.get("node")

            if node is None:
                continue

            r["row"].visible = True
            r["check"].visible = True
            r["check"].checked = bool(joint["node"].joint_value)

            r["check"].set_on_checked(
                lambda checked, j=joint:
                    self._signal_changed(j, checked)
            )

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
        row["value"].text_value = self._value_format(current_value)

        self._refresh()

    def _signal_changed(self, joint, checked):

        if self._setting_axis_info:
            return

        value = 1.0 if checked else 0.0

        self.on_joint_move(
            joint,
            value
        )
        
        self._refresh()
    
    def _refresh(self):
        self.window.set_needs_layout()

    def _value_format(self, value):
        text = f"{value:.4f}"
        count = max(0, 2 * (10-len(text)))
        return " " * count + text
    
    def refresh_axis_values(self):
        if self._setting_axis_info:
            return

        self._setting_axis_info = True
        try:
            for r in self.motion_axis_rows:
                joint = r.get("joint")
                if joint is None:
                    continue

                node = joint.get("node")
                if node is None:
                    continue

                r["value"].text_value = self._value_format(node.joint_value)

            for r in self.signal_axis_rows:
                joint = r.get("joint")
                if joint is None:
                    continue

                node = joint.get("node")
                if node is None:
                    continue

                r["check"].checked = bool(node.joint_value)

        finally:
            self._setting_axis_info = False

        self._refresh()