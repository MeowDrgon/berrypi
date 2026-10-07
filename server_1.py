from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
import os
import sqlite3
import json
import pandas as pd
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this-secret")

DB_NAME = "fatigue.db"
BASE_DIR = "database"
RULE_DIR = "rules"

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(RULE_DIR, exist_ok=True)

BIG_DATASET_TYPE = "general"
BIG_DATASET_FILES = {
    "general": os.path.join(BASE_DIR, "general_dataset.csv"),
    "small_eye": os.path.join(BASE_DIR, "small_eye_dataset.csv")
}

PERSONAL_RATIO = 20
BIG_DATA_RATIO = 80
BIG_DATA_MULTIPLIER = 4

LABEL_MAP = {
    0: "NORMAL",
    1: "YAWN",
    2: "EYE_CLOSE_OR_BLINK",
    3: "NOD",
    4: "SHAKE_HEAD",
    5: "LOOK_AWAY"
}

FEATURE_COLUMNS = [
    "EAR", "MAR", "Blink", "BlinkRate10s",
    "NodRatio", "HeadRatio", "HeadMotion"
]
REQUIRED_COLUMNS = FEATURE_COLUMNS + ["Label"]


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def add_column_if_not_exists(cursor, table_name, column_name, column_def):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
        )


def init_db():
    conn = get_db()
    cursor = conn.cursor()

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

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_data (
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
        user_type TEXT DEFAULT 'general',
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
    CREATE INDEX IF NOT EXISTS idx_fatigue_rules_user_id
    ON fatigue_rules(user_id)
    """)

    conn.commit()
    conn.close()
    print("[DB] SQLite initialized / migrated")


def login_required():
    return session.get("user_id")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user_id = (request.form.get("user_id") or "").strip()
        password = request.form.get("password") or ""

        if not user_id or not password:
            return render_template_string(AUTH_HTML, mode="register", error="請輸入帳號與密碼")
        if len(password) < 6:
            return render_template_string(AUTH_HTML, mode="register", error="密碼至少 6 碼")

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (user_id, user_type, password_hash) VALUES (?, 'general', ?)",
                (user_id, generate_password_hash(password))
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return render_template_string(AUTH_HTML, mode="register", error="帳號已存在")
        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template_string(AUTH_HTML, mode="register", error=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id = (request.form.get("user_id") or "").strip()
        password = request.form.get("password") or ""

        conn = get_db()
        row = conn.execute(
            "SELECT user_id, password_hash FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        conn.close()

        if row and row["password_hash"] and check_password_hash(row["password_hash"], password):
            session.clear()
            session["user_id"] = row["user_id"]
            return redirect(url_for("review_page"))

        return render_template_string(AUTH_HTML, mode="login", error="帳號或密碼錯誤")

    return render_template_string(AUTH_HTML, mode="login", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/review", methods=["GET"])
def review_page():
    user_id = login_required()
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    rows = conn.execute("""
        SELECT
            id, time, ear, mar, blink, blink_rate_10s,
            nod_ratio, head_ratio, head_motion,
            label, label_name,
            original_label, original_label_name, created_at
        FROM pending_data
        WHERE user_id = ?
          AND COALESCE(review_status, 'pending') = 'pending'
        ORDER BY id ASC
    """, (user_id,)).fetchall()
    conn.close()

    return render_template_string(
        REVIEW_HTML,
        user_id=user_id,
        rows=[dict(row) for row in rows]
    )


@app.route("/api/pending", methods=["GET"])
def pending_api():
    user_id = login_required()
    if not user_id:
        return jsonify({"status": "error", "msg": "login required"}), 401

    conn = get_db()
    rows = conn.execute("""
        SELECT *
        FROM pending_data
        WHERE user_id = ?
          AND COALESCE(review_status, 'pending') = 'pending'
        ORDER BY id ASC
    """, (user_id,)).fetchall()
    conn.close()

    return jsonify({
        "status": "success",
        "count": len(rows),
        "data": [dict(row) for row in rows]
    })


@app.route("/api/review/<int:pending_id>", methods=["POST"])
def review_pending(pending_id):
    user_id = login_required()
    if not user_id:
        return jsonify({"status": "error", "msg": "login required"}), 401

    data = request.get_json(silent=True) or {}
    decision = data.get("decision")
    if decision not in ("correct", "false_positive"):
        return jsonify({
            "status": "error",
            "msg": "decision must be correct or false_positive"
        }), 400

    conn = get_db()
    try:
        row = conn.execute("""
            SELECT *
            FROM pending_data
            WHERE id = ?
              AND user_id = ?
              AND COALESCE(review_status, 'pending') = 'pending'
        """, (pending_id, user_id)).fetchone()

        if row is None:
            return jsonify({
                "status": "error",
                "msg": "pending data not found or already reviewed"
            }), 404

        original_label = row["original_label"]
        if original_label is None:
            original_label = row["label"]

        original_name = row["original_label_name"] or row["label_name"]
        if not original_name:
            original_name = LABEL_MAP.get(original_label, "UNKNOWN")

        # 第一階段：
        # correct = 保留模型原始標籤
        # false_positive = 使用者確認不是疲勞，標記 NORMAL
        reviewed_label = int(original_label) if decision == "correct" else 0
        reviewed_name = LABEL_MAP.get(reviewed_label, "UNKNOWN")

        conn.execute("""
        INSERT INTO fatigue_data (
            user_id, time,
            ear, mar, blink, blink_rate_10s,
            nod_ratio, head_ratio, head_motion,
            label, label_name, user_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, row["time"],
            row["ear"], row["mar"], row["blink"], row["blink_rate_10s"],
            row["nod_ratio"], row["head_ratio"], row["head_motion"],
            reviewed_label, reviewed_name, row["user_type"] or "general"
        ))

        conn.execute("""
        UPDATE pending_data
        SET original_label = ?,
            original_label_name = ?,
            review_status = 'reviewed',
            reviewed_label = ?,
            reviewed_label_name = ?,
            reviewed_by = ?,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """, (
            original_label, original_name,
            reviewed_label, reviewed_name,
            user_id, pending_id, user_id
        ))

        conn.commit()

        return jsonify({
            "status": "success",
            "pending_id": pending_id,
            "decision": decision,
            "original_label": original_label,
            "original_label_name": original_name,
            "reviewed_label": reviewed_label,
            "reviewed_label_name": reviewed_name
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "msg": str(e)}), 500
    finally:
        conn.close()


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


