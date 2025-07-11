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
import json

# === .env読み込み ===
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
BRANCH = os.getenv("BRANCH", "main")
FILE_PATH = os.getenv("FILE_PATH", "index.html")
COMMIT_MESSAGE = "Update index.html from local script"

# === Google Sheets API 認証 ===
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_credentials():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('./client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

creds = get_credentials()
client = gspread.authorize(creds)


# === スケジュール取得 ===
def get_schedule_data():
    """
    Googleスプレッドシートから教室の予約スケジュールを抽出し、
    日付、時限、予約状況をまとめたリストを返します。
    """
    spreadsheet = client.open("自由使用向け予定表")
    worksheet = spreadsheet.sheet1

    df = get_as_dataframe(worksheet, header=None)
    schedule_data = []
    rows = df.values.tolist()

    i = 0
    while i < len(rows):
        row = rows[i]
        if isinstance(row[0], str) and '限' in ''.join(map(str, row)):
            date_info = row[0]
            if '月' in date_info and '日' in date_info:
                try:
                    date_part = date_info.split(' ')[0]

                    temp_date = datetime.strptime(date_part, '%m月%d日')
                    date_str = f'2025-{temp_date.strftime("%m-%d")}'

                    if i + 1 < len(rows) and rows[i + 1][0] == 'R3-301':
                        status_row = rows[i + 1][1:]
                        for j, status in enumerate(status_row):
                            schedule_data.append({
                                '日付': date_str,
                                '時間': f'{j + 1}限',
                                '状態': status
                            })
                except (ValueError, IndexError):
                    pass
            i += 5
        else:
            i += 1
    return schedule_data

# === 時限の取得 ===
def get_current_period(hour):
    if 8 <= hour < 10: return "1限"
    elif 10 <= hour < 12: return "2限"
    elif 13 <= hour < 15: return "3限"
    elif 15 <= hour < 17: return "4限"
    return None

# === CO2センサー値取得 ===
def get_avg_co2():
    now_unix = int(time.time())
    start_time = now_unix - 3600
    url = f'https://airoco.necolico.jp/data-api/day-csv?id=CgETViZ2&subscription-key=6b8aa7133ece423c836c38af01c59880&startDate={start_time}'
    res = requests.get(url)
    co2_values = []
    reader = csv.reader(res.text.strip().splitlines())
    for row in reader:
        if len(row) > 6 and row[1] == 'Ｒ３ー４０１':
            try:
                co2 = float(row[3])
                co2_values.append(co2)
            except ValueError:
                continue
    return np.mean(co2_values) if co2_values else None

# === 状態判定 ===
def determine_usage(booking, co2):
    if booking == "○" and co2 and co2 > 1000:
        return "✅ 正常利用中"
    elif booking == "×" and co2 and co2 > 1000:
        return "⚠️ 不正利用の可能性あり"
    elif booking == "○" and (not co2 or co2 < 600):
        return "⚠️ 無断キャンセルの可能性"
    else:
        return "🟢 空室または利用無し"

# === GitHubへアップロード ===
def upload_file_to_github(file_path, content_str, commit_message):
    """
    指定された内容のファイルをGitHubにアップロードする
    """
    import base64
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 既存ファイルのSHAを取得
    sha = None
    try:
        get_res = requests.get(api_url, headers=headers)
        if get_res.status_code == 200:
            sha = get_res.json()["sha"]
    except Exception as e:
        print(f"⚠️ SHA取得時の例外: {e}")
        # SHA取得に失敗しても続行

    # コンテンツをBase64にエンコード
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
        print(f"✅ GitHubへ {file_path} のアップロード成功！")
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

            # データの取得と判定
            schedule = get_schedule_data()
            booking = next((e['状態'] for e in schedule if e['日付'] == today and e['時間'] == period), "データなし")
            co2 = get_avg_co2()
            status = determine_usage(booking, co2)

            # データを辞書形式でまとめる
            output_data = {
                "status_text": status,
                "booking_status": booking or "なし",
                "co2_value": f"{co2:.1f}" if co2 is not None else "N/A",
                "current_period": period or "授業時間外",
                "last_updated": now.strftime('%Y-%m-%d %H:%M:%S')
            }

            # 辞書をJSON形式の文字列に変換
            json_str = json.dumps(output_data, indent=2, ensure_ascii=False)

            # JSONファイルをGitHubにアップロード
            upload_file_to_github(
                file_path="status.json", # アップロードするファイル名
                content_str=json_str,
                commit_message="Update classroom status data"
            )

            print(f"🕒 {now.strftime('%H:%M:%S')} に実行完了。次回は {interval_sec//60} 分後。")

        except Exception as e:
            print(f"⚠️ メインループでエラー発生: {e}")

        time.sleep(interval_sec)

# スクリプト開始
if __name__ == "__main__":
    main_loop(600)  # 10分ごとに実行