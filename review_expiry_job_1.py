"""Run periodically on the receiving server to apply the queue lifecycle."""
import sqlite3
from review_queue_1 import migrate, expire

DB_NAME = "fatigue.db"

def main():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        migrate(conn)
        print(expire(conn))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
