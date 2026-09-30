import dlib
import numpy as np
import csv
import os
import time
import requests
import json
import subprocess
import threading
import pygame
import pygame.camera
from collections import deque

# ==========================================
# AI 疲勞駕駛 Dataset 收集系統
# Windows 無 OpenCV / pygame 版
# 多狀態按鈕標記版本
# ==========================================
# 狀態按鍵：
# 0 = NORMAL 正常
# 1 = YAWN 打哈欠
# 2 = EYE_CLOSE_OR_BLINK 眼睛異常：閉眼 / 快速眨眼 / 眼部不穩
# 3 = NOD 點頭 / 低頭
# 4 = SHAKE_HEAD 搖頭 / 左右晃頭
# 5 = LOOK_AWAY 眼神飄移 / 視線偏移 / 注意力偏移
# Q = 離開
# ==========================================

# ==========================================
# 基本設定
# ==========================================
SERVER_URL = "http://172.20.10.2:5000"
TARGET_WIFI = "喵龍der手機"
RULE_FILE = "personal_rule.json"
LOCAL_DATA_DIR = "local_data"
os.makedirs(LOCAL_DATA_DIR, exist_ok=True)

new_rule = None
sync_running = False
sync_msg = "IDLE"

CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240
DISPLAY_FPS = 30
NO_FACE_LIMIT = 20

# 平滑參數，降低眼鏡反光造成的 landmark 抖動
SMOOTH_WINDOW = 5
EAR_JUMP_LIMIT = 0.12
MAR_JUMP_LIMIT = 0.20

# 快速眨眼統計窗口
BLINK_WINDOW_SECONDS = 10
BLINK_EAR_THRESHOLD = 0.21

# ==========================================
# Label 對照表
# ==========================================
LABEL_MAP = {
    0: "NORMAL",
    1: "YAWN",
    2: "EYE_CLOSE_OR_BLINK",
    3: "NOD",
    4: "SHAKE_HEAD",
    5: "LOOK_AWAY"
}
# ==========================================
# 人群類型
# G = 一般人
# F = 乾眼症
# ==========================================
USER_TYPE_MAP = {
    "general": "GENERAL",
    "small_eye": "SMALL_EYE"
}

KEY_TO_USER_TYPE = {
    pygame.K_g: "general",
    pygame.K_s: "small_eye"
}
KEY_TO_LABEL = {
    pygame.K_0: 0,
    pygame.K_1: 1,
    pygame.K_2: 2,
    pygame.K_3: 3,
    pygame.K_4: 4,
    pygame.K_5: 5,
}

# ==========================================
# dlib 68 點索引
# ==========================================
RIGHT_EYE = [36, 37, 38, 39, 40, 41]
LEFT_EYE = [42, 43, 44, 45, 46, 47]
MOUTH = [60, 61, 62, 63, 64, 65, 66, 67]
CHIN = 8
NOSE_TIP = 30
FACE_LEFT = 0
FACE_RIGHT = 16
BROW_CENTER = 27

# ==========================================
# 使用者資料
# ==========================================
user_name = input("Enter User Name: ")
DATASET_FILE = os.path.join(LOCAL_DATA_DIR, f"{user_name}_multi_state.csv")

# ==========================================
# 建立 CSV
# Label 是數字，LabelName 是文字，之後 AI 訓練可直接用 Label
# ==========================================
if not os.path.exists(DATASET_FILE):
    with open(DATASET_FILE, mode="w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "Time",
            "EAR",
            "MAR",
            "Blink",
            "BlinkRate10s",
            "NodRatio",
            "HeadRatio",
            "HeadMotion",
            "Label",
            "LabelName",
            "UserType"
        ])

# ==========================================
# 基本工具
# ==========================================
def euclidean(p1, p2):
    return np.linalg.norm(np.array(p1) - np.array(p2))


def calculate_ear(eye):
    v1 = euclidean(eye[1], eye[5])
    v2 = euclidean(eye[2], eye[4])
    h = euclidean(eye[0], eye[3])
    if h == 0:
        return 0
    return (v1 + v2) / (2.0 * h)


