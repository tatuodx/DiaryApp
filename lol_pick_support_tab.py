import os
import json
from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QComboBox, QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox,
    QCompleter
)
from PySide6.QtCore import Qt, QStringListModel
from openai import OpenAI

CHAMPION_JSON = os.path.join(os.path.dirname(__file__), "champion_names_ja.json")

class LolPickSupportTab(QWidget):
    def __init__(self, client: OpenAI | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.champions = self._load_champions()

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

        self.generate_button = QPushButton("最適ピックを提案")
        self.clear_button = QPushButton("クリア")

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("ここにAIの提案が表示されます。")

        # レイアウト構築
        layout = QVBoxLayout()

        # バン（2行×5列）
        layout.addWidget(QLabel("バン（10体、上から順に）:"))
        ban_grid = QGridLayout()
        for i, cb in enumerate(self.ban_combos):
            row = i // 5
            col = i % 5
            ban_grid.addWidget(cb, row, col)
        layout.addLayout(ban_grid)

        # 味方ピック（固定ロールラベルを上に表示）
        layout.addWidget(QLabel("味方の既ピック（5体） — 上のラベルがロールです:"))
        our_grid = QGridLayout()
        # ラベル行
        for i, role in enumerate(self.role_labels):
            our_grid.addWidget(QLabel(role), 0, i)
        # チャンピオン選択行
        for i, champ_cb in enumerate(self.our_picks_combos):
            our_grid.addWidget(champ_cb, 1, i)
        layout.addLayout(our_grid)

        # 敵ピック
        layout.addWidget(QLabel("敵の既ピック（5体）:"))
        enemy_h = QHBoxLayout()
        for cb in self.enemy_picks_combos:
            enemy_h.addWidget(cb)
        layout.addLayout(enemy_h)

        # ロール＋ボタン群
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("自分のロール:"))
        h3.addWidget(self.role_combo)
        h3.addStretch()
        h3.addWidget(self.generate_button)
        h3.addWidget(self.clear_button)
        layout.addLayout(h3)

        layout.addWidget(QLabel("AI提案:"))
        layout.addWidget(self.result_box)
        self.setLayout(layout)

        # シグナル
        self.generate_button.clicked.connect(self.on_generate)
        self.clear_button.clicked.connect(self.on_clear)

    def _load_champions(self):
        try:
            with open(CHAMPION_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 確実に先頭に指定なしがあるようにする
            if "指定なし" not in data:
                data.insert(0, "指定なし")
            return data
        except Exception:
            # フォールバック：簡易リスト
            return ["指定なし", "Aatrox", "Ahri", "Akali"]

    def _to_hiragana(self, s: str) -> str:
        # カタカナをひらがなに正規化、英字は小文字化、全角スペース除去など簡易正規化
        if not s:
            return ""
        out = []
        for ch in s.strip().replace("　", " "):
            code = ord(ch)
            # カタカナ範囲判定（U+30A1〜U+30F6）
            if 0x30A1 <= code <= 0x30F6:
                out.append(chr(code - 0x60))  # カタカナ→ひらがな
            else:
                out.append(ch)
        norm = "".join(out).lower()
        # 小書き文字等はそのままでも可。不要記号を削除
        for ch in ["・", " ", "(", ")", "（", "）", "：", ":", "　"]:
            norm = norm.replace(ch, "")
        return norm

    def _make_editable_with_completer(self, combo: QComboBox):
        # 編集可能にして、先頭一致（ひらがな/カタカナを無視）で補完を出す
        combo.setEditable(True)
        model = QStringListModel(self.champions, combo)
        completer = QCompleter(model, combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        combo.setCompleter(completer)
        combo._smodel = model
        combo._completer = completer
        # テキスト入力時に候補を更新する
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
            # 先頭一致で候補が無ければ部分一致でフォールバック（利便性向上）
            if not candidates:
                for name in self.champions:
                    if name == "指定なし":
                        continue
                    if nt in self._to_hiragana(name):
                        candidates.append(name)
            # 最後に限定数（例えば50）で切る
            candidates = candidates[:50]
        # 空の場合は指定なしを含める
        if not candidates:
            candidates = ["指定なし"]
        combo._smodel.setStringList(candidates)
        # 表示更新
        combo.completer().complete()

    def on_clear(self):
        for cb in self.ban_combos + self.enemy_picks_combos + self.our_picks_combos:
            cb.setCurrentIndex(0)
            # もし編集済みのテキストがある場合はクリア
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

        # プロンプト作成（日本語） — 指定の文言を含める
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

        # （UI上にプロンプトを表示しない） -> そのままAIへ送信
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
            # API応答からテキストを取得（クライアント実装に合わせる）
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
        # 味方ピックを「チャンピオン（ロール）」形式で返す。ロールは左から固定の role_labels を使用。
        vals = []
        for i, champ_cb in enumerate(self.our_picks_combos):
            champ = champ_cb.currentText().strip()
            if not champ or champ == "指定なし":
                continue
            role = self.role_labels[i] if i < len(self.role_labels) else "指定なし"
            vals.append(f"{champ}（{role}）")
        return vals