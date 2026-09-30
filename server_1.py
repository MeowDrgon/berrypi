from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import json
import pandas as pd
from datetime import datetime

# ==========================================
# Flask 初始化
# ==========================================
app = Flask(__name__)

DB_NAME = "fatigue.db"

BASE_DIR = "database"
RULE_DIR = "rules"

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(RULE_DIR, exist_ok=True)

print(
    "[DB PATH]",
    os.path.abspath(DB_NAME)
)
# ==========================================
# 大數據庫類型
# ==========================================
# general：一般人資料庫
# small_eye：小眼睛資料庫
# 只保留這兩種
# ==========================================
BIG_DATASET_TYPE = "general"
# 小眼睛使用者可以改成：
# BIG_DATASET_TYPE = "small_eye"

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
# 新版特徵欄位
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
# SQLite 連線
# ==========================================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ==========================================
# 初始化資料庫
# ==========================================
def init_db():

    conn = get_db()
    cursor = conn.cursor()

    # ==================================
    # 使用者表
    # user_type:
    # general / small_eye
    # ==================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE,
        user_type TEXT DEFAULT 'general',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==================================
    # 疲勞資料表
    # 相容新版多分類資料
    # ==================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fatigue_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id TEXT,
        time TEXT,

        ear REAL,
        mar REAL,
        blink INTEGER,

        blink_rate_10s REAL,

        nod_ratio REAL,
        head_ratio REAL,
        head_motion REAL,

        label INTEGER,
        label_name TEXT,

        user_type TEXT DEFAULT 'general',
                   
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==================================
    # Rule 表
    # 儲存 JSON rule
    # ==================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fatigue_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id TEXT,
        rule_json TEXT,

        big_dataset_type TEXT,
        version TEXT,

        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==================================
    # 索引
    # ==================================
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_fatigue_data_user_id
    ON fatigue_data(user_id)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_fatigue_data_label
    ON fatigue_data(label)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_fatigue_rules_user_id
    ON fatigue_rules(user_id)
    """)

    conn.commit()
    conn.close()

    print("[DB] SQLite initialized")


# ==========================================
# 大數據庫路徑
# ==========================================
def get_big_dataset_path(big_dataset_type=None):

    if big_dataset_type is None:
        big_dataset_type = BIG_DATASET_TYPE

    if big_dataset_type not in BIG_DATASET_FILES:
        print(f"[ERROR] unknown big_dataset_type: {big_dataset_type}")
        return None

    path = BIG_DATASET_FILES[big_dataset_type]

    if not os.path.exists(path):

        os.makedirs(BASE_DIR, exist_ok=True)

        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(
                "Time,EAR,MAR,Blink,BlinkRate10s,NodRatio,HeadRatio,HeadMotion,Label,LabelName\n"
            )

    return path


# ==========================================
# Rule 路徑
# ==========================================
def get_rule_path(user_id):
    return os.path.join(RULE_DIR, f"{user_id}_multiclass_rule.json")


# ==========================================
# 取得使用者類型
# ==========================================
def get_user_type(user_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT user_type FROM users
    WHERE user_id = ?
    """, (user_id,))

    row = cursor.fetchone()

    conn.close()

    if row is None:
        return BIG_DATASET_TYPE

    user_type = row["user_type"]

    if user_type not in BIG_DATASET_FILES:
        return BIG_DATASET_TYPE

    return user_type


