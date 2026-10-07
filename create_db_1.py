import sqlite3

DB_NAME = "fatigue.db"


def add_column_if_not_exists(cursor, table_name, column_name, column_def):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        print(f"[DB MIGRATE] add {table_name}.{column_name}")
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
        )


conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

# ==========================================
# 使用者資料表
# ==========================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE,
    user_type TEXT DEFAULT 'general',
    password_hash TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

add_column_if_not_exists(cursor, "users", "user_type", "TEXT DEFAULT 'general'")
add_column_if_not_exists(cursor, "users", "password_hash", "TEXT")
add_column_if_not_exists(cursor, "users", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP")


# ==========================================
# 狀態分類表
# ==========================================
cursor.execute("""
CREATE TABLE IF NOT EXISTS fatigue_labels (
    label INTEGER PRIMARY KEY,
    label_name TEXT UNIQUE,
    description TEXT
)
""")

label_data = [
    (0, "NORMAL", "正常狀態"),
    (1, "YAWN", "打哈欠"),
    (2, "EYE_CLOSE_OR_BLINK", "閉眼、快速眨眼、眼睛異常"),
    (3, "NOD", "點頭、低頭"),
    (4, "SHAKE_HEAD", "搖頭、左右晃頭"),
    (5, "LOOK_AWAY", "眼神飄移、視線偏移、注意力偏移")
]

cursor.executemany("""
INSERT OR IGNORE INTO fatigue_labels (label, label_name, description)
VALUES (?, ?, ?)
""", label_data)


# ==========================================
# 暫存 / 待人工審核資料
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
    original_label INTEGER,
    original_label_name TEXT,
    review_status TEXT DEFAULT 'pending',
    reviewed_label INTEGER,
    reviewed_label_name TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    user_type TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

for column, definition in [
    ("original_label", "INTEGER"),
    ("original_label_name", "TEXT"),
    ("review_status", "TEXT DEFAULT 'pending'"),
    ("reviewed_label", "INTEGER"),
    ("reviewed_label_name", "TEXT"),
    ("reviewed_by", "TEXT"),
    ("reviewed_at", "TEXT")
]:
    add_column_if_not_exists(cursor, "pending_data", column, definition)


# ==========================================
# 正式疲勞資料表
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

add_column_if_not_exists(cursor, "fatigue_data", "blink_rate_10s", "REAL DEFAULT 0")
add_column_if_not_exists(cursor, "fatigue_data", "head_motion", "REAL DEFAULT 0")
add_column_if_not_exists(cursor, "fatigue_data", "label_name", "TEXT")
add_column_if_not_exists(cursor, "fatigue_data", "user_type", "TEXT DEFAULT 'general'")
add_column_if_not_exists(cursor, "fatigue_data", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP")


# ==========================================
# Rule 資料表
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
# View
# ==========================================
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_normal_data AS
SELECT * FROM fatigue_data WHERE label = 0
""")
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_yawn_data AS
SELECT * FROM fatigue_data WHERE label = 1
""")
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_eye_data AS
SELECT * FROM fatigue_data WHERE label = 2
""")
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_nod_data AS
SELECT * FROM fatigue_data WHERE label = 3
""")
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_shake_head_data AS
SELECT * FROM fatigue_data WHERE label = 4
""")
cursor.execute("""
CREATE VIEW IF NOT EXISTS view_look_away_data AS
SELECT * FROM fatigue_data WHERE label = 5
""")


# ==========================================
# Index
# ==========================================
cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_pending_data_user_status
ON pending_data(user_id, review_status)
""")
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


conn.commit()
conn.close()

print("Database Created / Migrated Successfully")
print("Phase 1 review tables and login fields ready")
