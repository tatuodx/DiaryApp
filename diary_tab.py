from PySide6.QtWidgets import QWidget, QTextEdit, QPushButton, QVBoxLayout, QHBoxLayout, QMessageBox
from PySide6.QtCore import Qt
from openai import OpenAI

DIARY_FILE = "diary.txt"

class DiaryTab(QWidget):
    def __init__(self, client: OpenAI | None = None, parent=None):
        super().__init__(parent)
        self.client = client

        self.text_edit = QTextEdit()

        self.save_button = QPushButton("保存")
        self.load_button = QPushButton("読み込み")
        self.ai_button = QPushButton("AIコメント生成")
        if self.client is None:
            self.ai_button.setEnabled(False)

        h_layout = QHBoxLayout()
        h_layout.addWidget(self.load_button)
        h_layout.addWidget(self.save_button)
        h_layout.addWidget(self.ai_button)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        layout.addLayout(h_layout)
        self.setLayout(layout)

        self.save_button.clicked.connect(self.save_diary)
        self.load_button.clicked.connect(self.load_diary)
        self.ai_button.clicked.connect(self.generate_ai_comment)

    def save_diary(self):
        text = self.text_edit.toPlainText()
        try:
            with open(DIARY_FILE, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "保存完了", "日記を保存しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{e}")

    def load_diary(self):
        import os
        if not os.path.exists(DIARY_FILE):
            QMessageBox.information(self, "情報", "日記ファイルがありません。")
            return
        try:
            with open(DIARY_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            self.text_edit.setPlainText(content)
            QMessageBox.information(self, "読み込み完了", "日記を読み込みました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"読み込みに失敗しました:\n{e}")

    def generate_ai_comment(self):
        if self.client is None:
            QMessageBox.warning(self, "API未設定", "OPENAI_API_KEY が設定されていません。環境変数を設定してください。")
            return

        text = self.text_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "エラー", "日記が空です。")
            return

        try:
            response = self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "あなたは優しい日記コーチとして、日本語で短くコメントを返してください。"},
                    {"role": "user", "content": f"今日の日記です:\n{text}\nこの内容にコメントをください。"}
                ]
            )
            ai_comment = response.choices[0].message["content"]
            QMessageBox.information(self, "AI コメント", ai_comment)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"APIエラー:\n{e}")