def get_rule_path(user_id):
    return os.path.join(RULE_DIR, f"{user_id}_multiclass_rule.json")


def get_user_type(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT user_type FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return BIG_DATASET_TYPE
    return row["user_type"] if row["user_type"] in BIG_DATASET_FILES else BIG_DATASET_TYPE


def ensure_user(user_id, user_type=None):
    if user_type is None:
        user_type = BIG_DATASET_TYPE
    if user_type not in BIG_DATASET_FILES:
        user_type = BIG_DATASET_TYPE

    conn = get_db()
    conn.execute("""
    INSERT OR IGNORE INTO users (user_id, user_type)
    VALUES (?, ?)
    """, (user_id, user_type))
    conn.execute("""
    UPDATE users SET user_type = ? WHERE user_id = ?
    """, (user_type, user_id))
    conn.commit()
    conn.close()


def get_personal_df_from_db(user_id):
    conn = get_db()
    query = """
    SELECT
        time AS Time, ear AS EAR, mar AS MAR, blink AS Blink,
        blink_rate_10s AS BlinkRate10s, nod_ratio AS NodRatio,
        head_ratio AS HeadRatio, head_motion AS HeadMotion,
        label AS Label, label_name AS LabelName
    FROM fatigue_data WHERE user_id = ?
    """
    df = pd.read_sql_query(query, conn, params=(user_id,))
    conn.close()
    return df


def judge_by_rule(rule, data):
    try:
        ear = float(data.get("EAR", 0))
        mar = float(data.get("MAR", 0))
        blink_rate_10s = float(data.get("BlinkRate10s", 0))
        nod_ratio = float(data.get("NodRatio", 0))
        head_ratio = float(data.get("HeadRatio", 0))
        head_motion = float(data.get("HeadMotion", 0))
        rules = rule["rules"]

        if mar > rules["YAWN"]["YAWN_THRESHOLD"]:
            return 1, "YAWN"
        if (
            ear < rules["EYE_CLOSE_OR_BLINK"]["EAR_THRESHOLD"]
            or blink_rate_10s > rules["EYE_CLOSE_OR_BLINK"]["BLINK_RATE_THRESHOLD"]
        ):
            return 2, "EYE_CLOSE_OR_BLINK"
        if nod_ratio > rules["NOD"]["BASELINE_NOD"] + rules["NOD"]["NOD_DELTA"]:
            return 3, "NOD"
        if head_motion > rules["SHAKE_HEAD"]["SHAKE_THRESHOLD"]:
            return 4, "SHAKE_HEAD"
        if abs(head_ratio - rules["LOOK_AWAY"]["BASELINE_HEAD"]) > rules["LOOK_AWAY"]["HEAD_DELTA"]:
            return 5, "LOOK_AWAY"
        return 0, "NORMAL"
    except Exception as e:
        print("[JUDGE ERROR]", e)
        return -1, "ERROR"


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "msg": "Fatigue server is running",
        "version": "multiclass_rule_server_phase1_review"
    })


