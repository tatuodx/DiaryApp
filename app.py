import sys
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel, QFrame
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from openai import OpenAI

from diary_tab import DiaryTab
from todo_tab import TodoTab
from lol_pick_support_tab import LolPickSupportTab

class MainWindow(QMainWindow):
    """メインウィンドウ：lol_pick_support_tab のスタイルに合わせて白基調・丸み・上品な UI にする"""

    def __init__(self, client: OpenAI | None = None):
        super().__init__()
        self.client = client
        self.setWindowTitle("AI Diary & Todo App")
        self.resize(1000, 680)

        # グローバルフォント（Windowsで一般的なナチュラル系）
        ui_font = QFont("Yu Gothic UI", 10)
        self.setFont(ui_font)

        # 中央コンテナ（余白を取りつつカード風に配置）
        container = QWidget()
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(16, 16, 16, 16)
        container_layout.setSpacing(12)

        # タイトル
        title = QLabel("AI Diary & Todo App")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet("font-size:18px; font-weight:700; color:#2f3b4a;")
        container_layout.addWidget(title)

        # カードフレーム（内側にタブを配置）
        card = QFrame()
        card.setObjectName("cardFrame")
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        # タブ
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.North)
        tabs.setDocumentMode(True)
        tabs.setMovable(False)

        diary_tab = DiaryTab(client=self.client)
        todo_tab = TodoTab()
        lol_tab = LolPickSupportTab(client=self.client)

        tabs.addTab(diary_tab, "日記")
        tabs.addTab(todo_tab, "Todoリスト")
        tabs.addTab(lol_tab, "LoLピック支援")

        card_layout.addWidget(tabs)
        card.setLayout(card_layout)

        container_layout.addWidget(card)
        container.setLayout(container_layout)
        self.setCentralWidget(container)

        # 全体スタイル（白基調・丸み・柔らかい色味を適用）
        self.setStyleSheet("""
            QWidget {
                background-color: #f7f8fb;
                color: #333333;
                font-family: "Yu Gothic UI", "Segoe UI", "Meiryo", sans-serif;
            }
            #cardFrame {
                background: #ffffff;
                border-radius: 14px;
                border: 1px solid #eef1f6;
            }
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background: transparent;
                color: #4a5560;
                padding: 10px 14px;
                border-radius: 8px;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #e9f6ff, stop:1 #d7ecff);
                color: #1f4f8b;
                font-weight: 700;
                border: 1px solid #d7eefa;
            }
            QLabel {
                color: #444444;
            }
        """)

def create_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

if __name__ == "__main__":
    client = create_openai_client()
    app = QApplication(sys.argv)
    main_win = MainWindow(client=client)
    main_win.show()
    sys.exit(app.exec())
