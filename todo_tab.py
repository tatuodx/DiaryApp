import os
import json
from PySide6.QtWidgets import (
    QWidget, QListWidget, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QListWidgetItem, QMessageBox, QGraphicsDropShadowEffect, QLabel
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

TODO_FILE = "todos.json"


class TodoTab(QWidget):
    """Todo タブ: 追加・削除・保存・読み込みができるシンプルな UI"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # フォント設定（ナチュラル系のポピュラーなフォントを優先）
        ui_font = QFont("Yu Gothic UI", 10)
        self.setFont(ui_font)

        # ウィジェット作成
        self.list_widget = QListWidget()
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("新しいTODOを入力して Enter または「追加」を押してください")

        self.add_button = QPushButton("追加")
        self.remove_button = QPushButton("削除（選択）")
        self.save_button = QPushButton("保存")
        self.load_button = QPushButton("読み込み")

        # 見出しラベル
        self.header_label = QLabel("Todo リスト")
        self.header_label.setAlignment(Qt.AlignLeft)
        self.header_label.setStyleSheet("font-weight:700; color:#444444;")

        # レイアウト構築
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        main_layout.addWidget(self.header_label)

        # 入力行
        input_h = QHBoxLayout()
        input_h.setSpacing(8)
        input_h.addWidget(self.input_line)
        input_h.addWidget(self.add_button)
        main_layout.addLayout(input_h)

        # リスト（影をつけて浮かせる）
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 25))
        self.list_widget.setGraphicsEffect(shadow)
        main_layout.addWidget(self.list_widget)

        # ボタン群
        btn_h = QHBoxLayout()
        btn_h.setSpacing(8)
        btn_h.addWidget(self.remove_button)
        btn_h.addStretch()
        btn_h.addWidget(self.load_button)
        btn_h.addWidget(self.save_button)
        main_layout.addLayout(btn_h)

        self.setLayout(main_layout)

        # スタイル（白基調・丸み・柔らかい色を lol_pick_support_tab に合わせる）
        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                color: #333333;
                font-family: "Yu Gothic UI", "Segoe UI", "Meiryo", sans-serif;
            }
            QListWidget {
                border: 1px solid #f0f0f0;
                border-radius: 12px;
                padding: 6px;
                background: #fafafa;
            }
            QListWidget::item {
                padding: 8px 10px;
            }
            QLineEdit {
                border: 1px solid #efecec;
                border-radius: 10px;
                padding: 8px;
                background: #ffffff;
            }
            QPushButton {
                border-radius: 10px;
                padding: 6px 12px;
            }
            QPushButton#primary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6cc3ff, stop:1 #3aa0ff);
                color: white;
                border: none;
                font-weight: 600;
            }
            QPushButton#secondary {
                background: #ffffff;
                color: #444;
                border: 1px solid #e8e8e8;
            }
        """)

        # ボタンのオブジェクト名でスタイルを分ける
        self.add_button.setObjectName("primary")
        self.save_button.setObjectName("primary")
        self.remove_button.setObjectName("secondary")
        self.load_button.setObjectName("secondary")

        # シグナル接続
        self.add_button.clicked.connect(self.add_item)
        self.input_line.returnPressed.connect(self.add_item)
        self.remove_button.clicked.connect(self.remove_selected)
        self.save_button.clicked.connect(self.save_todos)
        self.load_button.clicked.connect(self.load_todos)

        # 起動時に既存ファイルがあれば読み込む
        self.load_todos()

    def add_item(self):
        """入力欄の文字列をタスクとして追加する"""
        text = self.input_line.text().strip()
        if not text:
            return
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.list_widget.addItem(item)
        self.input_line.clear()
        # 追加後に選択状態を外す
        self.list_widget.clearSelection()

    def remove_selected(self):
        """選択中のアイテムを削除する"""
        selected = self.list_widget.selectedItems()
        if not selected:
            QMessageBox.information(self, "削除", "削除する項目を選択してください。")
            return
        for it in selected:
            row = self.list_widget.row(it)
            self.list_widget.takeItem(row)

    def save_todos(self):
        """リストを JSON ファイルに保存する"""
        try:
            todos = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
            with open(TODO_FILE, "w", encoding="utf-8") as f:
                json.dump(todos, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "保存", f"TODO を保存しました ({TODO_FILE})")
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"保存に失敗しました:\n{e}")

    def load_todos(self):
        """JSON ファイルから読み込んでリストに反映する"""
        if not os.path.exists(TODO_FILE):
            return
        try:
            with open(TODO_FILE, "r", encoding="utf-8") as f:
                todos = json.load(f)
            self.list_widget.clear()
            for t in todos:
                item = QListWidgetItem(str(t))
                item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.list_widget.addItem(item)
        except Exception as e:
            QMessageBox.critical(self, "読み込みエラー", f"読み込みに失敗しました:\n{e}")