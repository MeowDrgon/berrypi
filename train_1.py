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
MODEL_ARCHIVE_DIR = os.path.join(RULE_DIR, "archive")

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(RULE_DIR, exist_ok=True)
os.makedirs(MODEL_ARCHIVE_DIR, exist_ok=True)    query = """
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
      AND (
          label_source = 'human_review'
          OR reviewed_label IS NOT NULL
      )
    """ os
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
MODEL_ARCHIVE_DIR = os.path.join(RULE_DIR, "archive")

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(RULE_DIR, exist_ok=True)
os.makedirs(MODEL_ARCHIVE_DIR, exist_ok=True)def save_rule(user_id, rule, training_rows):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version = f"multiclass_rule_{timestamp}"
    rule["version"] = version

    rule_path = get_rule_path(user_id)
    archive_path = os.path.join(MODEL_ARCHIVE_DIR, f"{user_id}_{version}.json")

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(rule, f, indent=4, ensure_ascii=False)

    with open(rule_path, "w", encoding="utf-8") as f:
        json.dump(rule, f, indent=4, ensure_ascii=False)

    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE model_versions SET is_active = 0 WHERE user_id = ?", (str(user_id),))
    conn.execute("""
        INSERT INTO model_versions (
            user_id, version, model_type, big_dataset_type,
            training_rows, is_active, rule_path
        )
        VALUES (?, ?, 'multiclass_rule', ?, ?, 1, ?)
    """, (
        str(user_id), version, rule.get("big_dataset_type"),
        int(training_rows), rule_path
    ))
    conn.commit()
    conn.close()

    print(f"\n[SAVED] active rule: {rule_path}")
    print(f"[ARCHIVE] {archive_path}")
    print(f"[VERSION] {version}"))