def calculate_mar(mouth):
    v1 = euclidean(mouth[1], mouth[7])
    v2 = euclidean(mouth[2], mouth[6])
    v3 = euclidean(mouth[3], mouth[5])
    h = euclidean(mouth[0], mouth[4])
    if h == 0:
        return 0
    return (v1 + v2 + v3) / (3.0 * h)


def rgb_to_gray(frame_rgb):
    gray = (
        0.299 * frame_rgb[:, :, 0] +
        0.587 * frame_rgb[:, :, 1] +
        0.114 * frame_rgb[:, :, 2]
    )
    return gray.astype(np.uint8)


def normalize_gray(gray):
    # 無 OpenCV 版本的簡單對比拉伸，降低光線和眼鏡反光造成的影響
    low = np.percentile(gray, 5)
    high = np.percentile(gray, 95)
    if high - low < 1:
        return gray.astype(np.uint8)
    out = (gray.astype(np.float32) - low) * 255.0 / (high - low)
    out = np.clip(out, 0, 255)
    return out.astype(np.uint8)


def median_smooth(queue, value):
    queue.append(float(value))
    return float(np.median(queue))


def robust_ear(left_ear, right_ear, prev_ear=None):
    # 戴眼鏡時可能有一眼被鏡框或反光影響，所以左右眼先做合理性過濾
    valid = []
    for v in [left_ear, right_ear]:
        if 0.05 <= v <= 0.45:
            valid.append(v)

    if len(valid) == 0:
        return prev_ear if prev_ear is not None else (left_ear + right_ear) / 2.0

    ear = float(np.median(valid))

    if prev_ear is not None and abs(ear - prev_ear) > EAR_JUMP_LIMIT:
        # 瞬間跳太大，通常是眼鏡反光或 landmark 抖動，採用比較保守的過渡值
        ear = prev_ear * 0.7 + ear * 0.3

    return ear


def robust_value(value, prev_value, jump_limit):
    if prev_value is None:
        return value
    if abs(value - prev_value) > jump_limit:
        return prev_value * 0.7 + value * 0.3
    return value

def rule_sync_worker():

    global new_rule
    global sync_running
    global sync_msg

    while True:

        sync_running = True

        try:

            rule = load_rule_auto(
                user_name,
                SERVER_URL,
                TARGET_WIFI
            )

            if rule is not None:

                new_rule = rule
                sync_msg = "UPDATED"

            else:

                sync_msg = "NO RULE"

        except Exception as e:

            sync_msg = str(e)

        sync_running = False

        time.sleep(60)
# ==========================================
# rule.json
# ==========================================
def load_local_rule():

    default_rule = {
        "EAR_THRESHOLD": 0.21,
        "YAWN_THRESHOLD": 0.35,
        "BASELINE_NOD": None,
        "NOD_DELTA": 0.05,
        "BASELINE_HEAD": None,
        "HEAD_DELTA": 0.15
    }

    if not os.path.exists(RULE_FILE):
        return default_rule

    with open(RULE_FILE, "r", encoding="utf-8") as f:
        rule = json.load(f)

    if "rules" in rule:

        rules = rule["rules"]

        if "YAWN" in rules:
            default_rule["YAWN_THRESHOLD"] = rules["YAWN"]["YAWN_THRESHOLD"]

        if "EYE_CLOSE_OR_BLINK" in rules:
            default_rule["EAR_THRESHOLD"] = rules["EYE_CLOSE_OR_BLINK"]["EAR_THRESHOLD"]

        if "NOD" in rules:
            default_rule["BASELINE_NOD"] = rules["NOD"]["BASELINE_NOD"]
            default_rule["NOD_DELTA"] = rules["NOD"]["NOD_DELTA"]

        if "LOOK_AWAY" in rules:
            default_rule["BASELINE_HEAD"] = rules["LOOK_AWAY"]["BASELINE_HEAD"]
            default_rule["HEAD_DELTA"] = rules["LOOK_AWAY"]["HEAD_DELTA"]

    return default_rule


def save_local_rule(rule):
    try:
        with open(RULE_FILE, "w", encoding="utf-8") as f:
            json.dump(rule, f, indent=4, ensure_ascii=False)
        print("[RULE SAVED]", rule)
    except Exception as e:
        print("[RULE SAVE ERROR]", e)