@app.route("/user_type/<user_id>", methods=["POST"])
def set_user_type(user_id):
    try:
        data = request.json or {}
        user_type = data.get("user_type", "general")
        if user_type not in BIG_DATASET_FILES:
            return jsonify({
                "status": "error",
                "msg": "user_type must be general or small_eye"
            }), 400
        ensure_user(user_id, user_type)
        return jsonify({
            "status": "success",
            "user_id": user_id,
            "user_type": user_type
        })
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route("/rule/<user_id>", methods=["GET"])
def get_rule(user_id):
    try:
        path = get_rule_path(user_id)
        if not os.path.exists(path):
            return jsonify({"status": "error", "msg": "no rule"}), 404
        with open(path, "r", encoding="utf-8") as f:
            rule = json.load(f)
        return jsonify({"status": "success", "rule": rule})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route("/latest_rule/<user_id>", methods=["GET"])
def latest_rule(user_id):
    path = get_rule_path(user_id)
    if not os.path.exists(path):
        return jsonify({"status": "error", "msg": "rule not found"}), 404
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/upload", methods=["POST"])
def upload_data():
    try:
        data = request.json or {}
        print("========== UPLOAD ==========")
        print(json.dumps(data, indent=4, ensure_ascii=False))

        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"status": "error", "msg": "user_id required"}), 400

        user_type = data.get("user_type", "general")
        ensure_user(user_id, user_type)

        try:
            original_label = int(data.get("Label"))
        except (TypeError, ValueError):
            original_label = 0

        original_label_name = data.get("LabelName") or LABEL_MAP.get(
            original_label, "UNKNOWN"
        )

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO pending_data (
            user_id, time,
            ear, mar, blink, blink_rate_10s,
            nod_ratio, head_ratio, head_motion,
            label, label_name,
            original_label, original_label_name,
            review_status, user_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            user_id, data.get("Time"),
            data.get("EAR"), data.get("MAR"), data.get("Blink"),
            data.get("BlinkRate10s"), data.get("NodRatio"),
            data.get("HeadRatio"), data.get("HeadMotion"),
            original_label, original_label_name,
            original_label, original_label_name, user_type
        ))
        pending_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "pending": True,
            "pending_id": pending_id
        })
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "msg": "server connected",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


