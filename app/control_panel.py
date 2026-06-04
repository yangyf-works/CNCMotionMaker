from pathlib import Path

import open3d.visualization.gui as gui # type: ignore

class ControlPanel:

    def __init__(self, json_dir: Path, on_json_selected):

        self.json_dir = json_dir
        self.on_json_selected = on_json_selected

        self.json_files = self._find_json_files()

        self.widget = gui.Vert(
            10,
            gui.Margins(10, 10, 10, 10)
        )

        title = gui.Label("CNCMotionMaker")
        self.widget.add_child(title)

        self.json_combo = gui.Combobox()

        if self.json_files:
            for path in self.json_files:
                self.json_combo.add_item(path.name)
        else:
            self.json_combo.add_item("(None JSON File)")

        self.json_combo.set_on_selection_changed(
            self._on_combo_changed
        )

        self.widget.add_child(self.json_combo)

        load_button = gui.Button("Load Model")
        load_button.set_on_clicked(self._on_load_clicked)

        self.widget.add_child(load_button)

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


        