# ==========================================
# Windows Wi-Fi 偵測，修正版：避免中文 SSID 亂碼
# ==========================================
def get_current_wifi():
    try:
        raw = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"]
        )

        for enc in ["utf-8", "cp950", "big5", "mbcs"]:
            try:
                result = raw.decode(enc, errors="ignore")
            except Exception:
                continue

            for line in result.splitlines():
                line = line.strip()

                if line.startswith("SSID") and not line.startswith("BSSID"):
                    parts = line.split(":", 1)

                    if len(parts) == 2:
                        ssid = parts[1].strip()

                        if ssid:
                            return ssid

        return None

    except Exception as e:
        print("[WIFI ERROR]", repr(e))
        return None


def is_target_wifi():
    current_wifi = get_current_wifi()
    print("[CURRENT WIFI]", current_wifi)
    return current_wifi == TARGET_WIFI

# ==========================================
# 檢查伺服器是否連得上
# ==========================================
def check_server_connection():
    try:
        response = requests.get(
            SERVER_URL + "/ping",
            timeout=2
        )

        if response.status_code == 200:
            result = response.json()

            if result.get("status") == "ok":
                print("[SERVER] connected")
                return True

        print("[SERVER] ping failed")
        return False

    except Exception as e:
        print("[SERVER ERROR]", repr(e))
        return False
    
def load_rule_auto(
    user_name,
    server_url,
    target_wifi
):

    try:

        if not is_target_wifi():
            return None

        response = requests.get(
            f"{server_url}/rule/{user_name}",
            timeout=5
        )

        if response.status_code != 200:
            return None

        result = response.json()

        if result.get("status") != "success":
            return None

        rule = result.get("rule")

        if rule:

            save_local_rule(rule)

            print("[RULE SYNC]")
            print(rule)

            return rule

        return None

    except Exception as e:

        print("[RULE DOWNLOAD ERROR]", e)

        return None
# ==========================================
# 每秒只上傳一筆資料給伺服器
# 不再傳整份 CSV
# ==========================================
def upload_one_row_to_server(
    user_id,
    user_type,
    ear,
    mar,
    blink_count,
    blink_rate_10s,
    nod_ratio,
    h_ratio,
    head_motion,
    label,
    label_name
):
    try:
        data = {
            "user_id": user_id,
            "user_type": user_type,

            "Time": time.strftime("%Y-%m-%d %H:%M:%S"),

            "EAR": round(ear, 3),
            "MAR": round(mar, 3),
            "Blink": int(blink_count),
            "BlinkRate10s": int(blink_rate_10s),

            "NodRatio": round(nod_ratio, 3),
            "HeadRatio": round(h_ratio, 3),
            "HeadMotion": round(head_motion, 3),

            "Label": int(label),
            "LabelName": label_name
        }

        response = requests.post(
            SERVER_URL + "/upload",
            json=data,
            timeout=2
        )
        print(response.status_code)
        print(response.text)
        return response.json()

    except Exception as e:
        print("[UPLOAD ERROR]", repr(e))
        return None

# ==========================================
# pygame 繪圖
# ==========================================
def draw_text(screen, font, text, x, y, color=(255, 255, 255)):
    img = font.render(text, True, color)
    screen.blit(img, (x, y))


def draw_point(screen, point, color=(0, 255, 0), radius=2):
    pygame.draw.circle(screen, color, (int(point[0]), int(point[1])), radius)


def draw_rect(screen, left, top, right, bottom, color=(0, 0, 255), width=2):
    rect = pygame.Rect(int(left), int(top), int(right - left), int(bottom - top))
    pygame.draw.rect(screen, color, rect, width)


def pick_largest_face(faces):
    return max(faces, key=lambda r: r.width() * r.height())

