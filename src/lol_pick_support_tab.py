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
import torch
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import cv2
import numpy as np

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
        """中央に枠線（長方形）を描画し、その枠内の左上と右上にそれぞれ横長の赤い長方形枠を描画する。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # メイン枠線の色・太さ（柔らかい青）
        pen = QPen(QColor(60, 120, 220, 200))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # 中央位置を計算してメイン長方形を描く
        sw = self.width()
        sh = self.height()
        rw = min(self._rect_w, sw - 40)
        rh = min(self._rect_h, sh - 40)
        rx = (sw - rw) // 2
        ry = (sh - rh) // 2
        # 角を丸く描画（丸みを持たせる）
        painter.drawRoundedRect(rx, ry, rw, rh, 12, 12)

        # --- 枠内の左上と右上に横長の赤い長方形枠を描画 ---
        # 赤色のペン（枠線のみ）
        red_pen = QPen(QColor(220, 60, 60, 200))  # 赤色
        red_pen.setWidth(2)
        painter.setPen(red_pen)
        painter.setBrush(Qt.NoBrush)

        # 横長の長方形のサイズ（枠内に収まるように調整）
        rect_width = int(rw * 0.15)  # メイン枠の15%幅
        rect_height = int(rh * 0.08)  # メイン枠の8%高さ
        margin = 10  # メイン枠からのマージン

        # 左上の横長長方形
        left_top_x = rx + margin
        left_top_y = ry + margin
        painter.drawRoundedRect(left_top_x, left_top_y, rect_width, rect_height, 6, 6)

        # 右上の横長の長方形
        right_top_x = rx + rw - rect_width - margin
        right_top_y = ry + margin
        painter.drawRoundedRect(right_top_x, right_top_y, rect_width, rect_height, 6, 6)

class SimpleCNN(nn.Module):
    """
    チャンピオンアイコン分類用の CNN モデル（32x32 入力）。
    utils/champion_model.pth で保存された学習済みモデルと同じ構造。
    """
    def __init__(self, num_classes):
        super(SimpleCNN, self).__init__()
        # 畳み込み層1: 3ch → 16ch
        self.conv1 = nn.Conv2d(3, 16, kernel_size=3, padding=1)
        self.relu1 = nn.ReLU()
        self.pool1 = nn.MaxPool2d(2, 2)  # 32x32 → 16x16
        
        # 畳み込み層2: 16ch → 32ch
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.relu2 = nn.ReLU()
        self.pool2 = nn.MaxPool2d(2, 2)  # 16x16 → 8x8
        
        # 全結合層
        self.fc1 = nn.Linear(32 * 8 * 8, 128)
        self.relu3 = nn.ReLU()
        self.fc2 = nn.Linear(128, num_classes)
    
    def forward(self, x):
        x = self.pool1(self.relu1(self.conv1(x)))
        x = self.pool2(self.relu2(self.conv2(x)))
        x = x.view(x.size(0), -1)  # フラット化
        x = self.relu3(self.fc1(x))
        x = self.fc2(x)
        return x

class LolPickSupportTab(QWidget):
    def __init__(self, client: OpenAI | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.champions = self._load_champions()
        # スクリーンオーバーレイ（中央に 1280x720 枠を表示）
        self._overlay = ScreenOverlay(1280, 720)
        self._overlay.hide()
        
        # 学習済みモデルとラベルマッピングを読み込み
        self._load_model()

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

    def _load_model(self):
        """
        学習済みモデル（champion_model.pth）を読み込み、推論用に準備します。
        train_list.txt から画像パスとラベルの対応を読み込んでラベル→チャンピオン名のマッピングを作成します。
        """
        utils_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "utils")
        model_path = os.path.join(utils_dir, "champion_model.pth")
        train_list_path = os.path.join(utils_dir, "train_list.txt")
        
        # ラベル→チャンピオン名のマッピングを作成
        self.label_to_champion = {}
        if os.path.exists(train_list_path):
            with open(train_list_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) != 2:
                        continue
                    img_path = parts[0].strip()
                    label = int(parts[1].strip())
                    # champion_icons/ChampionName.png から ChampionName を抽出
                    champion_name = os.path.splitext(os.path.basename(img_path))[0]
                    self.label_to_champion[label] = champion_name
        
        num_classes = len(self.label_to_champion)
        
        # モデルの読み込み
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        if os.path.exists(model_path) and num_classes > 0:
            try:
                self.model = SimpleCNN(num_classes=num_classes).to(self.device)
                self.model.load_state_dict(torch.load(model_path, map_location=self.device, weights_only=True))
                self.model.eval()
                print(f"学習済みモデルを読み込みました: {model_path} (クラス数: {num_classes})")
            except Exception as e:
                print(f"モデル読み込みエラー: {e}")
                self.model = None
        else:
            print(f"警告: モデルファイルまたはtrain_list.txtが見つかりません。")
        
        # 画像前処理（学習時と同じ変換）
        self.transform = transforms.Compose([
            transforms.Resize((32, 32)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
        ])

    def _classify_champion_icon(self, icon_image: Image.Image) -> str:
        """
        単一のチャンピオンアイコン画像を分類し、チャンピオン名を返します。
        
        Args:
            icon_image: PIL.Image オブジェクト（チャンピオンアイコン1体分）
        
        Returns:
            str: 予測されたチャンピオン名（不明な場合は "不明"）
        """
        if self.model is None:
            return "不明"
        
        try:
            # 前処理
            img_tensor = self.transform(icon_image).unsqueeze(0).to(self.device)
            
            # 推論
            with torch.no_grad():
                outputs = self.model(img_tensor)
                _, predicted = torch.max(outputs, 1)
                label = predicted.item()
            
            # ラベルからチャンピオン名に変換
            champion_name = self.label_to_champion.get(label, "不明")
            return champion_name
        except Exception as e:
            print(f"分類エラー: {e}")
            return "不明"

    def _detect_champion_icons(self, box_img: Image.Image) -> list[Image.Image]:
        """
        赤枠領域の画像から、チャンピオンアイコンが映っている矩形領域を検出して切り出します。
        
        処理フロー:
        1. PIL Image を OpenCV 形式（numpy配列）に変換
        2. グレースケール化・二値化処理
        3. 輪郭検出で矩形領域を抽出
        4. 面積・アスペクト比でフィルタリング（アイコンサイズに該当するもののみ）
        5. 左から順に最大5体まで切り出し
        
        Args:
            box_img: 赤枠領域の PIL.Image（横長の矩形）
        
        Returns:
            list[Image.Image]: 検出されたチャンピオンアイコン画像のリスト（最大5体）
        """
        try:
            # PIL Image → OpenCV 形式（numpy配列）に変換
            img_cv = cv2.cvtColor(np.array(box_img), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            
            # 適応的二値化（照明の影響を軽減）
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY_INV, 11, 2
            )
            
            # モルフォロジー処理でノイズ除去
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            
            # 輪郭検出
            contours, _ = cv2.findContours(
                morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            
            # 矩形候補をフィルタリング
            box_height = box_img.height
            box_width = box_img.width
            min_area = (box_height * 0.6) ** 2  # 最小面積（高さの60%の正方形）
            max_area = (box_height * 1.2) ** 2  # 最大面積（高さの120%の正方形）
            
            detected_rects = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h
                aspect_ratio = w / h if h > 0 else 0
                
                # フィルタリング条件:
                # - 面積が適切な範囲
                # - アスペクト比が正方形に近い（0.7 ~ 1.3）
                # - 高さが赤枠の50%以上
                if (min_area <= area <= max_area and 
                    0.7 <= aspect_ratio <= 1.3 and
                    h >= box_height * 0.5):
                    detected_rects.append((x, y, w, h))
            
            # 左から順にソート
            detected_rects.sort(key=lambda r: r[0])
            
            # 最大5体まで切り出し
            icon_images = []
            for i, (x, y, w, h) in enumerate(detected_rects[:5]):
                # マージンを少し持たせて切り出し（境界の情報を確保）
                margin = 2
                x1 = max(0, x - margin)
                y1 = max(0, y - margin)
                x2 = min(box_width, x + w + margin)
                y2 = min(box_height, y + h + margin)
                
                icon_crop = box_img.crop((x1, y1, x2, y2))
                icon_images.append(icon_crop)
            
            # 検出数が5未満の場合は警告ログ
            if len(icon_images) < 5:
                print(f"警告: 検出されたアイコン数が5未満です（{len(icon_images)}体）")
            
            return icon_images
            
        except Exception as e:
            print(f"アイコン検出エラー: {e}")
            import traceback
            traceback.print_exc()
            # エラー時は均等5分割にフォールバック
            return self._fallback_split_icons(box_img)
    
    def _fallback_split_icons(self, box_img: Image.Image) -> list[Image.Image]:
        """
        アイコン検出に失敗した場合のフォールバック処理。
        赤枠領域を単純に5等分して切り出します。
        
        Args:
            box_img: 赤枠領域の PIL.Image
        
        Returns:
            list[Image.Image]: 5等分されたアイコン画像のリスト
        """
        width = box_img.width
        height = box_img.height
        icon_width = width // 5
        
        icons = []
        for i in range(5):
            x1 = i * icon_width
            x2 = x1 + icon_width
            icon_crop = box_img.crop((x1, 0, x2, height))
            icons.append(icon_crop)
        
        return icons

    def _capture_screen_once(self):
        """
        スクリーンショットを取得し、赤枠内の5体のチャンピオンアイコンを分類します。
        
        処理フロー:
        1. 画面中央の指定領域をキャプチャ
        2. 左上と右上の赤枠領域をそれぞれ5分割してアイコンを切り出し
        3. 各アイコンをモデルで分類
        4. 切り出したアイコンを trim フォルダに保存（ファイル名: チャンピオン名_時刻.png）
        5. 結果を表示
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
            rw = min(self._overlay._rect_w, sw - 40)
            rh = min(self._overlay._rect_h, sh - 40)
            rx = geom.x() + (sw - rw) // 2
            ry = geom.y() + (sh - rh) // 2

            # 指定矩形のみをキャプチャ
            pix = screen.grabWindow(0, rx, ry, rw, rh)

            # PIL.Image に変換
            buf = QBuffer()
            buf.open(QBuffer.ReadWrite)
            pix.save(buf, "PNG")
            data = bytes(buf.data())
            buf.close()
            full_img = Image.open(BytesIO(data))

            # trim フォルダの作成（プロジェクトルート直下）
            project_root = os.path.dirname(os.path.dirname(__file__))
            trim_dir = os.path.join(project_root, "trim")
            os.makedirs(trim_dir, exist_ok=True)

            # 赤枠の座標（オーバーレイと同じ計算）
            rect_width = int(rw * 0.15)
            rect_height = int(rh * 0.08)
            margin = 10

            # 左上の赤枠（相対座標）
            left_box = (margin, margin, margin + rect_width, margin + rect_height)
            # 右上の赤枠（相対座標）
            right_box = (rw - rect_width - margin, margin, rw - margin, margin + rect_height)

            # 各赤枠を5分割してアイコンを切り出し・分類・保存
            results = []
            ts = time.strftime("%Y%m%d_%H%M%S")  # 共通のタイムスタンプ
            
            for box_name, box in [("左チーム", left_box), ("右チーム", right_box)]:
                x1, y1, x2, y2 = box
                box_width = x2 - x1
                icon_width = box_width // 5  # 5体均等分割
                
                team_champions = []
                for i in range(5):
                    icon_x1 = x1 + i * icon_width
                    icon_x2 = icon_x1 + icon_width
                    icon_box = (icon_x1, y1, icon_x2, y2)
                    
                    # アイコン領域を切り出し
                    icon_img = full_img.crop(icon_box)
                    
                    # 分類
                    champion_name = self._classify_champion_icon(icon_img)
                    team_champions.append(champion_name)
                    
                    # trim フォルダに保存（ファイル名: チャンピオン名_時刻_チーム_番号.png）
                    team_prefix = "left" if box_name == "左チーム" else "right"
                    filename = f"{champion_name}_{ts}_{team_prefix}_{i+1}.png"
                    save_path = os.path.join(trim_dir, filename)
                    try:
                        icon_img.save(save_path, "PNG")
                    except Exception as e:
                        print(f"アイコン保存エラー ({filename}): {e}")
                
                results.append(f"{box_name}: {', '.join(team_champions)}")
            
            # 結果を表示
            msg = "【チャンピオン分類結果】\n" + "\n".join(results)
            msg += f"\n\n切り出したアイコンを保存しました: {trim_dir}"
            self.result_box.append(msg)
            
            # デバッグ用: スクリーンショット全体を保存
            full_path = os.path.join(tempfile.gettempdir(), f"diaryapp_screenshot_{ts}.png")
            full_img.save(full_path, "PNG")
            self.result_box.append(f"スクリーンショット全体を保存: {full_path}")
            
        except Exception as e:
            self.result_box.append(f"スクリーンショット取得中にエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()

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