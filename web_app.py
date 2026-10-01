from flask import request, jsonify, render_template
from datetime import datetime
import os, hashlib, csv

# Import the existing project server so both services use the same fatigue.db
from server_1 import app, get_db, init_db, get_big_dataset_path

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
os.makedirs(TEMPLATE_DIR, exist_ok=True)


def web_db_setup():
    init_db()
    conn = get_db(); cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS web_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
        nickname TEXT NOT NULL, email TEXT, phone TEXT, vehicle_type TEXT,
        role TEXT DEFAULT 'user', status TEXT DEFAULT '正常',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS pending_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, time TEXT,
        ear REAL, mar REAL, blink INTEGER, blink_rate_10s REAL,
        nod_ratio REAL, head_ratio REAL, head_motion REAL,
        label INTEGER, label_name TEXT, user_type TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cols = {r[1] for r in cur.execute('PRAGMA table_info(pending_data)').fetchall()}
    for name, definition in [('review_status', "TEXT DEFAULT 'pending'"), ('reviewed_by','TEXT'), ('reviewed_at','TEXT'), ('review_label','INTEGER')]:
        if name not in cols: cur.execute(f'ALTER TABLE pending_data ADD COLUMN {name} {definition}')
    password_hash = hashlib.sha256('222'.encode('utf-8')).hexdigest()
    cur.execute('''INSERT OR IGNORE INTO web_users
        (account,password_hash,nickname,email,phone,vehicle_type,role,status)
        VALUES (?,?,?,?,?,?,?,?)''', ('111',password_hash,'測試使用者','','','一般汽車','user','正常'))
    conn.commit(); conn.close()


def hash_password(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()

def user_payload(row):
    return {'user_id':row['id'],'account':row['account'],'nickname':row['nickname'],'email':row['email'] or '',
            'phone':row['phone'] or '','vehicle_type':row['vehicle_type'] or '','role':row['role'],'status':row['status']}

def pending_row_to_dict(row):
    return {'id':row['id'],'user_id':row['user_id'],'time':row['time'],'EAR':row['ear'],'MAR':row['mar'],'Blink':row['blink'],
            'BlinkRate10s':row['blink_rate_10s'],'NodRatio':row['nod_ratio'],'HeadRatio':row['head_ratio'],'HeadMotion':row['head_motion'],
            'label':row['label'],'label_name':row['label_name'],'user_type':row['user_type'],'review_status':row['review_status']}

def append_big_dataset(data,label,label_name):
    dataset_type = data['user_type'] if data['user_type'] in ('general','small_eye') else 'general'
    path=get_big_dataset_path(dataset_type)
    with open(path,'a',newline='',encoding='utf-8-sig') as f:
        csv.writer(f).writerow([data['time'],data['EAR'],data['MAR'],data['Blink'],data['BlinkRate10s'],data['NodRatio'],data['HeadRatio'],data['HeadMotion'],label,label_name])

@app.route('/web')
def web_home(): return render_template('fatigue_dashboard.html')

@app.route('/web/api/login',methods=['POST'])
def web_login():
    data=request.get_json(silent=True) or {}; account=str(data.get('account','')).strip(); password=str(data.get('password',''))
    conn=get_db(); cur=conn.cursor(); cur.execute('SELECT * FROM web_users WHERE account=?',(account,)); row=cur.fetchone(); conn.close()
    if row is None or row['password_hash']!=hash_password(password): return jsonify({'error':'帳號或密碼錯誤'}),401
    if row['status']=='停權': return jsonify({'error':'此帳號目前已停權'}),403
    return jsonify(user_payload(row))

@app.route('/web/api/dashboard/<user_id>')
def web_dashboard(user_id):
    conn=get_db(); cur=conn.cursor()
    cur.execute('SELECT COUNT(*) FROM pending_data WHERE review_status="pending" AND user_id=?',(str(user_id),)); pending=cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM fatigue_data WHERE user_id=? AND label!=0',(str(user_id),)); fatigue=cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM fatigue_data WHERE user_id=?',(str(user_id),)); total=cur.fetchone()[0]
    cur.execute('SELECT MAX(created_at) FROM fatigue_data WHERE user_id=?',(str(user_id),)); last=cur.fetchone()[0]
    conn.close(); return jsonify({'pending':pending,'fatigue_events':fatigue,'total_records':total,'last_record':last})

@app.route('/web/api/reviews')
def web_reviews():
    user_id=request.args.get('user_id'); conn=get_db(); cur=conn.cursor()
    if user_id: cur.execute('SELECT * FROM pending_data WHERE review_status="pending" AND user_id=? ORDER BY id DESC',(user_id,))
    else: cur.execute('SELECT * FROM pending_data WHERE review_status="pending" ORDER BY id DESC')
    rows=cur.fetchall(); conn.close(); return jsonify([pending_row_to_dict(r) for r in rows])

