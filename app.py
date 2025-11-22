import sys
import os
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget
from openai import OpenAI

from diary_tab import DiaryTab
from todo_tab import TodoTab
from lol_pick_support_tab import LolPickSupportTab

if __name__ == "__main__":
    # OpenAI クライアント（環境変数から取得）
    api_key = os.environ.get("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key) if api_key else None

    app = QApplication(sys.argv)
    main_win = QMainWindow()
    main_win.setWindowTitle("AI Diary & Todo App")
    main_win.resize(800, 600)

    tabs = QTabWidget()
    tabs.setTabPosition(QTabWidget.West)

    diary_tab = DiaryTab(client=client)
    todo_tab = TodoTab()
    lol_tab = LolPickSupportTab(client=client)

    tabs.addTab(diary_tab, "日記")
    tabs.addTab(todo_tab, "Todoリスト")
    tabs.addTab(lol_tab, "LoLピック支援")

    main_win.setCentralWidget(tabs)
    main_win.show()
    sys.exit(app.exec())
