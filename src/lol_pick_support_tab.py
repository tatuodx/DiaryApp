import os
import json
import unicodedata
from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QComboBox, QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox,
    QCompleter, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QStringListModel, QTimer, QByteArray, QBuffer, QRect
from PySide6.QtGui import QFont, QColor, QPixmap, QGuiApplication, QPainter, QPen
import tempfile
import time
from io import BytesIO
from openai import OpenAI

CHAMPION_JSON = os.path.join(os.path.dirname(__file__), "champion_names_ja.json")

# --- 画面中央に枠線を描画する透過オーバーレイウィジェット ---
class ScreenOverlay(QWidget):
    """デスクトップ上に透過のオーバーレイを表示し、中央に指定サイズの枠線を描画する。"""
    def __init__(self, width: int = 1280, height: int = 720, parent=None):
        super().__init__(parent)
        self._rect_w = width
        self._rect_h = height

        # ウィンドウは枠のみ表示する透明ウィンドウにする
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # マウスイベントは下のアプリに透過（クリック等を妨げない）
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # サイズはスクリーン全体に合わせる
        screen = QGuiApplication.primaryScreen()
        if screen:
            geom = screen.geometry()
            self.setGeometry(geom)
        else:
            self.resize(1920, 1080)

    def paintEvent(self, event):
        """中央に枠線（長方形）を描画する。枠は白基調デザインに合わせた柔らかい色。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 半透明に薄くスクリーン全体を暗くする（視認性のため、必要なければコメントアウト可）
        # painter.fillRect(self.rect(), QColor(0, 0, 0, 40))

        # 枠線の色・太さ
        pen = QPen(QColor(60, 120, 220, 200))  # 柔らかい青
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # 中央位置を計算して長方形を描く
        sw = self.width()
        sh = self.height()
        rw = min(self._rect_w, sw - 40)
        rh = min(self._rect_h, sh - 40)
        rx = (sw - rw) // 2
        ry = (sh - rh) // 2
        # 角を丸く描画（丸みを持たせる）
        painter.drawRoundedRect(rx, ry, rw, rh, 12, 12)

class LolPickSupportTab(QWidget):
    def __init__(self, client: OpenAI | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.champions = self._load_champions()
        # スクリーンオーバーレイ（中央に 960x540 枠を表示）
        self._overlay = ScreenOverlay(1280, 720)
        self._overlay.hide()

        # UI フォント設定（Windows でポピュラーなフォントを優先）
        ui_font = QFont("Yu Gothic UI", 10)
        self.setFont(ui_font)

        # バン：10個（5×2段）
        self.ban_combos = [QComboBox() for _ in range(10)]
        for cb in self.ban_combos:
            cb.addItems(self.champions)
            self._make_editable_with_completer(cb)

        # 味方ピック：5体（上に固定ロールラベルを表示）
        self.role_labels = ["トップ", "ジャングル", "ミッド", "ADC", "サポート"]
        self.our_picks_combos = []
        for _ in range(5):
            champ_cb = QComboBox()
            champ_cb.addItems(self.champions)
            self._make_editable_with_completer(champ_cb)
            self.our_picks_combos.append(champ_cb)

        # 敵ピック：5
        self.enemy_picks_combos = [QComboBox() for _ in range(5)]
        for cb in self.enemy_picks_combos:
            cb.addItems(self.champions)
            self._make_editable_with_completer(cb)

        # ロール（自分のロール）
        self.role_combo = QComboBox()
        self.role_combo.addItems(["指定なし", "トップ", "ジャングル", "ミッド", "ADC", "サポート"])

        self.auto_get_button = QPushButton("チャンピオン自動取得")
        self.auto_get_button.setObjectName("primaryButton")
        self.generate_button = QPushButton("最適ピックを提案")
        self.generate_button.setObjectName("primaryButton")
        self.clear_button = QPushButton("クリア")
        self.clear_button.setObjectName("clearButton")

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("ここにAIの提案が表示されます。")

        # レイアウト構築
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # バン（2行×5列）
        layout.addWidget(QLabel("バン（10体）:"))
        ban_grid = QGridLayout()
        ban_grid.setHorizontalSpacing(8)
        ban_grid.setVerticalSpacing(8)
        for i, cb in enumerate(self.ban_combos):
            row = i // 5
            col = i % 5
            ban_grid.addWidget(cb, row, col)
        layout.addLayout(ban_grid)

        # 味方ピック（固定ロールラベルを上に表示）
        layout.addWidget(QLabel("味方の既ピック（5体） — 上のラベルがロールです:"))
        our_grid = QGridLayout()
        our_grid.setHorizontalSpacing(8)
        # ラベル行
        for i, role in enumerate(self.role_labels):
            lbl = QLabel(role)
            lbl.setAlignment(Qt.AlignCenter)
            our_grid.addWidget(lbl, 0, i)
        # チャンピオン選択行
        for i, champ_cb in enumerate(self.our_picks_combos):
            our_grid.addWidget(champ_cb, 1, i)
        layout.addLayout(our_grid)

        # 敵ピック
        layout.addWidget(QLabel("敵の既ピック（5体）:"))
        enemy_h = QHBoxLayout()
        enemy_h.setSpacing(8)
        for cb in self.enemy_picks_combos:
            enemy_h.addWidget(cb)
        layout.addLayout(enemy_h)

        # ロール＋ボタン群
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("自分のロール:"))
        h3.addWidget(self.role_combo)
        h3.addStretch()
        h3.addWidget(self.auto_get_button)
        h3.addWidget(self.generate_button)
        h3.addWidget(self.clear_button)
        layout.addLayout(h3)

        layout.addWidget(QLabel("AI提案:"))
        layout.addWidget(self.result_box)
        self.setLayout(layout)

        # 影を付けて浮いた印象に（控えめ）
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 25))
        self.result_box.setGraphicsEffect(shadow)

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
            QComboBox, QLineEdit {
                border: 1px solid #efecec;
                border-radius: 10px;
                padding: 6px 10px;
                background: #ffffff;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: none;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #eee;
                selection-background-color: #f0f6ff;
            }
            QTextEdit {
                border: 1px solid #f0f0f0;
                border-radius: 12px;
                background: #fafafa;
                padding: 8px;
                color: #222;
            }
            QPushButton#primaryButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6cc3ff, stop:1 #3aa0ff);
                color: white;
                border: none;
                border-radius: 12px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton#primaryButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7fd7ff, stop:1 #4ab6ff);
            }
            QPushButton#clearButton {
                background: #ffffff;
                color: #444;
                border: 1px solid #e8e8e8;
                border-radius: 10px;
                padding: 6px 12px;
            }
        """)

        # シグナル
        self.auto_get_button.clicked.connect(self.on_auto_get)
        self.generate_button.clicked.connect(self.on_generate)
        self.clear_button.clicked.connect(self.on_clear)

    def _load_champions(self):
        try:
            with open(CHAMPION_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "指定なし" not in data:
                data.insert(0, "指定なし")
            return data
        except Exception:
            return ["指定なし", "Aatrox", "Ahri", "Akali"]

    def _to_hiragana(self, s: str) -> str:
        if not s:
            return ""
        t = unicodedata.normalize("NFKC", s.strip())
        out_chars = []
        for ch in t:
            code = ord(ch)
            if 0x30A1 <= code <= 0x30F6:
                out_chars.append(chr(code - 0x60))
            else:
                out_chars.append(ch)
        norm = "".join(out_chars).lower()
        for ch in ["・", " ", "(", ")", "（", "）", "：", ":", "　"]:
            norm = norm.replace(ch, "")
        return norm

    def _make_editable_with_completer(self, combo: QComboBox):
        combo.setEditable(True)
        model = QStringListModel(self.champions, combo)
        completer = QCompleter(model, combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        combo.setCompleter(completer)
        combo._smodel = model
        combo._completer = completer
        combo.lineEdit().textEdited.connect(lambda txt, c=combo: self._update_completer(c, txt))

    def _update_completer(self, combo: QComboBox, text: str):
        # 入力を正規化して、チャンピオンリストを先頭一致でフィルタする（ひらがな/カタカナ無視）
        nt = self._to_hiragana(text)
        if nt == "":
            candidates = self.champions[:]
        else:
            candidates = []
            for name in self.champions:
                if name == "指定なし":
                    continue
                if self._to_hiragana(name).startswith(nt):
                    candidates.append(name)
            if not candidates:
                for name in self.champions:
                    if name == "指定なし":
                        continue
                    if nt in self._to_hiragana(name):
                        candidates.append(name)
            candidates = candidates[:50]
        if not candidates:
            candidates = ["指定なし"]

        # モデルを更新して補完候補を差し替える
        combo._smodel.setStringList(candidates)
        combo._completer.setModel(combo._smodel)

        # 補完ポップアップを確実に表示する処理
        # - プレフィックスは空にして候補全体を表示（候補は既にフィルタ済み）
        # - lineEdit のカーソル位置の矩形を指定して表示位置を安定化
        try:
            combo._completer.setCompletionPrefix("")
        except Exception:
            pass

        # 完全に消える問題に対処するため、明示的にカーソル矩形を渡して表示させる
        try:
            rect = combo.lineEdit().cursorRect()
            combo._completer.complete(rect)
        except Exception:
            # フォールバック：位置指定なしで表示
            combo._completer.complete()
    
    def on_auto_get(self):
        """スクリーンショットの自動取得を開始/停止するトグル。
        - オーバーレイは開始時に表示、停止時に非表示にする。
        """
        interval_ms = getattr(self, "_auto_interval", 5000)
        if not hasattr(self, "_auto_timer"):
            self._auto_timer = QTimer(self)
            self._auto_timer.timeout.connect(self._capture_screen_once)
            self._auto_interval = interval_ms

        if not self._auto_timer.isActive():
            # 開始：タイマーとオーバーレイを表示
            self._auto_timer.start(self._auto_interval)
            self.auto_get_button.setText("自動取得停止")
            self.auto_get_button.setObjectName("primaryButton")
            try:
                # オーバーレイを前面に表示
                self._overlay.show()
                self._overlay.raise_()
            except Exception:
                pass
            self.result_box.append("自動取得を開始しました。")
        else:
            # 停止：タイマーとオーバーレイを非表示
            self._auto_timer.stop()
            self.auto_get_button.setText("チャンピオン自動取得")
            try:
                self._overlay.hide()
            except Exception:
                pass
            self.result_box.append("自動取得を停止しました。")

    def _capture_screen_once(self):
        """単発でスクリーンショットを取得して保存し、可能であれば OCR を試行する内部処理。
        変更点: デスクトップ全体ではなく、オーバーレイで示した中央の矩形領域のみを保存します。
        """
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                self.result_box.append("スクリーン取得に失敗しました: primaryScreen が見つかりません。")
                return

            # オーバーレイで描画している矩形領域 (スクリーン座標) を計算
            geom = screen.geometry()
            sw = geom.width()
            sh = geom.height()
            # オーバーレイ側と同じ計算を再現（余白 40px を考慮）
            rw = min(self._overlay._rect_w, sw - 40)
            rh = min(self._overlay._rect_h, sh - 40)
            rx = geom.x() + (sw - rw) // 2
            ry = geom.y() + (sh - rh) // 2

            # 指定矩形のみをキャプチャ
            pix = screen.grabWindow(0, rx, ry, rw, rh)

            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(tempfile.gettempdir(), f"diaryapp_screenshot_{ts}.png")
            saved = pix.save(path, "PNG")
            if not saved:
                self.result_box.append("スクリーンショットの保存に失敗しました。")
                return

            ocr_text = None
            # OCR が利用可能なら試行（pytesseract + PIL）
            try:
                import pytesseract
                from PIL import Image
                buf = QBuffer()
                buf.open(QBuffer.ReadWrite)
                pix.save(buf, "PNG")
                data = bytes(buf.data())
                buf.close()
                img = Image.open(BytesIO(data))
                try:
                    # まず日本語指定で試す
                    ocr_text = pytesseract.image_to_string(img, lang="jpn")
                except Exception:
                    ocr_text = pytesseract.image_to_string(img)
            except Exception:
                ocr_text = None

            # OCR結果からチャンピオン名候補を簡易抽出（正規化して部分一致）
            found = []
            if ocr_text:
                norm = self._to_hiragana(ocr_text)
                for name in self.champions:
                    if name == "指定なし":
                        continue
                    if self._to_hiragana(name) in norm:
                        found.append(name)

            # 表示（どの領域を保存したか明示）
            msg = f"スクリーンショットを保存しました: {path} (領域: x={rx}, y={ry}, w={rw}, h={rh})"
            if found:
                msg += "\n検出されたチャンピオン候補: " + ", ".join(found)
            else:
                if ocr_text is not None:
                    msg += "\nOCR 実行済み。候補は検出されませんでした。"
                else:
                    msg += "\nOCR は利用できません（pytesseract が未インストール）。"
            self.result_box.append(msg)
        except Exception as e:
            self.result_box.append(f"スクリーンショット取得中にエラーが発生しました: {e}")

    def on_clear(self):
        for cb in self.ban_combos + self.enemy_picks_combos + self.our_picks_combos:
            cb.setCurrentIndex(0)
            if cb.lineEdit():
                cb.lineEdit().clear()
        self.role_combo.setCurrentIndex(0)
        self.result_box.clear()

    def on_generate(self):
        if self.client is None:
            QMessageBox.warning(self, "API未設定", "OPENAI_API_KEY が設定されていません。環境変数を設定してください。")
            return

        bans = self._collect_from_combos(self.ban_combos)
        our_picks = self._collect_our_picks()
        enemy_picks = self._collect_from_combos(self.enemy_picks_combos)
        role = self.role_combo.currentText()
        if role == "指定なし":
            role = "不特定"

        prompt = (
            "あなたは League of Legends のドラフトフェーズ専門アナリストです。"
            "OP.GGなどの統計系サイト、公式のLOL情報、LoL wiki、SNSでのトッププレイヤーの傾向を考慮して最適なピックを提案してください。"
            "パッチ15.23のメタ、ロールごとの強弱、ピック構成、チャンピオン相性、シナジー、カウンター、パワースパイク、エンゲージ/ディスエンゲージ構成、レンジ差、役割の補完などを深く理解しています。"
            "以下の情報をもとに、ユーザーが選ぶべき最適なチャンピオン候補を「最大3体」提案してください。"
            "\n\nバン一覧: " + (", ".join(bans) if bans else "なし")
            + "\n味方の既ピック: " + (", ".join(our_picks) if our_picks else "なし")
            + "\n敵の既ピック: " + (", ".join(enemy_picks) if enemy_picks else "なし")
            + "\n自分のロール: " + role

            +"【出力内容】"
            "1. 最適ピック候補（最大3体）: 各チャンピオンについて、ユーザーのロールで適切に運用できるチャンピオンを選んでください。"

            "2. 推奨理由（以下の観点で詳細に説明）:"
            " - 対面ロールが確定している場合のレーン相性（有利ポイント / 不利ポイント）"
            " - 味方構成とのシナジー（エンゲージ、ディスエンゲージ、CC連携、スケーリングの噛み合い）"
            " - 敵構成へのカウンター要素（レンジ差、耐久 vs バースト、分断能力、エンゲージ耐性など）"
            " - チーム構成バランス（AD/AP、前衛/後衛、CC量、オブジェクト戦力）"

            "【ルール】"
            " - BANされたチャンピオンは必ず候補から除外してください。"
            " - ユーザーのロールに適したチャンピオンのみ提案してください。"
            " - 敵のロールが曖昧な場合は「仮定」を明示し、その上で分析を行ってください。"
            " - 可能な限り具体的な理由を提示し、抽象的な回答は避けてください。"
            " - 現パッチの一般的なメタ傾向や構成理論に基づいた説明をしてください。"
            " - 600トークン以内に収めてください。"
        )

        self.result_box.setPlainText("AIに問い合わせ中...")
        try:
            response = self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "あなたはLoLについて非常に詳しいコーチです。助言は日本語で簡潔に行ってください。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=600
            )
            ai_text = None
            try:
                ai_text = response.choices[0].message["content"]
            except Exception:
                try:
                    ai_text = response.choices[0].message.content
                except Exception:
                    ai_text = str(response)
            self.result_box.setPlainText(ai_text.strip())
        except Exception as e:
            self.result_box.setPlainText("")
            QMessageBox.critical(self, "APIエラー", f"AIへの問い合わせに失敗しました:\n{e}")

    def _collect_from_combos(self, combos):
        vals = []
        for cb in combos:
            t = cb.currentText().strip()
            if t and t != "指定なし":
                vals.append(t)
        return vals

    def _collect_our_picks(self):
        vals = []
        for i, champ_cb in enumerate(self.our_picks_combos):
            champ = champ_cb.currentText().strip()
            if not champ or champ == "指定なし":
                continue
            role = self.role_labels[i] if i < len(self.role_labels) else "指定なし"
            vals.append(f"{champ}（{role}）")
        return vals