import os
import json
from PySide6.QtWidgets import QWidget, QListWidget, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout, QListWidgetItem, QMessageBox
from PySide6.QtCore import Qt

TODO_FILE = "todos.json"

class TodoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.list_widget = QListWidget()
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("新しいTODOを入力して Enter／追加ボタン")

        self.add_button = QPushButton("追加")
        self.remove_button = QPushButton("削除（選択）")
        self.save_button = QPushButton("保存")
        self.load_button = QPushButton("読み込み")

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.add_button)
        btn_layout.addWidget(self.remove_button)
        btn_layout.addWidget(self.load_button)
        btn_layout.addWidget(self.save_button)

        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        layout.addWidget(self.input_line)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.add_button.clicked.connect(self.add_item)
        self.remove_button.clicked.connect(self.remove_selected)
        self.save_button.clicked.connect(self.save_todos)
        self.load_button.clicked.connect(self.load_todos)
        self.input_line.returnPressed.connect(self.add_item)

        self.load_todos()

    def add_item(self):
        text = self.input_line.text().strip()
        if not text:
            return
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        item.setCheckState(Qt.Unchecked)
        self.list_widget.addItem(item)
        self.input_line.clear()

    def remove_selected(self):
        for itm in self.list_widget.selectedItems():
            row = self.list_widget.row(itm)
            self.list_widget.takeItem(row)

    def save_todos(self):
        todos = []
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            todos.append({"text": it.text(), "done": it.checkState() == Qt.Checked})
        try:
            with open(TODO_FILE, "w", encoding="utf-8") as f:
                json.dump(todos, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "保存完了", "TODOを保存しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{e}")

    def load_todos(self):
        if not os.path.exists(TODO_FILE):
            return
        try:
            with open(TODO_FILE, "r", encoding="utf-8") as f:
                todos = json.load(f)
            self.list_widget.clear()
            for t in todos:
                item = QListWidgetItem(t.get("text", ""))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if t.get("done") else Qt.Unchecked)
                self.list_widget.addItem(item)
        except Exception:
            pass