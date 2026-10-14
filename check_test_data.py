
import sqlite3
from pathlib import Path

# 檢查目前 Python 使用的資料夾
print("目前執行位置：", Path.cwd())

# 檢查此資料夾的 fatigue.db
db_path = Path.cwd() / "fatigue.db"

print("資料庫路徑：", db_path)
print("資料庫是否存在：", db_path.exists())

if not db_path.exists():
    print("找不到 fatigue.db，請確認 server_1.py 的執行位置")
    raise SystemExit

# 使用唯讀模式，避免意外建立空資料庫
conn = sqlite3.connect(
    db_path.as_uri() + "?mode=ro",
    uri=True
)

# 列出資料庫中的所有資料表
tables = conn.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name
""").fetchall()

print("\n資料庫中的資料表：")
for table in tables:
    print("-", table[0])

# 檢查 pending_data 是否存在
table_names = [table[0] for table in tables]

if "pending_data" in table_names:
    print("\n找到 pending_data！")

    columns = conn.execute(
        "PRAGMA table_info(pending_data)"
    ).fetchall()

    print("\npending_data 欄位：")
    for column in columns:
        print("-", column[1])

    count = conn.execute(
        "SELECT COUNT(*) FROM pending_data"
    ).fetchone()[0]

    print("\npending_data 總筆數：", count)

    rows = conn.execute(
        "SELECT * FROM pending_data LIMIT 3"
    ).fetchall()

    print("\n前 3 筆資料：")
    for row in rows:
        print(row)

else:
    print("\n找不到 pending_data 資料表！")
    print("可能是開錯資料庫，或資料庫尚未初始化。")

conn.close()
