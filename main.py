import os
import json
import csv
import time
from datetime import datetime
import pytz
import numpy as np
import requests
import gspread
from gspread_dataframe import get_as_dataframe

# === 設定値 ===
# Airoco APIキーは公開情報のため直接記述
AIROCO_API_KEY = "6b8aa7133ece423c836c38af01c59880"

# === 環境変数から設定を読み込み ===
SPREADSHEET_NAME = os.environ['SPREADSHEET_NAME']
# GitHub Secretsに登録したサービスアカウントのJSONキーを読み込む
google_creds_json = os.environ['GOOGLE_SERVICE_ACCOUNT_KEY']
google_creds_dict = json.loads(google_creds_json)

# === Google Sheets API 認証 (サービスアカウントを使用) ===
def get_gspread_client():
    """サービスアカウント情報を使ってgspreadクライアントを認証します。"""
    client = gspread.service_account_from_dict(google_creds_dict)
    return client

# === スケジュール取得 ===
def get_schedule_data(client):
    """Googleスプレッドシートから教室の予約スケジュールを抽出します。"""
    spreadsheet = client.open(SPREADSHEET_NAME)
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
                    # 年を2025年に固定
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
    """現在の時間に対応する時限を返します。"""
    if 8 <= hour < 10: return "1限"
    elif 10 <= hour < 12: return "2限"
    elif 13 <= hour < 15: return "3限"
    elif 15 <= hour < 17: return "4限"
    return None

# === CO2センサー値取得 ===
def get_avg_co2():
    """Airoco APIから過去1時間の平均CO2濃度を取得します。"""
    now_unix = int(time.time())
    start_time = now_unix - 3600
    url = f'https://airoco.necolico.jp/data-api/day-csv?id=CgETViZ2&subscription-key={AIROCO_API_KEY}&startDate={start_time}'
    res = requests.get(url)
    co2_values = []
    try:
        res.raise_for_status() # HTTPエラーがあれば例外を発生
        reader = csv.reader(res.text.strip().splitlines())
        for row in reader:
            if len(row) > 6 and row[1] == 'Ｒ３ー４０１':
                try:
                    co2 = float(row[3])
                    co2_values.append(co2)
                except ValueError:
                    continue
    except requests.exceptions.RequestException as e:
        print(f"❌ APIリクエストエラー: {e}")
        return None
    
    return np.mean(co2_values) if co2_values else None

# === 状態判定 ===
def determine_usage(booking, co2):
    """予約状況とCO2濃度から教室の状態を判定します。"""
    if booking == "○" and co2 and co2 > 1000:
        return "✅ 正常利用中"
    elif booking == "○" and (co2 is None or co2 < 600):
        return "⚠️ 無断キャンセルの可能性"
    else:
        return "🟢 空室または利用無し"

# === メイン処理 ===
def main():
    """メイン処理。各種データを取得・判定し、結果をJSONファイルに出力します。"""
    try:
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        # 現在時刻を2025年として扱う
        today_str = datetime(2025, now.month, now.day).strftime('%Y-%m-%d')
        hour = now.hour
        period = get_current_period(hour)

        # Google Sheetsからデータを取得
        gspread_client = get_gspread_client()
        schedule = get_schedule_data(gspread_client)
        booking = next((item['状態'] for item in schedule if item['日付'] == today_str and item['時間'] == period), "データなし")

        # CO2センサー値を取得
        co2 = get_avg_co2()

        # 状態を判定
        status = determine_usage(booking, co2)

        # 出力データを作成
        output_data = {
            "status_text": status,
            "booking_status": booking or "なし",
            "co2_value": f"{co2:.1f}" if co2 is not None else "N/A",
            "current_period": period or "授業時間外",
            "last_updated": now.strftime('%Y-%m-%d %H:%M:%S')
        }

        # データをJSONファイルに書き出し
        with open("status.json", "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"✅ {now.strftime('%H:%M:%S')} - status.json の生成に成功しました。")

    except Exception as e:
        print(f"❌ メイン処理でエラーが発生しました: {e}")

if __name__ == "__main__":
    main()