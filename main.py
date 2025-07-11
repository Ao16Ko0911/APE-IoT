import os
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import requests
import time
import csv
from datetime import datetime
import pytz
import gspread
from gspread_dataframe import get_as_dataframe
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import json # 👈 1. JSONライブラリをインポート

# (他の関数 get_credentials, get_schedule_data, etc. は変更なし)
# ...

# === GitHubへアップロード（汎用版） ===
# 2. 関数を汎用的にして、ファイルパスと内容を引数で渡せるように変更
def upload_file_to_github(file_path, content_str, commit_message):
    import base64
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 現在のSHAを取得
    sha = None
    try:
        get_res = requests.get(api_url, headers=headers)
        if get_res.status_code == 200:
            sha = get_res.json()["sha"]
    except Exception as e:
        print(f"⚠️ SHA取得時の例外: {e}")
        # SHAがなくても続行

    content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

    update_data = {
        "message": commit_message,
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha:
        update_data["sha"] = sha

    put_res = requests.put(api_url, headers=headers, json=update_data)

    if put_res.status_code in [200, 201]:
        print(f"✅ GitHubへ {file_path} をアップロード成功！")
    else:
        print(f"❌ GitHubアップロード失敗: {put_res.status_code}")
        print(put_res.text)


# === メイン処理ループ ===
def main_loop(interval_sec=600):
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Tokyo'))
            today = now.strftime('%Y-%m-%d')
            hour = now.hour
            period = get_current_period(hour)

            schedule = get_schedule_data()
            booking = next((e['状態'] for e in schedule if e['日付'] == today and e['時間'] == period), "データなし")

            co2 = get_avg_co2()
            status = determine_usage(booking, co2)
            
            # 3. HTMLではなく辞書データを作成
            output_data = {
                "status_text": status,
                "booking_status": booking or "なし",
                "co2_value": f"{co2:.1f}" if co2 is not None else "N/A",
                "current_period": period or "授業時間外",
                "last_updated": now.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # 4. 辞書をJSON文字列に変換
            json_str = json.dumps(output_data, indent=2, ensure_ascii=False)

            # 5. JSONファイルをGitHubにアップロード
            upload_file_to_github(
                file_path="status.json", # アップロードするファイル名
                content_str=json_str,
                commit_message="Update status.json"
            )

            print(f"🕒 {now.strftime('%H:%M:%S')} に実行完了。次回は {interval_sec//60} 分後。")

        except Exception as e:
            print(f"⚠️ エラー発生: {e}")
        time.sleep(interval_sec)

# スクリプト開始
if __name__ == "__main__":
    # 既存の get_schedule_data などの関数はこのまま使います
    # ...
    main_loop(600)