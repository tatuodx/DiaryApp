from PySide6.QtWidgets import (
    QWidget,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QInputDialog,
    QScrollArea,
    QLineEdit,
    QLabel,
    QFormLayout,
    QTimeEdit,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QRect, QTime
import os
import datetime
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from openai import OpenAI
import json

DIARY_FILE = "diary.txt"


class TimelineWidget(QWidget):
    """06:00 〜 翌日 06:00 のタイムライン。15分単位のスロットでイベントを作成・編集できます。
    描画や操作のロジックは従来の実装を踏襲していますが、見た目を白基調・丸みのあるスタイルに合わせています。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_min = 6 * 60  # 06:00
        self.total_minutes = 24 * 60
        self.slot_minutes = 15
        self.slots = self.total_minutes // self.slot_minutes  # 96
        self.slot_height = 12
        self.left_margin = 60
        self.min_width = 500
        self.setMinimumSize(self.min_width, self.slot_height * self.slots)

        self.events = []

        # 選択・編集 state
        self.selecting = False
        self.sel_start_y = 0
        self.sel_end_y = 0
        self.mode = None
        self.edit_index = None
        self.move_anchor_y = 0
        self.resize_anchor_y = 0
        self._orig_event = None
        self.selected_index = None

        # 見た目用フォント
        self._label_font = QFont("Yu Gothic UI", 9)

    def sizeHint(self):
        return self.minimumSize()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        w = self.width()

        # グリッド線
        pen = QPen(QColor("#f0f0f0"))
        painter.setPen(pen)
        for i in range(self.slots + 1):
            y = i * self.slot_height
            painter.drawLine(self.left_margin, y, w, y)

        # 時刻ラベル（1時間ごと）
        painter.setFont(self._label_font)
        painter.setPen(QColor("#666666"))
        for i in range(0, self.slots + 1, 4):
            minutes = self.start_min + i * self.slot_minutes
            hour = (minutes // 60) % 24
            label = f"{hour:02d}:00"
            y = i * self.slot_height
            painter.drawText(8, y + (self.slot_height // 2) + 5, label)

        # イベント描画
        for idx, ev in enumerate(sorted(self.events, key=lambda e: e["start"])):
            top_min = max(ev["start"] - self.start_min, 0)
            bottom_min = min(ev["end"] - self.start_min, self.total_minutes)
            if bottom_min <= 0 or top_min >= self.total_minutes:
                continue
            top_slot = int(round(top_min / self.slot_minutes))
            bottom_slot = int(round(bottom_min / self.slot_minutes))
            top_y = top_slot * self.slot_height
            height = max(2, (bottom_slot - top_slot) * self.slot_height - 1)

            rect = QRect(self.left_margin + 8, top_y + 2, w - self.left_margin - 16, height)
            painter.setPen(QPen(QColor("#66a3ff")))
            painter.setBrush(QColor(102, 163, 255, 220))
            painter.drawRoundedRect(rect, 6, 6)

            # テキスト
            painter.setPen(QColor("#ffffff"))
            fm = painter.fontMetrics()
            title = ev.get("title", "(無題)")
            start_h = (ev["start"] // 60) % 24
            start_m = ev["start"] % 60
            end_h = (ev["end"] // 60) % 24
            end_m = ev["end"] % 60
            time_label = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"
            text = f"{time_label} {title}"
            elided = fm.elidedText(text, Qt.ElideRight, rect.width() - 10)
            painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, elided)

            # 選択時の境界線
            if self.selected_index is not None:
                sel_ev = (
                    self.events[self.selected_index]
                    if 0 <= self.selected_index < len(self.events)
                    else None
                )
                if sel_ev is ev:
                    painter.setPen(QPen(QColor("#ffb74d"), 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(rect, 6, 6)

        # 現在選択中のドラッグ矩形
        if self.selecting:
            y1 = min(self.sel_start_y, self.sel_end_y)
            y2 = max(self.sel_start_y, self.sel_end_y)
            sel_rect = QRect(self.left_margin + 8, y1, w - self.left_margin - 16, max(2, y2 - y1))
            painter.setPen(QPen(QColor("#a5d6a7")))
            painter.setBrush(QColor(165, 214, 167, 120))
            painter.drawRoundedRect(sel_rect, 6, 6)

    # 以下マウス操作・編集ロジックは既存の挙動を保つ
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            posy = max(0, min(self.height(), event.pos().y()))
            hit = self._hit_test(event.pos())
            if hit is None:
                self.mode = "creating"
                self.selecting = True
                self.sel_start_y = posy
                self.sel_end_y = posy
            else:
                kind, idx = hit
                self.edit_index = idx
                if kind == "inside":
                    self.mode = "moving"
                    self.move_anchor_y = posy
                    self._orig_event = dict(self.events[idx])
                elif kind == "top":
                    self.mode = "resize_top"
                    self.resize_anchor_y = posy
                    self._orig_event = dict(self.events[idx])
                elif kind == "bottom":
                    self.mode = "resize_bottom"
                    self.resize_anchor_y = posy
                    self._orig_event = dict(self.events[idx])
            self.update()

    def mouseMoveEvent(self, event):
        posy = max(0, min(self.height(), event.pos().y()))
        if self.mode == "creating" and self.selecting:
            self.sel_end_y = posy
            self.update()
        elif self.mode == "moving" and self.edit_index is not None:
            dy = posy - self.move_anchor_y
            dslots = int(round(dy / self.slot_height))
            dminutes = dslots * self.slot_minutes
            orig = self._orig_event
            duration = orig["end"] - orig["start"]
            new_start = orig["start"] + dminutes
            new_end = new_start + duration
            min_start = self.start_min
            max_end = self.start_min + self.total_minutes
            if new_start < min_start:
                new_start = min_start
                new_end = new_start + duration
            if new_end > max_end:
                new_end = max_end
                new_start = new_end - duration
            self.events[self.edit_index]["start"] = new_start
            self.events[self.edit_index]["end"] = new_end
            self.update()
            # notify detail panel if this is the selected event
            try:
                if (
                    hasattr(self, "selection_changed_callback")
                    and self.selection_changed_callback
                    and self.selected_index == self.edit_index
                ):
                    self.selection_changed_callback(self.selected_index)
            except Exception:
                pass
        elif self.mode in ("resize_top", "resize_bottom") and self.edit_index is not None:
            orig = self._orig_event
            if self.mode == "resize_top":
                dy = posy - self.resize_anchor_y
                dslots = int(round(dy / self.slot_height))
                dminutes = dslots * self.slot_minutes
                new_start = orig["start"] + dminutes
                min_start = self.start_min
                max_start = orig["end"] - self.slot_minutes
                new_start = max(min_start, min(max_start, new_start))
                self.events[self.edit_index]["start"] = new_start
            else:
                dy = posy - self.resize_anchor_y
                dslots = int(round(dy / self.slot_height))
                dminutes = dslots * self.slot_minutes
                new_end = orig["end"] + dminutes
                min_end = orig["start"] + self.slot_minutes
                max_end = self.start_min + self.total_minutes
                new_end = max(min_end, min(max_end, new_end))
                self.events[self.edit_index]["end"] = new_end
            self.update()
            try:
                if (
                    hasattr(self, "selection_changed_callback")
                    and self.selection_changed_callback
                    and self.selected_index == self.edit_index
                ):
                    self.selection_changed_callback(self.selected_index)
            except Exception:
                pass

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.mode == "creating" and self.selecting:
                self.selecting = False
                self.sel_end_y = max(0, min(self.height(), event.pos().y()))
                y1 = min(self.sel_start_y, self.sel_end_y)
                y2 = max(self.sel_start_y, self.sel_end_y)
                start_slot = int(round(y1 / self.slot_height))
                end_slot = int(round(y2 / self.slot_height))
                if end_slot == start_slot:
                    end_slot = start_slot + 1

                start_min_offset = start_slot * self.slot_minutes
                end_min_offset = end_slot * self.slot_minutes
                start_abs = self.start_min + start_min_offset
                end_abs = self.start_min + end_min_offset

                title, ok = QInputDialog.getText(self, "イベントタイトル", "イベント名を入力してください:")
                if ok and title.strip():
                    ev = {
                        "start": start_abs,
                        "end": end_abs,
                        "title": title.strip(),
                        "location": "",
                        "reflection": "",
                    }
                    self.events.append(ev)
                    self.select_event(len(self.events) - 1)
            if not self.selecting:
                hit = self._hit_test(event.pos())
                if hit is not None:
                    kind, idx = hit
                    self.select_event(idx)
            self.mode = None
            self.edit_index = None
            self._orig_event = None
            self.move_anchor_y = 0
            self.resize_anchor_y = 0
            self.update()

    def select_event(self, index: int | None):
        if index is None:
            self.selected_index = None
        elif 0 <= index < len(self.events):
            self.selected_index = index
        else:
            self.selected_index = None
        self.update()
        try:
            if hasattr(self, "selection_changed_callback") and self.selection_changed_callback:
                self.selection_changed_callback(self.selected_index)
        except Exception:
            pass

    def get_event(self, index: int):
        if 0 <= index < len(self.events):
            return self.events[index]
        return None

    def update_event(self, index: int, notify: bool = True, **kwargs):
        if 0 <= index < len(self.events):
            ev = self.events[index]
            for k, v in kwargs.items():
                if k in ("start", "end"):
                    ev[k] = int(v)
                else:
                    ev[k] = v
            self.update()
            try:
                if (
                    notify
                    and hasattr(self, "selection_changed_callback")
                    and self.selection_changed_callback
                    and self.selected_index == index
                ):
                    self.selection_changed_callback(self.selected_index)
            except Exception:
                pass

    def _event_rect(self, ev):
        w = self.width()
        top_min = max(ev["start"] - self.start_min, 0)
        bottom_min = min(ev["end"] - self.start_min, self.total_minutes)
        top_slot = int(round(top_min / self.slot_minutes))
        bottom_slot = int(round(bottom_min / self.slot_minutes))
        top_y = top_slot * self.slot_height
        height = max(2, (bottom_slot - top_slot) * self.slot_height - 1)
        return QRect(self.left_margin + 8, top_y + 2, w - self.left_margin - 16, height)

    def _hit_test(self, qpoint):
        for idx in range(len(self.events) - 1, -1, -1):
            ev = self.events[idx]
            rect = self._event_rect(ev)
            if rect.contains(qpoint):
                y = qpoint.y()
                top_edge = rect.top()
                bottom_edge = rect.bottom()
                margin = max(6, int(self.slot_height / 2))
                if abs(y - top_edge) <= margin:
                    return ("top", idx)
                if abs(y - bottom_edge) <= margin:
                    return ("bottom", idx)
                return ("inside", idx)
        return None

    def to_json(self):
        return json.dumps({"events": self.events}, ensure_ascii=False, indent=2)

    def from_json(self, content: str):
        try:
            data = json.loads(content)
            raw_events = None
            if isinstance(data, dict) and "events" in data and isinstance(data["events"], list):
                raw_events = data["events"]
            elif isinstance(data, list):
                raw_events = data
            if raw_events is None:
                return False
            cleaned = []
            for item in raw_events:
                if not isinstance(item, dict):
                    continue
                try:
                    start = int(item.get("start", self.start_min))
                except Exception:
                    try:
                        start = int(float(item.get("start", self.start_min)))
                    except Exception:
                        start = self.start_min
                try:
                    end = int(item.get("end", start + self.slot_minutes))
                except Exception:
                    try:
                        end = int(float(item.get("end", start + self.slot_minutes)))
                    except Exception:
                        end = start + self.slot_minutes
                if end <= start:
                    end = start + self.slot_minutes
                min_t = self.start_min
                max_t = self.start_min + self.total_minutes
                if start < min_t:
                    start = min_t
                if end > max_t:
                    end = max_t
                if start >= max_t:
                    # skip events completely outside range
                    continue
                title = item.get("title", "") or ""
                location = item.get("location", "") or ""
                reflection = item.get("reflection", "") or ""
                cleaned.append(
                    {
                        "start": start,
                        "end": end,
                        "title": title,
                        "location": location,
                        "reflection": reflection,
                    }
                )
            self.events = cleaned
            self.update()
            return True
        except Exception:
            return False

    def get_text_summary(self) -> str:
        if not self.events:
            return ""
        parts = []
        for ev in sorted(self.events, key=lambda e: e["start"]):
            sh = (ev["start"] // 60) % 24
            sm = ev["start"] % 60
            eh = (ev["end"] // 60) % 24
            em = ev["end"] % 60
            parts.append(f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d} {ev.get('title','(無題)')}")
        return "\n".join(parts)


class DiaryTab(QWidget):
    """日記タブのメイン UI。見た目を lol_pick_support_tab に合わせて白基調・丸み・ポップで上品にします。"""

    def __init__(self, client: OpenAI | None = None, parent=None):
        super().__init__(parent)
        self.client = client

        # フォント設定（ナチュラルでポピュラーなフォント）
        ui_font = QFont("Yu Gothic UI", 10)
        self.setFont(ui_font)

        # タイムライン（スクロール内）
        self.timeline = TimelineWidget()
        self.timeline.selection_changed_callback = None
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.timeline)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(400)

        # ボタン群
        self.save_button = QPushButton("保存")
        self.load_button = QPushButton("読み込み")
        self.ai_button = QPushButton("AIコメント生成")
        if self.client is None:
            self.ai_button.setEnabled(False)

        # 左側: タイムライン + 操作
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.load_button)
        h_layout.addWidget(self.save_button)
        h_layout.addWidget(self.ai_button)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(8)
        left_layout.addWidget(self.scroll)
        left_layout.addLayout(h_layout)

        # 右側: 詳細パネル
        detail_widget = QWidget()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        self.title_edit = QLineEdit()
        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("HH:mm")
        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("HH:mm")
        self.location_edit = QLineEdit()
        self.reflection_edit = QTextEdit()
        self.reflection_edit.setMinimumHeight(200)
        self.reflection_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        form.addRow(QLabel("タイトル"), self.title_edit)
        form.addRow(QLabel("開始時刻"), self.start_time_edit)
        form.addRow(QLabel("終了時刻"), self.end_time_edit)
        form.addRow(QLabel("場所"), self.location_edit)
        form.addRow(QLabel("振り返り"), self.reflection_edit)

        # 詳細パネルのボタン
        self.delete_button = QPushButton("削除")
        detail_buttons = QHBoxLayout()
        detail_buttons.addStretch()
        detail_buttons.addWidget(self.delete_button)

        dv = QVBoxLayout()
        dv.setContentsMargins(8, 8, 8, 8)
        dv.setSpacing(8)
        dv.addLayout(form)
        dv.addLayout(detail_buttons)
        detail_widget.setLayout(dv)

        # detail_widget用のシャドウエフェクト
        shadow_detail = QGraphicsDropShadowEffect(self)
        shadow_detail.setBlurRadius(12)
        shadow_detail.setOffset(0, 6)
        shadow_detail.setColor(QColor(0, 0, 0, 30))
        detail_widget.setGraphicsEffect(shadow_detail)
        # scroll用のシャドウエフェクト
        shadow_scroll = QGraphicsDropShadowEffect(self)
        shadow_scroll.setBlurRadius(12)
        shadow_scroll.setOffset(0, 6)
        shadow_scroll.setColor(QColor(0, 0, 0, 30))
        self.scroll.setGraphicsEffect(shadow_scroll)

        # メインレイアウトを左右に分割
        main_h = QHBoxLayout()
        main_h.addLayout(left_layout, 1)
        main_h.addWidget(detail_widget, 1)
        main_h.setContentsMargins(12, 12, 12, 12)
        main_h.setSpacing(12)
        self.setLayout(main_h)

        # シグナル接続
        self.save_button.clicked.connect(self.save_diary)
        self.load_button.clicked.connect(self.load_diary)
        self.ai_button.clicked.connect(self.generate_ai_comment)
        self.timeline.selection_changed_callback = self.on_timeline_selection_changed

        self.title_edit.editingFinished.connect(self._on_title_changed)
        self.start_time_edit.timeChanged.connect(self._on_start_time_changed)
        self.end_time_edit.timeChanged.connect(self._on_end_time_changed)
        self.location_edit.editingFinished.connect(self._on_location_changed)
        self.reflection_edit.textChanged.connect(self._on_reflection_changed)
        self.delete_button.clicked.connect(self._on_delete_event)
        self.on_timeline_selection_changed(None)

        # スタイルシート（白基調・丸み・柔らかい色）
        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                color: #333333;
                font-family: "Yu Gothic UI", "Segoe UI", "Meiryo", sans-serif;
            }
            QLabel {
                color: #444444;
                font-weight: 600;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QLineEdit, QTimeEdit, QTextEdit {
                border: 1px solid #efecec;
                border-radius: 10px;
                padding: 6px 8px;
                background: #ffffff;
            }
            QTextEdit {
                background: #fbfbfb;
                border-radius: 10px;
            }
            QPushButton {
                border-radius: 10px;
                padding: 6px 12px;
            }
            QPushButton:disabled {
                background: #f5f5f5;
                color: #999999;
            }
            /* プライマリボタンのグラデーション。万一無効になっても背景色で視認性を確保 */
            QPushButton#primary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6cc3ff, stop:1 #3aa0ff);
                background-color: #3aa0ff;
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

        # ボタンにオブジェクト名をつけてスタイル区別
        self.save_button.setObjectName("secondary")
        self.ai_button.setObjectName("primary")
        self.load_button.setObjectName("secondary")
        self.delete_button.setObjectName("secondary")

        # 自動で今日のファイルを読み込む（サイレント）
        self.load_diary(silent=True)

    # ---------- 既存の保存/読み込み/AI 関連処理 ----------
    def save_diary(self):
        content = self.timeline.to_json()
        try:
            diaries_dir = os.path.join(os.path.dirname(__file__), "Diaries")
            os.makedirs(diaries_dir, exist_ok=True)
            filename = datetime.date.today().strftime("%Y%m%d") + ".json"
            filepath = os.path.join(diaries_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, "保存完了", f"日記（タイムライン）を保存しました:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{e}")

    def load_diary(self, silent: bool = False):
        diaries_dir = os.path.join(os.path.dirname(__file__), "Diaries")
        filename = datetime.date.today().strftime("%Y%m%d") + ".json"
        filepath = os.path.join(diaries_dir, filename)
        if not os.path.exists(filepath):
            if not silent:
                QMessageBox.information(self, "情報", f"日記ファイルがありません:\n{filepath}")
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if self.timeline.from_json(content):
                if not silent:
                    QMessageBox.information(self, "読み込み完了", f"日記（タイムライン）を読み込みました:\n{filepath}")
            else:
                if not silent:
                    QMessageBox.information(self, "読み込み完了", "ファイルは JSON 形式ではありません。内容は表示されません。")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "エラー", f"読み込みに失敗しました:\n{e}")

    def generate_ai_comment(self):
        if self.client is None:
            QMessageBox.warning(self, "API未設定", "OPENAI_API_KEY が設定されていません。環境変数を設定してください。")
            return
        summary = self.timeline.get_text_summary()
        if not summary.strip():
            QMessageBox.warning(self, "エラー", "イベントがありません。")
            return
        try:
            response = self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "あなたは優しい日記コーチとして、日本語で短くコメントを返してください。"},
                    {"role": "user", "content": f"今日の出来事タイムラインです:\n{summary}\nこの内容にコメントしてください。"},
                ],
            )
            ai_comment = response.choices[0].message["content"]
            QMessageBox.information(self, "AI コメント", ai_comment)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"APIエラー:\n{e}")

    # ---------- detail panel handlers ----------
    def _minutes_to_qtime(self, minutes: int) -> QTime:
        h = (minutes // 60) % 24
        m = minutes % 60
        return QTime(h, m)

    def _qtime_to_minutes(self, qtime: QTime) -> int:
        return qtime.hour() * 60 + qtime.minute()

    def on_timeline_selection_changed(self, index: int | None):
        if index is None:
            self.title_edit.setText("")
            self.start_time_edit.setTime(QTime(6, 0))
            self.end_time_edit.setTime(QTime(7, 0))
            self.location_edit.setText("")
            self.reflection_edit.setPlainText("")
            self.title_edit.setEnabled(False)
            self.start_time_edit.setEnabled(False)
            self.end_time_edit.setEnabled(False)
            self.location_edit.setEnabled(False)
            self.reflection_edit.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        ev = self.timeline.get_event(index)
        if ev is None:
            return
        self.title_edit.setEnabled(True)
        self.start_time_edit.setEnabled(True)
        self.end_time_edit.setEnabled(True)
        self.location_edit.setEnabled(True)
        self.reflection_edit.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.title_edit.setText(ev.get("title", ""))
        self.start_time_edit.blockSignals(True)
        self.start_time_edit.setTime(self._minutes_to_qtime(ev.get("start", self.timeline.start_min)))
        self.start_time_edit.blockSignals(False)
        self.end_time_edit.blockSignals(True)
        self.end_time_edit.setTime(self._minutes_to_qtime(ev.get("end", self.timeline.start_min + self.timeline.slot_minutes)))
        self.end_time_edit.blockSignals(False)
        self.location_edit.setText(ev.get("location", ""))
        self.reflection_edit.blockSignals(True)
        self.reflection_edit.setPlainText(ev.get("reflection", ""))
        self.reflection_edit.blockSignals(False)

    def _snap_to_slot(self, minutes: int) -> int:
        slot = self.timeline.slot_minutes
        snapped = int(round(minutes / slot)) * slot
        min_m = self.timeline.start_min
        max_m = self.timeline.start_min + self.timeline.total_minutes
        return max(min_m, min(max_m, snapped))

    def _on_title_changed(self):
        idx = self.timeline.selected_index
        if idx is None:
            return
        text = self.title_edit.text()
        self.timeline.update_event(idx, notify=False, title=text)

    def _on_start_time_changed(self, qtime: QTime):
        idx = self.timeline.selected_index
        if idx is None:
            return
        minutes = self._qtime_to_minutes(qtime)
        minutes = self._snap_to_slot(minutes)
        ev = self.timeline.get_event(idx)
        if ev is None:
            return
        end = ev.get("end", minutes + self.timeline.slot_minutes)
        if minutes >= end:
            end = minutes + self.timeline.slot_minutes
        max_end = self.timeline.start_min + self.timeline.total_minutes
        if end > max_end:
            end = max_end
        self.timeline.update_event(idx, notify=False, start=minutes, end=end)

    def _on_end_time_changed(self, qtime: QTime):
        idx = self.timeline.selected_index
        if idx is None:
            return
        minutes = self._qtime_to_minutes(qtime)
        minutes = self._snap_to_slot(minutes)
        ev = self.timeline.get_event(idx)
        if ev is None:
            return
        start = ev.get("start", minutes - self.timeline.slot_minutes)
        if minutes <= start:
            start = minutes - self.timeline.slot_minutes
        min_start = self.timeline.start_min
        if start < min_start:
            start = min_start
        self.timeline.update_event(idx, notify=False, start=start, end=minutes)

    def _on_location_changed(self):
        idx = self.timeline.selected_index
        if idx is None:
            return
        self.timeline.update_event(idx, notify=False, location=self.location_edit.text())

    def _on_reflection_changed(self):
        idx = self.timeline.selected_index
        if idx is None:
            return
        self.timeline.update_event(idx, notify=False, reflection=self.reflection_edit.toPlainText())

    def _on_delete_event(self):
        idx = self.timeline.selected_index
        if idx is None:
            return
        try:
            self.timeline.events.pop(idx)
        except Exception:
            pass
        self.timeline.select_event(None)