AUTH_HTML = """
<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ '登入' if mode == 'login' else '建立帳號' }}</title>
<style>
body{font-family:Arial,sans-serif;max-width:460px;margin:60px auto;padding:20px;background:#f5f7fa}
.card{background:white;padding:28px;border-radius:14px;box-shadow:0 4px 20px #0001}
input,button{width:100%;box-sizing:border-box;padding:12px;margin:7px 0;font-size:16px}
button{cursor:pointer;border:0;border-radius:8px;background:#222;color:#fff}
a{display:inline-block;margin-top:12px}.error{color:#b00020}
</style></head><body><div class="card">
<h2>{{ '使用者登入' if mode == 'login' else '建立使用者帳號' }}</h2>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post">
<input name="user_id" placeholder="帳號" required>
<input name="password" type="password" placeholder="密碼（至少 6 碼）" required>
<button type="submit">{{ '登入' if mode == 'login' else '建立帳號' }}</button>
</form>
{% if mode == 'login' %}<a href="{{ url_for('register') }}">第一次使用？建立帳號</a>
{% else %}<a href="{{ url_for('login') }}">返回登入</a>{% endif %}
</div></body></html>
"""

REVIEW_HTML = """
<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>待審核疲勞資料</title>
<style>
body{font-family:Arial,sans-serif;margin:0;background:#f5f7fa;color:#222}
header{background:#222;color:#fff;padding:16px 24px;display:flex;justify-content:space-between}
main{max-width:1100px;margin:24px auto;padding:0 16px}
.card{background:#fff;border-radius:12px;padding:18px;margin-bottom:14px;box-shadow:0 2px 10px #0001}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:12px 0}
.metric{background:#f1f3f5;padding:10px;border-radius:8px}
button{padding:10px 18px;border:0;border-radius:8px;cursor:pointer;margin-right:8px}
.ok{background:#198754;color:#fff}.bad{background:#dc3545;color:#fff}
.muted{color:#666}.empty{padding:40px;text-align:center;background:#fff;border-radius:12px}
</style></head><body>
<header><div>疲勞資料審核｜{{ user_id }}</div>
<a style="color:#fff" href="{{ url_for('logout') }}">登出</a></header>
<main><h2>待審核資料（{{ rows|length }} 筆）</h2>
<p class="muted">「正確」保留模型原始標籤；「誤判」在第一階段視為 NORMAL，並保留原始模型標籤供後續分析。</p>
{% if not rows %}<div class="empty">目前沒有待審核資料。</div>{% endif %}
{% for r in rows %}
<div class="card" id="item-{{ r.id }}">
<strong>#{{ r.id }}｜{{ r.time or r.created_at }}</strong>
<p>模型判定：<b>{{ r.original_label_name or r.label_name or 'UNKNOWN' }}</b>
（{{ r.original_label if r.original_label is not none else r.label }}）</p>
<div class="grid">
<div class="metric">EAR<br><b>{{ r.ear }}</b></div>
<div class="metric">MAR<br><b>{{ r.mar }}</b></div>
<div class="metric">Blink<br><b>{{ r.blink }}</b></div>
<div class="metric">BlinkRate10s<br><b>{{ r.blink_rate_10s }}</b></div>
<div class="metric">NodRatio<br><b>{{ r.nod_ratio }}</b></div>
<div class="metric">HeadRatio<br><b>{{ r.head_ratio }}</b></div>
<div class="metric">HeadMotion<br><b>{{ r.head_motion }}</b></div>
</div>
<button class="ok" onclick="review({{ r.id }}, 'correct')">✓ 正確</button>
<button class="bad" onclick="review({{ r.id }}, 'false_positive')">✕ 誤判</button>
</div>
{% endfor %}</main>
<script>
async function review(id, decision){
  if(!confirm(decision === 'correct' ? '確認模型判定正確？' : '確認這筆是誤判？')) return;
  const res = await fetch('/api/review/' + id, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({decision})
  });
  const data = await res.json();
  if(!res.ok){ alert(data.msg || '審核失敗'); return; }
  const el = document.getElementById('item-' + id);
  if(el) el.remove();
}
</script></body></html>
"""


if __name__ == "__main__":
    init_db()
    get_big_dataset_path("general")
    get_big_dataset_path("small_eye")
    app.run(host="0.0.0.0", port=5000, debug=True)