# ==========================================
# 主程式
# ==========================================
def main():
    model_path = "shape_predictor_68_face_landmarks.dat"
    if not os.path.exists(model_path):
        print("找不到 shape_predictor_68_face_landmarks.dat")
        print("請把模型檔放在跟這個 Python 檔同一個資料夾")
        return

    detector = dlib.get_frontal_face_detector()
    predictor = dlib.shape_predictor(model_path)

    pygame.init()
    pygame.camera.init()

    cameras = pygame.camera.list_cameras()
    if len(cameras) == 0:
        print("找不到攝影機")
        return

    print("[CAMERA LIST]", cameras)
    print("[USING CAMERA]", cameras[0])

    cam = pygame.camera.Camera(cameras[0], (CAMERA_WIDTH, CAMERA_HEIGHT), "RGB")
    cam.start()

    screen = pygame.display.set_mode((CAMERA_WIDTH, CAMERA_HEIGHT))
    pygame.display.set_caption("Dlib Multi-State Dataset Capture - No OpenCV")

    font = pygame.font.SysFont("Arial", 18)
    big_font = pygame.font.SysFont("Arial", 26)
    clock = pygame.time.Clock()

    blink_count = 0
    yawn_count = 0
    is_blinking = False
    was_yawning = False
    blink_times = deque()

    eye_closed_start = None
    yawn_start = None
    nod_start = None
    distract_start = None

    eye_alert = False
    yawn_alert = False
    nod_alert = False
    distract_alert = False

    EYE_CLOSED_SECONDS = 0.8
    YAWN_SECONDS = 0.8
    NOD_SECONDS = 0.8
    DISTRACT_SECONDS = 2.0

    rule = load_local_rule()
    EAR_THRESHOLD = rule["EAR_THRESHOLD"]
    YAWN_THRESHOLD = rule["YAWN_THRESHOLD"]
    NOD_DELTA = rule["NOD_DELTA"]
    HEAD_DELTA = rule["HEAD_DELTA"]

    print("========== Current Rule ==========")
    print(f"EAR_THRESHOLD  = {EAR_THRESHOLD}")
    print(f"YAWN_THRESHOLD = {YAWN_THRESHOLD}")
    print(f"NOD_DELTA      = {NOD_DELTA}")
    print(f"HEAD_DELTA     = {HEAD_DELTA}")
    print("==================================")

    calibration_start = time.time()
    calibration_ears = []
    calibration_mars = []
    calibration_nods = []
    calibration_heads = []
    calibrated = False

    baseline_ear = 0
    baseline_mar = 0
    baseline_nod = 0
    baseline_head = 0

    current_label = 0
    current_label_name = LABEL_MAP[current_label]
    # 目前人群類型，預設一般人
    current_user_type = "general"

    last_save_time = time.time()
    last_sync_time = 0
    prev_time = time.time()
    fps = 0

    no_face_count = 0
    last_face = None
    last_points = None

    ear_queue = deque(maxlen=SMOOTH_WINDOW)
    mar_queue = deque(maxlen=SMOOTH_WINDOW)
    nod_queue = deque(maxlen=SMOOTH_WINDOW)
    head_queue = deque(maxlen=SMOOTH_WINDOW)
    head_motion_queue = deque(maxlen=SMOOTH_WINDOW)

    prev_ear = None
    prev_mar = None
    prev_head = None

    running = True
    threading.Thread(
        target=rule_sync_worker,
        daemon=True
    ).start()
    print("======================================")
    print("多狀態資料收集啟動：Windows / No OpenCV / pygame")
    print("0 / N = NORMAL")
    print("1 / Y = YAWN 打哈欠")
    print("2 / E/B/C = EYE_CLOSE_OR_BLINK 眼睛異常")
    print("3 / D = NOD 點頭 / 低頭")
    print("4 / S = SHAKE_HEAD 搖頭 / 左右晃頭")
    print("5 / L = LOOK_AWAY 眼神飄移 / 視線偏移")
    print("Q = QUIT")
    print("資料會存到：", DATASET_FILE)
    print("======================================")

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:

                # 切換疲勞狀態 Label
                if event.key in KEY_TO_LABEL:
                    current_label = KEY_TO_LABEL[event.key]
                    current_label_name = LABEL_MAP[current_label]
                    print(f"[LABEL] {current_label} = {current_label_name}")

                # 切換人群類型 user_type
                elif event.key in KEY_TO_USER_TYPE:
                    current_user_type = KEY_TO_USER_TYPE[event.key]
                    print(f"[USER TYPE] {current_user_type}")

                elif event.key == pygame.K_q:
                    print("[INFO] Quit")
                    running = False

       
        global new_rule
        if new_rule is not None:
            
            rules = new_rule.get("rules", {})

            if "YAWN" in rules:
                YAWN_THRESHOLD = rules["YAWN"]["YAWN_THRESHOLD"]

            if "EYE_CLOSE_OR_BLINK" in rules:
                EAR_THRESHOLD = rules["EYE_CLOSE_OR_BLINK"]["EAR_THRESHOLD"]

            if "NOD" in rules:
                baseline_nod = rules["NOD"]["BASELINE_NOD"]
                NOD_DELTA = rules["NOD"]["NOD_DELTA"]

            if "LOOK_AWAY" in rules:
                baseline_head = rules["LOOK_AWAY"]["BASELINE_HEAD"]
                HEAD_DELTA = rules["LOOK_AWAY"]["HEAD_DELTA"]

            print("[RULE UPDATED]")
            # 最後才清掉
            new_rule = None

        if not cam.query_image():
            clock.tick(DISPLAY_FPS)
            continue

        frame_surface = cam.get_image()
        frame_surface = pygame.transform.scale(frame_surface, (CAMERA_WIDTH, CAMERA_HEIGHT))
        frame_surface = pygame.transform.flip(frame_surface, True, False)
        screen.blit(frame_surface, (0, 0))

        arr = pygame.surfarray.array3d(frame_surface)
        frame_rgb = np.transpose(arr, (1, 0, 2)).astype(np.uint8)
        gray = normalize_gray(rgb_to_gray(frame_rgb))

        faces = detector(gray, 1)

        face = None
        all_points = None
        using_cached_face = False

        if len(faces) > 0:
            no_face_count = 0
            face = pick_largest_face(faces)
            last_face = face

            landmarks = predictor(gray, face)
            all_points = []
            for i in range(68):
                x = landmarks.part(i).x
                y = landmarks.part(i).y
                all_points.append((x, y))
            last_points = all_points
        else:
            no_face_count += 1
            if no_face_count < NO_FACE_LIMIT and last_face is not None and last_points is not None:
                face = last_face
                all_points = last_points
                using_cached_face = True
            else:
                face = None
                all_points = None
                last_face = None
                last_points = None

        if face is not None and all_points is not None:
            for point in all_points:
                draw_point(screen, point)

            draw_rect(screen, face.left(), face.top(), face.right(), face.bottom(), color=(0, 0, 255), width=2)

            if using_cached_face:
                draw_text(screen, font, "Face cached", 500, 25, color=(255, 255, 0))
            else:
                draw_text(screen, font, "Face detected", 500, 25, color=(0, 255, 0))

            left_ear = calculate_ear([all_points[i] for i in LEFT_EYE])
            right_ear = calculate_ear([all_points[i] for i in RIGHT_EYE])
            raw_ear = robust_ear(left_ear, right_ear, prev_ear)
            raw_ear = robust_value(raw_ear, prev_ear, EAR_JUMP_LIMIT)
            ear = median_smooth(ear_queue, raw_ear)
            prev_ear = ear

            raw_mar = calculate_mar([all_points[i] for i in MOUTH])
            raw_mar = robust_value(raw_mar, prev_mar, MAR_JUMP_LIMIT)
            mar = median_smooth(mar_queue, raw_mar)
            prev_mar = mar

            face_h = euclidean(all_points[BROW_CENTER], all_points[CHIN])
            if face_h == 0:
                nod_ratio_raw = 0
            else:
                nod_ratio_raw = euclidean(all_points[BROW_CENTER], all_points[NOSE_TIP]) / face_h
            nod_ratio = median_smooth(nod_queue, nod_ratio_raw)

            face_w = euclidean(all_points[FACE_LEFT], all_points[FACE_RIGHT])
            if face_w == 0:
                h_ratio_raw = 0
            else:
                h_ratio_raw = euclidean(all_points[FACE_LEFT], all_points[NOSE_TIP]) / face_w
            h_ratio = median_smooth(head_queue, h_ratio_raw)

            if prev_head is None:
                head_motion_raw = 0
            else:
                head_motion_raw = abs(h_ratio - prev_head)
            head_motion = median_smooth(head_motion_queue, head_motion_raw)
            prev_head = h_ratio

            if not calibrated:
                calibration_ears.append(ear)
                calibration_mars.append(mar)
                calibration_nods.append(nod_ratio)
                calibration_heads.append(h_ratio)

                remain = int(5 - (time.time() - calibration_start))
                if remain < 0:
                    remain = 0

                draw_text(screen, big_font, f"Calibrating... {remain}s", 120, 210, color=(255, 255, 0))
                draw_text(screen, font, "Look forward, keep eyes open", 80, 250, color=(255, 255, 0))
                draw_text(screen, font, "If you wear glasses, calibrate with glasses", 80, 280, color=(255, 255, 0))

                if time.time() - calibration_start >= 5:
                    baseline_ear = float(np.median(calibration_ears))
                    baseline_mar = float(np.median(calibration_mars))
                    baseline_nod = float(np.median(calibration_nods))
                    baseline_head = float(np.median(calibration_heads))

                    if rule["EAR_THRESHOLD"] is not None:
                        EAR_THRESHOLD = rule["EAR_THRESHOLD"]
                    else:
                        EAR_THRESHOLD = baseline_ear * 0.90

                    if rule["YAWN_THRESHOLD"] is not None:
                        YAWN_THRESHOLD = rule["YAWN_THRESHOLD"]
                    else:
                        YAWN_THRESHOLD = max(0.35, baseline_mar * 2.0)

                    if rule.get("BASELINE_NOD") is not None:
                        baseline_nod = rule["BASELINE_NOD"]
                    if rule.get("BASELINE_HEAD") is not None:
                        baseline_head = rule["BASELINE_HEAD"]

                    calibrated = True

                    print("========== Calibration Done ==========")
                    print(f"Baseline EAR    = {baseline_ear:.3f}")
                    print(f"EAR Threshold   = {EAR_THRESHOLD:.3f}")
                    print(f"Baseline MAR    = {baseline_mar:.3f}")
                    print(f"Yawn Threshold  = {YAWN_THRESHOLD:.3f}")
                    print(f"Baseline Nod    = {baseline_nod:.3f}")
                    print(f"Baseline Head   = {baseline_head:.3f}")
                    print("======================================")

            else:
                current_time = time.time()

                # Blink / eye close
                if ear < EAR_THRESHOLD:
                    if not is_blinking:
                        is_blinking = True
                        eye_closed_start = current_time

                    if eye_closed_start is not None:
                        closed_time = current_time - eye_closed_start
                        if closed_time >= EYE_CLOSED_SECONDS:
                            eye_alert = True
                else:
                    if is_blinking:
                        blink_count += 1
                        blink_times.append(current_time)
                        is_blinking = False

                    eye_closed_start = None
                    eye_alert = False

                while len(blink_times) > 0 and current_time - blink_times[0] > BLINK_WINDOW_SECONDS:
                    blink_times.popleft()

                blink_rate_10s = len(blink_times)

                # Yawn
                if mar > YAWN_THRESHOLD:
                    if yawn_start is None:
                        yawn_start = current_time
                    yawn_time = current_time - yawn_start
                    if yawn_time >= YAWN_SECONDS:
                        yawn_alert = True
                    if not was_yawning and yawn_alert:
                        yawn_count += 1
                        was_yawning = True
                else:
                    yawn_start = None
                    yawn_alert = False
                    was_yawning = False

                # Nod
                nod_down = nod_ratio > baseline_nod + NOD_DELTA
                if nod_down:
                    if nod_start is None:
                        nod_start = current_time
                    nod_time = current_time - nod_start
                    if nod_time >= NOD_SECONDS:
                        nod_alert = True
                else:
                    nod_start = None
                    nod_alert = False

                # Look away / head drift
                head_diff = abs(h_ratio - baseline_head)
                if head_diff > HEAD_DELTA:
                    if distract_start is None:
                        distract_start = current_time
                    distract_time = current_time - distract_start
                    if distract_time >= DISTRACT_SECONDS:
                        distract_alert = True
                else:
                    distract_start = None
                    distract_alert = False

                alert_list = []
                if eye_alert:
                    alert_list.append("EYE_CLOSED")
                if blink_rate_10s >= 8:
                    alert_list.append("FAST_BLINK")
                if yawn_alert:
                    alert_list.append("YAWNING")
                if nod_alert:
                    alert_list.append("NODDING_DOWN")
                if distract_alert:
                    alert_list.append("LOOK_AWAY")
                if head_motion > 0.05:
                    alert_list.append("HEAD_SHAKE")

                auto_status = "NORMAL" if len(alert_list) == 0 else "+".join(alert_list)

                if current_time - last_save_time >= 1:
                    with open(DATASET_FILE, mode="a", newline="", encoding="utf-8-sig") as file:
                        writer = csv.writer(file)
                        writer.writerow([
                            time.strftime("%Y-%m-%d %H:%M:%S"),
                            round(ear, 3),
                            round(mar, 3),
                            blink_count,
                            blink_rate_10s,
                            round(nod_ratio, 3),
                            round(h_ratio, 3),
                            round(head_motion, 3),
                            current_label,
                            current_label_name,
                            current_user_type
                        ])

                        if is_target_wifi():

                            if check_server_connection():

                                upload_result = upload_one_row_to_server(
                                    user_name,
                                    current_user_type,
                                    ear,
                                    mar,
                                    blink_count,
                                    blink_rate_10s,
                                    nod_ratio,
                                    h_ratio,
                                    head_motion,
                                    current_label,
                                    current_label_name
                                )

                                print("[UPLOAD RESULT]", upload_result)

                            else:
                                print("[UPLOAD] server not connected")

                        else:
                            print("[UPLOAD] not target wifi")

                    print(
                        f"[SAVED] "
                        f"EAR={ear:.2f} MAR={mar:.2f} Blink={blink_count} "
                        f"BlinkRate10s={blink_rate_10s} Nod={nod_ratio:.2f} "
                        f"Head={h_ratio:.2f} HeadMotion={head_motion:.3f} "
                        f"Auto={auto_status} Label={current_label}:{current_label_name}"
                    )

                    last_save_time = current_time

                

                current = time.time()
                if current - prev_time != 0:
                    fps = 1 / (current - prev_time)
                prev_time = current

               

                label_color = (0, 255, 0) if current_label == 0 else (255, 0, 0)
                auto_color = (0, 255, 0) if auto_status == "NORMAL" else (255, 0, 0)

                draw_text(screen, font, f"FPS: {int(fps)}", 10, 25, color=(0, 255, 0))
                draw_text(screen, font, f"EAR: {ear:.2f} / TH: {EAR_THRESHOLD:.2f}", 10, 55)
                draw_text(screen, font, f"MAR: {mar:.2f} / TH: {YAWN_THRESHOLD:.2f}", 10, 85)
                draw_text(screen, font, f"Blink: {blink_count} / 10s: {blink_rate_10s}", 10, 115)
                draw_text(screen, font, f"Nod: {nod_ratio:.2f} / Base: {baseline_nod:.2f}", 10, 145)
                draw_text(screen, font, f"Head: {h_ratio:.2f} / Base: {baseline_head:.2f}", 10, 175)
                draw_text(screen, font, f"HeadMotion: {head_motion:.3f}", 10, 205)
                draw_text(screen, font, f"Auto: {auto_status}", 10, 235, color=auto_color)
                draw_text(screen, font, f"Label: {current_label} - {current_label_name}", 10, 265, color=label_color)

                sync_text = "SYNC: RUNNING" if sync_running else f"SYNC: {sync_msg}"
                draw_text(screen, font, sync_text, 10, 295, color=(255, 255, 0))

        else:
            draw_text(screen, big_font, "No face detected", 180, 220, color=(255, 0, 0))
            draw_text(screen, font, f"No face count: {no_face_count}", 220, 260, color=(255, 255, 0))

        draw_text(screen, font, "0/N NORMAL | 1/Y YAWN | 2/E EYE | 3/D NOD", 10, 385, color=(255, 255, 255))
        draw_text(
            screen,
            font,
            f"Current Label: {current_label} {current_label_name}",
            10,
            445,
            color=(255, 255, 0)
        )

        draw_text(
            screen,
            font,
            f"UserType: {current_user_type} | G=GENERAL S=SMALL_EYE",
            10,
            465,
            color=(255, 255, 0)
        )
        

        pygame.display.update()
        clock.tick(DISPLAY_FPS)

    cam.stop()
    pygame.camera.quit()
    pygame.quit()


if __name__ == "__main__":
    main()
