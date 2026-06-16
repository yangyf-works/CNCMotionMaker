from pathlib import Path

import open3d.visualization.gui as gui # type: ignore

class ControlPanel:

    def __init__(self, json_dir: Path, on_json_selected):

        self.json_dir = json_dir
        self.on_json_selected = on_json_selected

        self.json_files = self._find_json_files()

        self.widget = gui.Vert(
            5,
            gui.Margins(5, 5, 1, 5)
        )

        title = gui.Label("Model select")
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
        load_button.horizontal_padding_em = 0.2
        load_button.vertical_padding_em = 0.1
        load_button.set_on_clicked(self._on_load_clicked)

        self.widget.add_child(load_button)
        self._add_manual()

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

    def _add_manual(self):
        mouse_manual = self._create_manual_table(
            "Mouse",
            [
                ("Left :", "Rotate View"),
                ("Middle :", "Rotate Light"),
                ("Right :", "Pan View"),
                ("Wheel :", "Zoom In/Out"),
            ]
        )
        self.widget.add_child(mouse_manual)

        key_manual = self._create_manual_table(
            "Key",
            [
                ("Arrow Keys :", "Orbit View"),
                ("W/A/S/D :", "Pan View"),
                ("Q/E :", "Roll View"),
            ]
        )
        self.widget.add_child(key_manual)

        ctrlkey_manual = self._create_manual_table(
            "Ctrl + Key",
            [
                ("Up :", "Zoom In"),
                ("Down :", "Zoom Out"),
                ("Left :", "Narrow FOV"),
                ("Right :", "Wide FOV"),
                ("C :", "Reset Camera"),
                ("L :", "Reset Light"),
                ("A :", "Show Joint"),
                ("S :", "Export STL"),
            ]
        )
        self.widget.add_child(ctrlkey_manual)

    def _create_manual_table(self, title, rows):
        manual_box = gui.CollapsableVert(
            title,
            2,
            gui.Margins(2, 5, 0, 0)
        )

        table = gui.Horiz(1)

        operation_col = gui.Vert(0)
        description_col = gui.Vert(0)

        table.add_child(operation_col)
        table.add_child(description_col)

        for operation, description in rows:
            operation_col.add_child(gui.Label(operation))
            description_col.add_child(gui.Label(description))

        manual_box.add_child(table)

        return manual_box
            