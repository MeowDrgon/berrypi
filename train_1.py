import os
import json
import sqlite3
import pandas as pd
from datetime import datetime

# ==========================================
# FATIGUE PERSONALIZED MULTICLASS RULE TRAINING SYSTEM
# 不使用 pkl
# 從 fatigue.db 讀個人資料
# 依 users.user_type 自動選 general / small_eye 大數據庫
# 輸出個人化 JSON rule
# ==========================================


# ==========================================
# 基本設定
# ==========================================
DB_NAME = "fatigue.db"
BASE_DIR = "database"
RULE_DIR = "rules"

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(RULE_DIR, exist_ok=True)


# ==========================================
# 大數據庫檔案
# general：一般人資料庫
# small_eye：小眼睛資料庫
# ==========================================
BIG_DATASET_FILES = {
    "general": os.path.join(BASE_DIR, "general_dataset.csv"),
    "small_eye": os.path.join(BASE_DIR, "small_eye_dataset.csv")
}


# ==========================================
# 訓練比例
# 個人 : 大數據 = 20 : 80 = 1 : 4
# ==========================================
PERSONAL_RATIO = 20
BIG_DATA_RATIO = 80
BIG_DATA_MULTIPLIER = 4


# ==========================================
# 多分類 Label 定義
# ==========================================
LABEL_MAP = {
    0: "NORMAL",
    1: "YAWN",
    2: "EYE_CLOSE_OR_BLINK",
    3: "NOD",
    4: "SHAKE_HEAD",
    5: "LOOK_AWAY"
}


# ==========================================
# 特徵欄位
# ==========================================
FEATURE_COLUMNS = [
    "EAR",
    "MAR",
    "Blink",
    "BlinkRate10s",
    "NodRatio",
    "HeadRatio",
    "HeadMotion"
]

REQUIRED_COLUMNS = FEATURE_COLUMNS + ["Label"]


# ==========================================
# 從 users 表讀取所有 user
# ==========================================
def get_all_users_from_db():

    if not os.path.exists(DB_NAME):
        print(f"[ERROR] {DB_NAME} not found")
        return []

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT user_id
    FROM users
    ORDER BY user_id
    """)

    users = [row[0] for row in cursor.fetchall()]

    conn.close()

    return users


# ==========================================
# 從 users 表讀 user_type
# ==========================================
def get_user_type_from_db(user_id):

    if not os.path.exists(DB_NAME):
        print(f"[WARN] {DB_NAME} not found，預設 general")
        return "general"

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT user_type
    FROM users
    WHERE user_id = ?
    """, (str(user_id),))

    row = cursor.fetchone()

    conn.close()

    if row is None:
        print(f"[WARN] users 找不到 user_id={user_id}，預設 general")
        return "general"

    user_type = row[0]

    if user_type not in BIG_DATASET_FILES:
        print(f"[WARN] user_type 不合法：{user_type}，預設 general")
        return "general"

    return user_type


# ==========================================
# 根據 user_type 取得大數據庫路徑
# ==========================================
def get_big_dataset_path_by_user(user_id):

    user_type = get_user_type_from_db(user_id)

    big_dataset_csv = BIG_DATASET_FILES.get(user_type)

    return big_dataset_csv, user_type


# ==========================================
# 從 fatigue.db 讀取某個 user 的個人資料
# ==========================================
def get_personal_df_from_db(user_id):

    if not os.path.exists(DB_NAME):
        print(f"[ERROR] {DB_NAME} not found")
        return None

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
    WHERE user_id = ?
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(str(user_id),)
    )

    conn.close()

    return df


# ==========================================
# Rule 輸出路徑
# ==========================================
def get_rule_path(user_id):

    return os.path.join(RULE_DIR, f"{user_id}_multiclass_rule.json")


