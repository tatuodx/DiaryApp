import requests
import os
import json

# 1. 最新バージョンを取る
try:
    v = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()[0]
    print("version:", v)
except (requests.RequestException, IndexError) as e:
    print(f"バージョン取得エラー: {e}")
    exit(1)

# 2. champion.json を取る
cj = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/champion.json").json()
champions = cj["data"]

os.makedirs("champion_icons", exist_ok=True)
os.makedirs("champion_splashes", exist_ok=True)

for key, info in champions.items():
    # アイコン（png）
    icon_url = f"https://ddragon.leagueoflegends.com/cdn/{v}/img/champion/{key}.png"
    r = requests.get(icon_url)
    if r.ok:
        # ファイルを自動的にクローズするため with 文を使用
        with open(f"champion_icons/{key}.png", "wb") as f:
            f.write(r.content)

    # スプラッシュ（スキン0..N）
    for s in info.get("skins", []):
        skin_num = s["num"]  # 0,1,2...
        splash_url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_{skin_num}.jpg"
        r2 = requests.get(splash_url)
        if r2.ok:
            # with文を使ってファイルを自動的にクローズする
            with open(f"champion_splashes/{key}_{skin_num}.jpg", "wb") as f:
                f.write(r2.content)
