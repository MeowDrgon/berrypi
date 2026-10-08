"""Review queue policy. Run expiry locally or on the receiving server; never from a browser."""
from datetime import datetime, timedelta, timezone
import sqlite3

FATIGUE_CODES = {1, 2, 3}
UNKNOWN_CODES = {-1, 6}
FEATURES = ("ear", "mar", "blink", "blink_rate_10s", "nod_ratio", "head_ratio", "head_motion")


def category(label):
    try:
        label = int(label)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if label == 0:
        return "NORMAL"
    if label in FATIGUE_CODES:
        return "FATIGUE"
    return "UNKNOWN"  # LOOK_AWAY and SHAKE_HEAD are not fatigue


def priority(label, near_threshold=False, historically_wrong=False):
    if category(label) == "UNKNOWN" or historically_wrong:
        return "high"
    if category(label) == "FATIGUE" or near_threshold:
        return "medium"
    return "low"


def migrate(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(pending_data)")}
    for name, definition in (
        ("priority", "TEXT DEFAULT 'low'"),
        ("event_group", "TEXT"),
        ("expires_at", "TEXT"),
        ("archived_at", "TEXT"),
        ("label_source", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE pending_data ADD COLUMN {name} {definition}")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(fatigue_data)")}
    for name, definition in (
        ("original_label", "INTEGER"),
        ("reviewed_label", "INTEGER"),
        ("label_source", "TEXT DEFAULT 'legacy'"),
        ("pending_id", "INTEGER"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE fatigue_data ADD COLUMN {name} {definition}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fatigue_pending ON fatigue_data(pending_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_priority ON pending_data(review_status,priority,created_at)")
    conn.commit()


def transfer(conn, row, label, source):
    """Copy a reviewed or expired sample once; preserve provenance."""
    if label not in (0, 1):
        raise ValueError("Only NORMAL/FATIGUE training labels allowed")
    fields = ", ".join(FEATURES)
    placeholders = ", ".join("?" for _ in FEATURES)
    original = row["original_label"] if row["original_label"] is not None else row["label"]
    conn.execute(f"""
        INSERT OR IGNORE INTO fatigue_data
        (user_id,time,{fields},label,label_name,user_type,original_label,reviewed_label,label_source,pending_id)
        VALUES (?,?,{placeholders},?,?,?,?,?,?,?)
    """, (row["user_id"], row["time"], *(row[k] for k in FEATURES),
          label, "NORMAL" if label == 0 else "FATIGUE",
          row["user_type"], original, label, source, row["id"]))


def expire(conn, now=None):
    """NORMAL/FATIGUE: 7 days -> auto label; UNKNOWN: archive at 7, delete at 30."""
    now = now or datetime.now(timezone.utc)
    seven = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    thirty = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    moved = archived = deleted = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute("""
            SELECT * FROM pending_data
            WHERE COALESCE(review_status,'pending')='pending'
              AND created_at <= ?
        """, (seven,)).fetchall()
        for row in rows:
            kind = category(row["original_label"] if row["original_label"] is not None else row["label"])
            if kind == "UNKNOWN":
                conn.execute("UPDATE pending_data SET review_status='archived', archived_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
                archived += 1
            else:
                transfer(conn, row, 0 if kind == "NORMAL" else 1, "auto_expired")
                conn.execute("UPDATE pending_data SET review_status='auto_expired',label_source='auto_expired' WHERE id=?", (row["id"],))
                moved += 1
        result = conn.execute("""
            DELETE FROM pending_data
            WHERE review_status='archived' AND created_at <= ?
        """, (thirty,))
        deleted = result.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"auto_labeled": moved, "archived": archived, "deleted": deleted}