# ==========================================
# 清理資料
# ==========================================
def clean_dataset(df, source_name="dataset"):

    if df is None:
        print(f"[ERROR] {source_name} is None")
        return None

    df = df.copy()

    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            print(f"[WARN] {source_name} 缺少欄位 {col}，自動補 0")
            df[col] = 0

    if "Label" not in df.columns:
        print(f"[ERROR] {source_name} 缺少 Label 欄位")
        return None

    df = df[REQUIRED_COLUMNS].copy()

    for col in REQUIRED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()

    df["Label"] = df["Label"].astype(int)

    df = df[df["Label"].isin(LABEL_MAP.keys())]

    return df


# ==========================================
# 建立訓練資料
# 20% 個人資料 + 80% 對應大數據庫
# ==========================================
def build_training_dataset(user_id):

    big_dataset_csv, user_type = get_big_dataset_path_by_user(user_id)

    print("[USER ID]", user_id)
    print("[USER TYPE]", user_type)
    print("[BIG DATASET CSV]", big_dataset_csv)

    # -----------------------------
    # 從 fatigue.db 讀個人資料
    # -----------------------------
    personal_df = get_personal_df_from_db(user_id)

    if personal_df is None:
        print("[ERROR] personal data read failed")
        return None

    # -----------------------------
    # 檢查大數據庫
    # -----------------------------
    if big_dataset_csv is None or not os.path.exists(big_dataset_csv):
        print(f"[SKIP] {user_id} 是 {user_type}，但大數據庫不存在：{big_dataset_csv}")
        return None

    big_df = pd.read_csv(big_dataset_csv)

    print("[PERSONAL RAW ROWS]", len(personal_df))
    print("[BIG DATASET RAW ROWS]", len(big_df))

    personal_df = clean_dataset(personal_df, source_name="personal")
    big_df = clean_dataset(big_df, source_name=user_type)

    if personal_df is None or big_df is None:
        return None

    print("[PERSONAL CLEAN ROWS]", len(personal_df))
    print("[BIG DATASET CLEAN ROWS]", len(big_df))

    # -----------------------------
    # 資料量檢查
    # -----------------------------
    if len(personal_df) < 10:
        print("[ERROR] 個人資料太少，至少需要 10 筆")
        return None

    if len(big_df) < 20:
        print(f"[SKIP] {user_type} 大數據庫資料太少，至少需要 20 筆")
        return None

    if big_df["Label"].nunique() < 1:
        print(f"[SKIP] {user_type} 大數據庫至少需要 1 種 Label")
        return None

    # -----------------------------
    # 20% 個人 + 80% 大數據
    # 個人 : 大數據 = 1 : 4
    # -----------------------------
    personal_count = len(personal_df)
    need_big_count = personal_count * BIG_DATA_MULTIPLIER

    big_sample = big_df.sample(
        n=min(need_big_count, len(big_df)),
        random_state=42
    )

    train_df = pd.concat(
        [personal_df, big_sample],
        ignore_index=True
    )

    train_df = train_df.sample(
        frac=1,
        random_state=42
    ).reset_index(drop=True)

    total_count = len(train_df)
    personal_ratio = len(personal_df) / total_count * 100
    big_ratio = len(big_sample) / total_count * 100

    print("\n========== Dataset Info ==========")
    print(f"Personal data used : {len(personal_df)}")
    print(f"Big data used      : {len(big_sample)}")
    print(f"Total mixed data   : {total_count}")
    print(f"Big dataset type   : {user_type}")
    print(f"Personal ratio     : {personal_ratio:.1f}%")
    print(f"Big data ratio     : {big_ratio:.1f}%")
    print("==================================\n")

    return train_df, user_type


# ==========================================
# 安全取 median
# ==========================================
def safe_median(df, column, default_value):

    if df is None or len(df) == 0:
        return default_value

    if column not in df.columns:
        return default_value

    value = df[column].median()

    if pd.isna(value):
        return default_value

    return float(value)


# ==========================================
# 安全取 quantile
# ==========================================
def safe_quantile(series, q, default_value):

    if series is None or len(series) == 0:
        return default_value

    value = series.quantile(q)

    if pd.isna(value):
        return default_value

    return float(value)


# ==========================================
# 印 Label 分布
# ==========================================
def print_label_distribution(df):

    print("========== Label Distribution ==========")

    counts = df["Label"].value_counts().sort_index()

    for label, count in counts.items():
        name = LABEL_MAP.get(int(label), "UNKNOWN")
        print(f"Label {label} ({name}) : {count}")

    print("========================================\n")


# ==========================================
# 用多分類資料產生 rule.json
# ==========================================
def train_multiclass_rule_from_dataset(df, user_type):

    print_label_distribution(df)

    normal_df = df[df["Label"] == 0]
    yawn_df = df[df["Label"] == 1]
    eye_df = df[df["Label"] == 2]
    nod_df = df[df["Label"] == 3]
    shake_df = df[df["Label"] == 4]
    look_df = df[df["Label"] == 5]

    if len(normal_df) < 5:
        print("[ERROR] NORMAL 資料太少，至少需要 5 筆")
        return None

    # ==================================
    # NORMAL baseline
    # ==================================
    normal_ear = safe_median(normal_df, "EAR", 0.25)
    normal_mar = safe_median(normal_df, "MAR", 0.20)
    normal_blink_rate = safe_median(normal_df, "BlinkRate10s", 0)
    normal_nod = safe_median(normal_df, "NodRatio", 0.30)
    normal_head = safe_median(normal_df, "HeadRatio", 0.50)
    normal_head_motion = safe_median(normal_df, "HeadMotion", 0)

    # ==================================
    # 1. YAWN rule
    # ==================================
    if len(yawn_df) >= 3:
        yawn_mar = safe_median(yawn_df, "MAR", normal_mar)

        if yawn_mar > normal_mar:
            yawn_threshold = (normal_mar + yawn_mar) / 2
        else:
            yawn_threshold = max(0.35, normal_mar * 1.8)
    else:
        yawn_threshold = max(0.35, normal_mar * 1.8)

    # ==================================
    # 2. EYE_CLOSE_OR_BLINK rule
    # ==================================
    if len(eye_df) >= 3:
        eye_ear = safe_median(eye_df, "EAR", normal_ear)
        eye_blink_rate = safe_median(eye_df, "BlinkRate10s", normal_blink_rate)

        if eye_ear < normal_ear:
            ear_threshold = (normal_ear + eye_ear) / 2
        else:
            ear_threshold = normal_ear * 0.90

        if eye_blink_rate > normal_blink_rate:
            blink_rate_threshold = (normal_blink_rate + eye_blink_rate) / 2
        else:
            blink_rate_threshold = max(6, normal_blink_rate + 3)
    else:
        ear_threshold = normal_ear * 0.90
        blink_rate_threshold = max(6, normal_blink_rate + 3)

    # ==================================
    # 3. NOD rule
    # ==================================
    if len(nod_df) >= 3:
        nod_value = safe_median(nod_df, "NodRatio", normal_nod)

        nod_delta = max(
            0.05,
            abs(nod_value - normal_nod) / 2
        )
    else:
        nod_delta = 0.05

    # ==================================
    # 4. SHAKE_HEAD rule
    # ==================================
    if len(shake_df) >= 3:
        shake_motion = safe_median(shake_df, "HeadMotion", normal_head_motion)

        if shake_motion > normal_head_motion:
            shake_threshold = (normal_head_motion + shake_motion) / 2
        else:
            shake_threshold = max(0.08, normal_head_motion + 0.05)
    else:
        shake_threshold = max(0.08, normal_head_motion + 0.05)

    # ==================================
    # 5. LOOK_AWAY rule
    # ==================================
    normal_head_diff = abs(normal_df["HeadRatio"] - normal_head)
    normal_head_delta_95 = safe_quantile(normal_head_diff, 0.95, 0.15)

    if len(look_df) >= 3:
        look_head_diff = abs(look_df["HeadRatio"] - normal_head)

        look_delta = safe_median(
            pd.DataFrame({"diff": look_head_diff}),
            "diff",
            normal_head_delta_95
        )

        head_delta = max(
            0.12,
            (normal_head_delta_95 + look_delta) / 2
        )
    else:
        head_delta = max(0.15, normal_head_delta_95)

    # ==================================
    # rule JSON
    # 不保留舊版相容欄位
    # ==================================
    rule = {
        "version": "multiclass_rule_v1",

        "big_dataset_type": user_type,

        "train_ratio": {
            "personal": PERSONAL_RATIO,
            "big_data": BIG_DATA_RATIO
        },

        "label_map": LABEL_MAP,

        "features": FEATURE_COLUMNS,

        "baseline": {
            "EAR": round(float(normal_ear), 3),
            "MAR": round(float(normal_mar), 3),
            "BlinkRate10s": round(float(normal_blink_rate), 3),
            "NodRatio": round(float(normal_nod), 3),
            "HeadRatio": round(float(normal_head), 3),
            "HeadMotion": round(float(normal_head_motion), 3)
        },

        "rules": {
            "YAWN": {
                "label": 1,
                "condition": "MAR > YAWN_THRESHOLD",
                "YAWN_THRESHOLD": round(float(yawn_threshold), 3)
            },

            "EYE_CLOSE_OR_BLINK": {
                "label": 2,
                "condition": "EAR < EAR_THRESHOLD or BlinkRate10s > BLINK_RATE_THRESHOLD",
                "EAR_THRESHOLD": round(float(ear_threshold), 3),
                "BLINK_RATE_THRESHOLD": round(float(blink_rate_threshold), 3)
            },

            "NOD": {
                "label": 3,
                "condition": "NodRatio > BASELINE_NOD + NOD_DELTA",
                "BASELINE_NOD": round(float(normal_nod), 3),
                "NOD_DELTA": round(float(nod_delta), 3)
            },

            "SHAKE_HEAD": {
                "label": 4,
                "condition": "HeadMotion > SHAKE_THRESHOLD",
                "SHAKE_THRESHOLD": round(float(shake_threshold), 3)
            },

            "LOOK_AWAY": {
                "label": 5,
                "condition": "abs(HeadRatio - BASELINE_HEAD) > HEAD_DELTA",
                "BASELINE_HEAD": round(float(normal_head), 3),
                "HEAD_DELTA": round(float(head_delta), 3)
            }
        },

        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return rule


# ==========================================
# 儲存 rule.json
# ==========================================
def save_rule(user_id, rule, len(train_df)):

    rule_path = get_rule_path(user_id)

    with open(rule_path, "w", encoding="utf-8") as f:
        json.dump(rule, f, indent=4, ensure_ascii=False)

    print(f"\n[SAVED] Rule saved to {rule_path}")
    print(json.dumps(rule, indent=4, ensure_ascii=False))


# ==========================================
# 訓練單一 user
# ==========================================
def train_user(user_id):

    print("\n===================================")
    print(f"Training Personalized Rule for User {user_id}")
    print("===================================\n")

    result = build_training_dataset(user_id)

    if result is None:
        print(f"[FAILED] User {user_id} rule training failed")
        return

    train_df, user_type = result

    rule = train_multiclass_rule_from_dataset(train_df, user_type)

    if rule is None:
        print(f"[FAILED] User {user_id} rule generation failed")
        return

    save_rule(user_id, rule)

    print(f"\n[SUCCESS] User {user_id} personalized rule training completed")


# ==========================================
# 批次訓練所有 user
# 從 fatigue.db 的 users 表找 user
# ==========================================
def train_all_users():

    users = get_all_users_from_db()

    if len(users) == 0:
        print("[ERROR] No users found in fatigue.db")
        return

    print("[USERS FOUND]", users)

    for user_id in users:
        train_user(user_id)


# ==========================================
# 主程式
# ==========================================
if __name__ == "__main__":

    print("===== FATIGUE PERSONALIZED RULE TRAINING SYSTEM =====")
    print("[CURRENT DIR]", os.getcwd())
    print("[DB NAME]", DB_NAME)
    print("[BASE DIR]", BASE_DIR)
    print("[RULE DIR]", RULE_DIR)
    print("[BIG DATASET FILES]", BIG_DATASET_FILES)
    print("[USER TYPE SOURCE]", "fatigue.db users.user_type")

    train_all_users()