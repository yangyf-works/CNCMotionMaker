from pathlib import Path

import open3d.visualization.gui as gui
import traceback

class ControlPanel:

    def __init__(self, json_dir: Path, on_json_selected, on_joint_move):

        self.json_dir = json_dir
        self.on_json_selected = on_json_selected
        self.on_joint_move = on_joint_move

        self.json_files = self._find_json_files()

        self.widget = gui.Vert(
            10,
            gui.Margins(10, 10, 10, 10)
        )

        title = gui.Label("Control Panel")
        self.widget.add_child(title)

        self.widget.add_child(gui.Label("JSON File"))

        self.json_combo = gui.Combobox()

        if self.json_files:
            for path in self.json_files:
                self.json_combo.add_item(path.name)
        else:
            self.json_combo.add_item("(JSONファイルなし)")

        self.json_combo.set_on_selection_changed(
            self._on_combo_changed
        )

        self.widget.add_child(self.json_combo)

        load_button = gui.Button("Load Selected JSON")
        load_button.set_on_clicked(self._on_load_clicked)

        self.widget.add_child(load_button)

        self.axis_label = gui.Label("Axis Info")
        self.widget.add_child(self.axis_label)

        #
        # 軸ボタン格納エリア
        #
        self.axis_layout = gui.Vert()
        self.widget.add_child(self.axis_layout)

    def _find_json_files(self):

        if not self.json_dir.exists():
            self.json_dir.mkdir(parents=True, exist_ok=True)
            return []

        return sorted(
            self.json_dir.glob("*.json")
        )

    def _on_combo_changed(self, text, index):

        print("Combo changed:", text, index)

    def _on_load_clicked(self):

        index = self.json_combo.selected_index

        if index < 0:
            return

        if not self.json_files:
            print("JSONファイルがありません")
            return

        json_path = self.json_files[index]

        self.on_json_selected(json_path)

   
    def set_axis_info(self, joint_info_list):
        try:
            print("set_axis_info")

            #
            # 以前のUIを削除
            #
            while len(self.axis_layout.get_children()) > 0:
                self.axis_layout.remove_child(
                    self.axis_layout.get_children()[0]
                )

            if not joint_info_list:

                self.axis_layout.add_child(
                    gui.Label("軸情報なし")
                )

                return

            for joint in joint_info_list:

                #
                # 軸名
                #
                label = gui.Label(joint["name"])

                self.axis_layout.add_child(label)

                #
                # ボタン行
                #
                button_row = gui.Horiz()

                plus_btn = gui.Button("+")
                minus_btn = gui.Button("-")

                plus_btn.set_on_clicked(
                    lambda j=joint:
                        self.on_joint_move(j, +0.1)
                )

                minus_btn.set_on_clicked(
                    lambda j=joint:
                        self.on_joint_move(j, -0.1)
                )

                button_row.add_child(plus_btn)
                button_row.add_child(minus_btn)

                self.axis_layout.add_child(button_row)
                
        except Exception:
            traceback.print_exc()

        