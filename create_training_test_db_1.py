"""Generate isolated SYNTHETIC data for pipeline smoke tests only.
Never use this database for real training or deployment.
Run: py create_training_test_db_1.py
"""
import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

FEATURES = ("ear", "mar", "blink", "blink_rate_10s", "nod_ratio", "head_ratio", "head_motion")


def build(path):
    path = Path(path).resolve()
    if path.name == "fatigue.db":
        raise SystemExit("Refusing to overwrite fatigue.db")
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing database: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261014)
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE fatigue_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, time TEXT,
                ear REAL, mar REAL, blink INTEGER, blink_rate_10s REAL,
                nod_ratio REAL, head_ratio REAL, head_motion REAL,
                label INTEGER, label_name TEXT,
                user_type TEXT DEFAULT 'general',
                label_source TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        base = datetime(2026, 9, 1, 9, 0, 0)
        rows = []
        for day in range(6):
            for label in (0, 1):
                for i in range(20):
                    # Distinct, mildly overlapping distributions; NOT real sensor data.
                    if label == 0:
                        ear = rng.gauss(0.30, 0.045)
                        mar = rng.gauss(0.18, 0.08)
                        blink = rng.randint(0, 1)
                        blink_rate = rng.gauss(3, 1.2)
                        nod = rng.gauss(0.06, 0.045)
                    else:
                        ear = rng.gauss(0.17, 0.055)
                        mar = rng.gauss(0.62, 0.15)
                        blink = rng.randint(1, 3)
                        blink_rate = rng.gauss(7, 2)
                        nod = rng.gauss(0.38, 0.12)
                    values = (
                        max(0, ear), max(0, mar), blink, max(0, blink_rate),
                        max(0, nod), max(0, rng.gauss(0.12, 0.07)),
                        max(0, rng.gauss(0.09, 0.05))
                    )
                    moment = base + timedelta(days=day, seconds=label*100+i)
                    rows.append((
                        "synthetic_driver_001", moment.strftime("%Y-%m-%d %H:%M:%S"),
                        *values, label, "NORMAL" if label == 0 else "FATIGUE",
                        "general", "human_review"
                    ))
        conn.executemany("""
            INSERT INTO fatigue_data (
                user_id,time,ear,mar,blink,blink_rate_10s,nod_ratio,head_ratio,
                head_motion,label,label_name,user_type,label_source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
    except Exception:
        conn.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
    print(f"Created SYNTHETIC test database: {path}")
    print("Rows: 240 | NORMAL: 120 | FATIGUE: 120 | driver-days: 6")
    print("Do NOT use these metrics to assess real-world fatigue detection.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="fatigue_training_test.db")
    args = parser.parse_args()
    build(args.out)
