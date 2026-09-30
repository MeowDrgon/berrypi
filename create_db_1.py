import sqlite3

DB_NAME = "fatigue.db"


# ==========================================
# 如果舊資料表缺欄位，自動新增欄位
# ==========================================
def add_column_if_not_exists(cursor, table_name, column_name, column_def):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]

    if column_name not in columns:
        print(f"[DB MIGRATE] add {table_name}.{column_name}")
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
        )


# ==========================================
# 建立 / 連接資料庫
# ==========================================
conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()


# ==========================================
# 使用者資料表
# user_type:
# general = 一般人資料庫
# small_eye = 乾眼症資料庫
# ==========================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE
)
""")

add_column_if_not_exists(
    cursor,
    "users",
    "user_type",
    "TEXT DEFAULT 'general'"
)


add_column_if_not_exists(
    cursor,
    "users",
    "created_at",
    "TEXT DEFAULT CURRENT_TIMESTAMP"
)


# ==========================================
# 狀態分類表
# 這張表用來管理 Label 代表什麼狀態
# ==========================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS fatigue_labels (
    label INTEGER PRIMARY KEY,
    label_name TEXT UNIQUE,
    description TEXT
)
""")


# ==========================================
# 預設狀態分類
# ==========================================
label_data = [
    (
        0,
        "NORMAL",
        "正常狀態"
    ),
    (
        1,
        "YAWN",
        "打哈欠"
    ),
    (
        2,
        "EYE_CLOSE_OR_BLINK",
        "閉眼、快速眨眼、眼睛異常"
    ),
    (
        3,
        "NOD",
        "點頭、低頭"
    ),
    (
        4,
        "SHAKE_HEAD",
        "搖頭、左右晃頭"
    ),
    (
        5,
        "LOOK_AWAY",
        "眼神飄移、視線偏移、注意力偏移"
    )
]
# ==========================================
# 類別約束
# ==========================================
cursor.executemany("""
INSERT OR IGNORE INTO fatigue_labels (
    label,
    label_name,
    description
)
VALUES (?, ?, ?)
""", label_data)

# ==========================================
# 暫存疲勞資料表
# ==========================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS pending_data(

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

    user_type TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")
# ==========================================
# 疲勞資料表
# 所有人、所有狀態的資料都存在這張表
# 用 user_id 區分使用者
# 用 label 區分狀態
# ==========================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS fatigue_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id TEXT,
    time TEXT,

    ear REAL,
    mar REAL,
    blink INTEGER,

    nod_ratio REAL,
    head_ratio REAL,

    label INTEGER
)
""")


# ==========================================
# 新版多狀態資料新增欄位
# ==========================================
add_column_if_not_exists(
    cursor,
    "fatigue_data",
    "blink_rate_10s",
    "REAL DEFAULT 0"
)

add_column_if_not_exists(
    cursor,
    "fatigue_data",
    "head_motion",
    "REAL DEFAULT 0"
)

add_column_if_not_exists(
    cursor,
    "fatigue_data",
    "label_name",
    "TEXT"
)

add_column_if_not_exists(
    cursor,
    "fatigue_data",
    "user_type",
    "TEXT DEFAULT 'general'"
)

add_column_if_not_exists(
    cursor,
    "fatigue_data",
    "created_at",
    "TEXT DEFAULT CURRENT_TIMESTAMP"
)


# ==========================================
# Rule 資料表
# 用來儲存訓練後的 JSON rule
# ==========================================
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


# ==========================================
# 建立分類查詢 View
# 這些不是新資料表，是方便查資料用
# ==========================================

# 正常資料
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_normal_data AS
SELECT *
FROM fatigue_data
WHERE label = 0
""")

# 打哈欠資料
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_yawn_data AS
SELECT *
FROM fatigue_data
WHERE label = 1
""")

# 閉眼 / 快速眨眼 / 眼睛異常資料
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_eye_data AS
SELECT *
FROM fatigue_data
WHERE label = 2
""")

# 點頭 / 低頭資料
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_nod_data AS
SELECT *
FROM fatigue_data
WHERE label = 3
""")

# 搖頭 / 晃頭資料
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_shake_head_data AS
SELECT *
FROM fatigue_data
WHERE label = 4
""")

# 眼神飄移 / 注意力偏移資料
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_look_away_data AS
SELECT *
FROM fatigue_data
WHERE label = 5
""")


# ==========================================
# 建立索引，加快查詢速度
# ==========================================
cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_fatigue_data_user_id
ON fatigue_data(user_id)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_fatigue_data_label
ON fatigue_data(label)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_fatigue_data_user_label
ON fatigue_data(user_id, label)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_fatigue_rules_user_id
ON fatigue_rules(user_id)
""")

# ==========================================
# 儲存並關閉
# ==========================================
conn.commit()
conn.close()

print("Database Created / Migrated Successfully")
print("Label tables and category views created successfully")