# ==========================================
# 建立 / 更新使用者
# ==========================================
def ensure_user(user_id, user_type=None):

    if user_type is None:
        user_type = BIG_DATASET_TYPE

    if user_type not in BIG_DATASET_FILES:
        user_type = BIG_DATASET_TYPE

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, user_type)
    VALUES (?, ?)
    """, (user_id, user_type))

    cursor.execute("""
    UPDATE users
    SET user_type = ?
    WHERE user_id = ?
    """, (user_type, user_id))

    conn.commit()
    conn.close()


# ==========================================
# 從 SQLite 讀取個人資料
# ==========================================
def get_personal_df_from_db(user_id):

    conn = get_db()

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
        params=(user_id,)
    )

    conn.close()

    return df



# ==========================================
# 依 rule 判斷目前狀態
# POST /rule
# ==========================================
def judge_by_rule(rule, data):

    try:
        ear = float(data.get("EAR", 0))
        mar = float(data.get("MAR", 0))
        blink_rate_10s = float(data.get("BlinkRate10s", 0))
        nod_ratio = float(data.get("NodRatio", 0))
        head_ratio = float(data.get("HeadRatio", 0))
        head_motion = float(data.get("HeadMotion", 0))

        rules = rule["rules"]

        # ==================================
        # 判斷順序可以依你們需求調整
        # 先判斷明顯疲勞/動作
        # ==================================
        if mar > rules["YAWN"]["YAWN_THRESHOLD"]:
            return 1, "YAWN"

        if (
            ear < rules["EYE_CLOSE_OR_BLINK"]["EAR_THRESHOLD"]
            or blink_rate_10s > rules["EYE_CLOSE_OR_BLINK"]["BLINK_RATE_THRESHOLD"]
        ):
            return 2, "EYE_CLOSE_OR_BLINK"

        if nod_ratio > (
            rules["NOD"]["BASELINE_NOD"]
            + rules["NOD"]["NOD_DELTA"]
        ):
            return 3, "NOD"

        if head_motion > rules["SHAKE_HEAD"]["SHAKE_THRESHOLD"]:
            return 4, "SHAKE_HEAD"

        if abs(
            head_ratio - rules["LOOK_AWAY"]["BASELINE_HEAD"]
        ) > rules["LOOK_AWAY"]["HEAD_DELTA"]:
            return 5, "LOOK_AWAY"

        return 0, "NORMAL"

    except Exception as e:
        print("[JUDGE ERROR]", e)
        return -1, "ERROR"


# ==========================================
# 首頁測試
# ==========================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "msg": "Fatigue server is running",
        "version": "multiclass_rule_server"
    })


# ==========================================
# 設定使用者類型
# general / small_eye
# ==========================================
@app.route("/user_type/<user_id>", methods=["POST"])
def set_user_type(user_id):

    try:
        data = request.json or {}

        user_type = data.get("user_type", "general")

        if user_type not in BIG_DATASET_FILES:
            return jsonify({
                "status": "error",
                "msg": "user_type must be general or small_eye"
            })

        ensure_user(user_id, user_type)

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "user_type": user_type
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "msg": str(e)
        })



# ==========================================
# ④ 取得 Rule
# GET /rule/<user_id>
# ==========================================
@app.route("/rule/<user_id>", methods=["GET"])
def get_rule(user_id):

    try:
        path = get_rule_path(user_id)

        if not os.path.exists(path):
            return jsonify({
                "status": "error",
                "msg": "no rule"
            })

        with open(path, "r", encoding="utf-8") as f:
            rule = json.load(f)

        return jsonify({
            "status": "success",
            "rule": rule
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "msg": str(e)
        })


@app.route("/latest_rule/<user_id>", methods=["GET"])
def latest_rule(user_id):

    path = get_rule_path(user_id)

    if not os.path.exists(path):
        return jsonify({
            "status": "error",
            "msg": "rule not found"
        })

    return jsonify(
        json.load(
            open(path, "r", encoding="utf-8")
        )
    )

@app.route("/upload", methods=["POST"])
def upload_data():

    try:
        #這邊這幾行是各種檢查顯示
        print("========== UPLOAD ==========")

        data = request.json

        print("[UPLOAD RECEIVED]")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        
        print("[UPLOAD]")
        print(data)

        user_id = data.get("user_id")
        user_type = data.get("user_type", "general")

        ensure_user(user_id, user_type)

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO fatigue_data (
            user_id,
            time,

            ear,
            mar,
            blink,
            blink_rate_10s,

            nod_ratio,
            head_ratio,
            head_motion,

            label,
            label_name,

            user_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            data.get("Time"),

            data.get("EAR"),
            data.get("MAR"),
            data.get("Blink"),
            data.get("BlinkRate10s"),

            data.get("NodRatio"),
            data.get("HeadRatio"),
            data.get("HeadMotion"),

            data.get("Label"),
            data.get("LabelName"),
            user_type
        ))

        conn.commit()
        cursor.execute(
            "SELECT COUNT(*) FROM fatigue_data"
        )

        print(
            "[TOTAL ROWS]",
            cursor.fetchone()[0]
        )
        conn.close()

        return jsonify({
            "status": "success"
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "msg": str(e)
        })

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "msg": "server connected",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
# ==========================================
# Server 啟動
# ==========================================

if __name__ == "__main__":

    init_db()

    # 建立兩個大數據庫空檔案
    get_big_dataset_path("general")
    get_big_dataset_path("small_eye")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )