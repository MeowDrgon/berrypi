#匯入各種套件
import sqlite3
import pandas as pd
import os
#來源SQLite資料庫常數
DB_NAME = "fatigue.db"
# 輸出的 CSV 檔案要存放的資料夾名稱
BASE_DIR = "database"

# 確保輸出資料夾存在，如果不存在就自動建立
os.makedirs(BASE_DIR, exist_ok=True)

#2個dataset的csv檔集
GENERAL_OUTPUT = os.path.join(BASE_DIR, "general_dataset.csv")
SMALL_EYE_OUTPUT = os.path.join(BASE_DIR, "small_eye_dataset.csv")

#csv檔欄位名稱順序
CSV_COLUMNS = [
    "Time",
    "EAR",
    "MAR",
    "Blink",
    "BlinkRate10s",
    "NodRatio",
    "HeadRatio",
    "HeadMotion",
    "Label",
    "LabelName"
]

#核心功能：從資料庫撈取資料並導出 CSV
def export_dataset(user_type, output_path):
    #根據指定的 user_type 從 SQL 資料庫撈取資料，清洗後儲存至指定的 CSV 路徑
    #建立與 SQLite 資料庫的連線
    conn = sqlite3.connect(DB_NAME)
    
    query = """
    SELECT
        time AS Time,
        ear AS EAR,
        mar AS MAR,
        blink AS Blink,
        blink_rate_10s AS BlinkRate10s,
        nod_ratio AS NodRatio,
        head_ratio AS HeadRatio,
        head_motion AS HeadMotion,
        label AS Label,
        label_name AS LabelName
    FROM fatigue_data
    WHERE user_type = ?
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(user_type,)
    )

    conn.close()

    if len(df) == 0:
        print(f"[WARN] 沒有 {user_type} 資料，不產生 {output_path}")
        return

    df = df[CSV_COLUMNS]
    df = df.dropna()
    df["Label"] = df["Label"].astype(int)

    df.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"[SAVED] {user_type} dataset saved to {output_path}")
    print(f"[ROWS] {len(df)}")

    print("\n========== Label Count ==========")
    print(df["LabelName"].value_counts())
    print("=================================\n")


if __name__ == "__main__":

    print("===== EXPORT BIG DATASET FROM SQLITE =====")

    export_dataset(
        user_type="general",
        output_path=GENERAL_OUTPUT
    )

    export_dataset(
        user_type="small_eye",
        output_path=SMALL_EYE_OUTPUT
    )

    print("===== EXPORT DONE =====")