@app.route('/web/api/review/<int:review_id>',methods=['POST'])
def web_review(review_id):
    data=request.get_json(silent=True) or {}; decision=data.get('decision'); reviewer=str(data.get('reviewer','111'))
    if decision not in ('fatigue','normal'): return jsonify({'error':'decision 必須是 fatigue 或 normal'}),400
    conn=get_db(); cur=conn.cursor(); cur.execute('SELECT * FROM pending_data WHERE id=?',(review_id,)); row=cur.fetchone()
    if row is None: conn.close(); return jsonify({'error':'找不到待審核資料'}),404
    label=int(row['label']) if decision=='fatigue' else 0; label_name=row['label_name'] if decision=='fatigue' else 'NORMAL'
    cur.execute('''UPDATE pending_data SET review_status=?,reviewed_by=?,reviewed_at=?,review_label=? WHERE id=?''',
                ('approved_fatigue' if decision=='fatigue' else 'rejected_normal',reviewer,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),label,review_id))
    if decision=='fatigue':
        cur.execute('''INSERT INTO fatigue_data (user_id,time,ear,mar,blink,blink_rate_10s,nod_ratio,head_ratio,head_motion,label,label_name,user_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (row['user_id'],row['time'],row['ear'],row['mar'],row['blink'],row['blink_rate_10s'],row['nod_ratio'],row['head_ratio'],row['head_motion'],label,label_name,row['user_type']))
        append_big_dataset(pending_row_to_dict(row),label,label_name)
    conn.commit(); conn.close(); return jsonify({'status':'success','decision':decision})

@app.route('/web/api/driving/<user_id>')
def web_driving(user_id):
    conn=get_db(); cur=conn.cursor(); cur.execute('SELECT label_name,COUNT(*) AS count FROM fatigue_data WHERE user_id=? GROUP BY label_name ORDER BY count DESC',(str(user_id),))
    distribution=[{'label':r['label_name'] or 'UNKNOWN','count':r['count']} for r in cur.fetchall()]
    cur.execute('SELECT COUNT(*) FROM fatigue_data WHERE user_id=? AND label=0',(str(user_id),)); normal=cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM fatigue_data WHERE user_id=?',(str(user_id),)); total=cur.fetchone()[0]
    conn.close(); return jsonify({'normal':normal,'total':total,'distribution':distribution})

@app.route('/web/api/profile/<user_id>')
def web_profile(user_id):
    conn=get_db(); cur=conn.cursor(); cur.execute('SELECT * FROM web_users WHERE account=? OR id=?',(str(user_id),user_id if str(user_id).isdigit() else -1)); row=cur.fetchone(); conn.close()
    if row is None: return jsonify({'error':'找不到使用者'}),404
    return jsonify(user_payload(row))

@app.route('/web/api/admin/users')
def web_admin_users():
    conn=get_db(); cur=conn.cursor(); cur.execute('SELECT id,account,nickname,email,phone,vehicle_type,role,status,created_at FROM web_users ORDER BY id'); rows=[dict(r) for r in cur.fetchall()]; conn.close(); return jsonify(rows)

@app.route('/web/api/admin/user/<int:user_id>/ban',methods=['POST'])
def web_admin_ban(user_id):
    conn=get_db(); cur=conn.cursor(); cur.execute('UPDATE web_users SET status="停權" WHERE id=?',(user_id,)); conn.commit(); conn.close(); return jsonify({'status':'success'})

@app.route('/web/api/admin/pending')
def web_admin_pending():
    conn=get_db(); cur=conn.cursor(); cur.execute('SELECT * FROM pending_data WHERE review_status="pending" ORDER BY id DESC'); rows=[pending_row_to_dict(r) for r in cur.fetchall()]; conn.close(); return jsonify(rows)


def upload_to_pending():
    """Replacement for server_1 /upload: live Pi rows enter review queue first."""
    try:
        data=request.get_json(silent=True) or {}; user_id=str(data.get('user_id','')).strip()
        if not user_id: return jsonify({'status':'error','msg':'missing user_id'}),400
        user_type=data.get('user_type','general')
        if user_type not in ('general','small_eye'): user_type='general'
        conn=get_db(); cur=conn.cursor(); cols={r[1] for r in cur.execute('PRAGMA table_info(pending_data)').fetchall()}
        if 'review_status' not in cols:
            cur.execute("ALTER TABLE pending_data ADD COLUMN review_status TEXT DEFAULT 'pending'")
            cur.execute('ALTER TABLE pending_data ADD COLUMN reviewed_by TEXT'); cur.execute('ALTER TABLE pending_data ADD COLUMN reviewed_at TEXT'); cur.execute('ALTER TABLE pending_data ADD COLUMN review_label INTEGER')
        cur.execute('''INSERT INTO pending_data (user_id,time,ear,mar,blink,blink_rate_10s,nod_ratio,head_ratio,head_motion,label,label_name,user_type,review_status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (user_id,data.get('Time'),data.get('EAR'),data.get('MAR'),data.get('Blink'),data.get('BlinkRate10s'),data.get('NodRatio'),data.get('HeadRatio'),data.get('HeadMotion'),data.get('Label',0),data.get('LabelName','NORMAL'),user_type,'pending'))
        conn.commit(); row_id=cur.lastrowid; conn.close(); print('[PENDING UPLOAD]',user_id,row_id)
        return jsonify({'status':'success','pending_id':row_id})
    except Exception as e: return jsonify({'status':'error','msg':str(e)}),500

# Override the existing /upload view in this web-enabled process so live Raspberry Pi rows enter review first.
app.view_functions['upload_data']=upload_to_pending

if __name__=='__main__':
    web_db_setup(); get_big_dataset_path('general'); get_big_dataset_path('small_eye'); app.run(host='0.0.0.0',port=5000,debug=True)
