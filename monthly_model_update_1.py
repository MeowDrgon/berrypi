"""
第二階段：每月模型更新入口。

建議由 Linux cron / systemd timer 每月執行一次：
    python3 monthly_model_update_1.py

流程：
1. 將目前已人工審核的資料重新匯出成大數據 CSV
2. 重新訓練每個使用者的 personalized rule
3. 新 rule 會保存為版本化 archive，並更新 active rule
4. 舊 rule 不刪除，方便回溯
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime

DB_NAME = "fatigue.db"
RUN_KEY = datetime.now().strftime("%Y-%m")


def run_step(label, command):
    print(f"\n===== {label} =====")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed, exit={result.returncode}")


def record_run(status, users_trained=0, message=""):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("""
        INSERT OR REPLACE INTO training_runs
        (run_key, run_type, started_at, finished_at, status, users_trained, message)
        VALUES (?, 'monthly', COALESCE(
            (SELECT started_at FROM training_runs WHERE run_key = ?),
            CURRENT_TIMESTAMP
        ), CURRENT_TIMESTAMP, ?, ?, ?)
    """, (RUN_KEY, RUN_KEY, status, users_trained, message[:500]))
    conn.commit()
    conn.close()


def count_users():
    conn = sqlite3.connect(DB_NAME)
    row = conn.execute("""
        SELECT COUNT(DISTINCT user_id)
        FROM fatigue_data
        WHERE label_source = 'human_review'
    """).fetchone()
    conn.close()
    return int(row[0] or 0)


def main():
    started = datetime.now().isoformat(timespec="seconds")
    print("===== MONTHLY MODEL UPDATE =====")
    print("[START]", started)
    print("[RUN KEY]", RUN_KEY)

    conn = sqlite3.connect(DB_NAME)
    conn.execute("""
        INSERT OR IGNORE INTO training_runs
        (run_key, run_type, started_at, status, message)
        VALUES (?, 'monthly', ?, 'running', 'monthly update started')
    """, (RUN_KEY, started))
    conn.commit()
    conn.close()

    try:
        # 先把已確認資料重新整理成 general / small_eye dataset。
        run_step(
            "EXPORT REVIEWED DATASET",
            [sys.executable, "big_dataset_1.py"]
        )

        # train_1.py 現在只使用 human_review 資料。
        run_step(
            "RETRAIN PERSONALIZED RULES",
            [sys.executable, "train_1.py"]
        )

        users = count_users()
        record_run(
            "success",
            users,
            "monthly export + reviewed-data retraining completed"
        )
        print("[SUCCESS] monthly model update completed")

    except Exception as exc:
        record_run("failed", 0, str(exc))
        print("[FAILED]", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
