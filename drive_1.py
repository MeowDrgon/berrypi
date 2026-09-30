#2026/6/3尚未進行修改，尚未跟上第一版大更新
import os
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

import json
import time
import subprocess
from collections import deque

import dlib
import numpy as np
import requests
import pygame
import pygame.camera


# ==========================================
# AI 疲勞駕駛正式上路版
# Windows / dlib / pygame.camera / 無 cv2
#
# 功能：
# 1. 不用輸入名字
# 2. 從 config.json 讀 user_id / server_url / target_wifi
# 3. 啟動時自動向伺服器下載 rules/<user_id>_multiclass_rule.json
# 4. 若伺服器連不上，改讀本機快取 rule
# 5. 使用 rule 判斷疲勞狀態
# 6. 偵測到疲勞狀態時播放警報聲
# 7. 第一版正式上路：不回傳資料庫、不存 CSV
# ==========================================


# ==========================================
# 基本設定
# ==========================================
CONFIG_FILE = "config.json"
RULE_DIR = "rules"
RULE_VERSION = "multiclass_rule_v1"

os.makedirs(RULE_DIR, exist_ok=True)

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
DISPLAY_FPS = 30

# 如果攝影機不穩，可以改成：
# CAMERA_WIDTH = 320
# CAMERA_HEIGHT = 240

NO_FACE_LIMIT = 20

SMOOTH_WINDOW = 5
EAR_JUMP_LIMIT = 0.12
MAR_JUMP_LIMIT = 0.20

BLINK_WINDOW_SECONDS = 10

# 警報設定
ALERT_HOLD_SECONDS = 0.8       # 異常狀態持續多久才警報
ALERT_COOLDOWN_SECONDS = 2.0   # 警報聲間隔
ALARM_FILE = "alarm.wav"       # 可有可無，有就播放 wav，沒有就用 beep

# 安全下限，避免訓練出的 threshold 太敏感
MIN_BLINK_RATE_THRESHOLD = 6.0
MIN_SHAKE_THRESHOLD = 0.03
MIN_HEAD_DELTA = 0.10
MIN_NOD_DELTA = 0.05


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
# config.json
# ==========================================
def create_config_template():
    template = {
        "user_id": "林庭佑",
        "server_url": "http://172.16.126.162:5000",
        "target_wifi": "CJCU3202"
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=4, ensure_ascii=False)

    print("[CONFIG] 已建立 config.json 範本")
    print("請先打開 config.json，把 user_id 改成伺服器 rules 裡對應的使用者名稱")
    print("例如 rules/陳茂隆_multiclass_rule.json，user_id 就要填：陳茂隆")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_config_template()
        return None

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        user_id = config.get("user_id")
        server_url = config.get("server_url")
        target_wifi = config.get("target_wifi")

        if (
            not user_id
            or not server_url
            or not target_wifi
            or "請改成" in str(user_id)
        ):
            print("[ERROR] config.json 尚未設定完成")
            print("請確認 config.json 內有 user_id、server_url、target_wifi")
            return None

        return config

    except Exception as e:
        print("[CONFIG LOAD ERROR]", repr(e))
        return None


# ==========================================
# Wi-Fi / Server / Rule
# ==========================================
def get_current_wifi():
    """
    Windows 版本 Wi-Fi 偵測。
    如果未來放到 Raspberry Pi，這個函式要改成 iwgetid -r。
    """
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


def is_target_wifi(target_wifi):
    current_wifi = get_current_wifi()
    print("[CURRENT WIFI]", current_wifi)
    return current_wifi == target_wifi


def check_server_connection(server_url):
    try:
        response = requests.get(
            server_url + "/ping",
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


def get_rule_path(user_id):
    return os.path.join(RULE_DIR, f"{user_id}_multiclass_rule.json")


def download_rule_from_server(user_id, server_url):
    try:
        url = server_url + f"/rule/{user_id}"

        response = requests.get(
            url,
            timeout=5
        )

        result = response.json()

        if result.get("status") != "success":
            print("[RULE DOWNLOAD FAILED]", result)
            return None

        rule = result.get("rule")

        if rule is None:
            print("[RULE DOWNLOAD FAILED] no rule in response")
            return None

        rule_path = get_rule_path(user_id)

        with open(rule_path, "w", encoding="utf-8") as f:
            json.dump(rule, f, indent=4, ensure_ascii=False)

        print("[RULE DOWNLOADED]", rule_path)
        return rule

    except Exception as e:
        print("[RULE DOWNLOAD ERROR]", repr(e))
        return None


def load_local_rule(user_id):
    rule_path = get_rule_path(user_id)

    if not os.path.exists(rule_path):
        print("[RULE LOCAL] not found:", rule_path)
        return None

    try:
        with open(rule_path, "r", encoding="utf-8") as f:
            rule = json.load(f)

        print("[RULE LOADED FROM LOCAL]", rule_path)
        return rule

    except Exception as e:
        print("[RULE LOCAL LOAD ERROR]", repr(e))
        return None


def load_rule_auto(user_id, server_url, target_wifi):
    """
    啟動時：
    1. 如果在指定 Wi-Fi 且 server 連得上，先下載最新版 rule
    2. 下載失敗就讀本機快取
    3. 兩個都沒有就停止
    """
    if is_target_wifi(target_wifi) and check_server_connection(server_url):
        print("[RULE] Try download latest rule from server...")
        rule = download_rule_from_server(user_id, server_url)

        if rule is not None:
            return rule

    print("[RULE] Use local cached rule...")
    return load_local_rule(user_id)


# ==========================================
# Rule 解析
# ==========================================
def get_rule_thresholds(rule):
    """
    讀取新版 multiclass_rule_v1 格式。
    """
    try:
        rules = rule["rules"]

        yawn_threshold = float(
            rules["YAWN"]["YAWN_THRESHOLD"]
        )

        ear_threshold = float(
            rules["EYE_CLOSE_OR_BLINK"]["EAR_THRESHOLD"]
        )

        blink_rate_threshold = float(
            rules["EYE_CLOSE_OR_BLINK"]["BLINK_RATE_THRESHOLD"]
        )

        baseline_nod = float(
            rules["NOD"]["BASELINE_NOD"]
        )

        nod_delta = float(
            rules["NOD"]["NOD_DELTA"]
        )

        shake_threshold = float(
            rules["SHAKE_HEAD"]["SHAKE_THRESHOLD"]
        )

        baseline_head = float(
            rules["LOOK_AWAY"]["BASELINE_HEAD"]
        )

        head_delta = float(
            rules["LOOK_AWAY"]["HEAD_DELTA"]
        )

        # 安全下限，避免過度敏感
        blink_rate_threshold = max(MIN_BLINK_RATE_THRESHOLD, blink_rate_threshold)
        shake_threshold = max(MIN_SHAKE_THRESHOLD, shake_threshold)
        nod_delta = max(MIN_NOD_DELTA, nod_delta)
        head_delta = max(MIN_HEAD_DELTA, head_delta)

        thresholds = {
            "YAWN_THRESHOLD": yawn_threshold,
            "EAR_THRESHOLD": ear_threshold,
            "BLINK_RATE_THRESHOLD": blink_rate_threshold,
            "BASELINE_NOD": baseline_nod,
            "NOD_DELTA": nod_delta,
            "SHAKE_THRESHOLD": shake_threshold,
            "BASELINE_HEAD": baseline_head,
            "HEAD_DELTA": head_delta,
        }

        return thresholds

    except Exception as e:
        print("[RULE FORMAT ERROR]", repr(e))
        return None


def judge_by_rule(
    ear,
    mar,
    blink_rate_10s,
    nod_ratio,
    h_ratio,
    head_motion,
    thresholds
):
    """
    回傳：
    label, status_name
    """
    if mar > thresholds["YAWN_THRESHOLD"]:
        return 1, "YAWN"

    if (
        ear < thresholds["EAR_THRESHOLD"]
        or blink_rate_10s > thresholds["BLINK_RATE_THRESHOLD"]
    ):
        return 2, "EYE_CLOSE_OR_BLINK"

    if nod_ratio > (
        thresholds["BASELINE_NOD"]
        + thresholds["NOD_DELTA"]
    ):
        return 3, "NOD"

    if head_motion > thresholds["SHAKE_THRESHOLD"]:
        return 4, "SHAKE_HEAD"

    if abs(h_ratio - thresholds["BASELINE_HEAD"]) > thresholds["HEAD_DELTA"]:
        return 5, "LOOK_AWAY"

    return 0, "NORMAL"


# ==========================================
# 基本計算
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
    valid = []

    for v in [left_ear, right_ear]:
        if 0.05 <= v <= 0.45:
            valid.append(v)

    if len(valid) == 0:
        return prev_ear if prev_ear is not None else (left_ear + right_ear) / 2.0

    ear = float(np.median(valid))

    if prev_ear is not None and abs(ear - prev_ear) > EAR_JUMP_LIMIT:
        ear = prev_ear * 0.7 + ear * 0.3

    return ear


def robust_value(value, prev_value, jump_limit):
    if prev_value is None:
        return value

    if abs(value - prev_value) > jump_limit:
        return prev_value * 0.7 + value * 0.3

    return value


def pick_largest_face(faces):
    return max(faces, key=lambda r: r.width() * r.height())


# ==========================================
# 聲音警報
# ==========================================
try:
    import winsound
    HAS_WINSOUND = True
except Exception:
    HAS_WINSOUND = False


def init_alarm():
    try:
        pygame.mixer.init()

        if os.path.exists(ALARM_FILE):
            print("[ALARM] using alarm.wav")
            return pygame.mixer.Sound(ALARM_FILE)

        print("[ALARM] alarm.wav not found, use beep")
        return None

    except Exception as e:
        print("[ALARM INIT ERROR]", repr(e))
        return None


def play_alert_sound(alarm_sound, status_name):
    try:
        if alarm_sound is not None:
            alarm_sound.play()
            return

        if HAS_WINSOUND:
            if status_name == "YAWN":
                winsound.Beep(800, 300)
            elif status_name == "EYE_CLOSE_OR_BLINK":
                winsound.Beep(1200, 300)
            elif status_name == "NOD":
                winsound.Beep(1000, 300)
            elif status_name == "SHAKE_HEAD":
                winsound.Beep(900, 300)
            elif status_name == "LOOK_AWAY":
                winsound.Beep(700, 300)
            else:
                winsound.Beep(1000, 300)

    except Exception as e:
        print("[ALERT SOUND ERROR]", repr(e))


# ==========================================
# pygame 繪圖
# ==========================================
def draw_text(screen, font, text, x, y, color=(255, 255, 255)):
    img = font.render(text, True, color)
    screen.blit(img, (x, y))


def draw_point(screen, point, color=(0, 255, 0), radius=2):
    pygame.draw.circle(
        screen,
        color,
        (int(point[0]), int(point[1])),
        radius
    )


def draw_rect(screen, left, top, right, bottom, color=(0, 0, 255), width=2):
    rect = pygame.Rect(
        int(left),
        int(top),
        int(right - left),
        int(bottom - top)
    )
    pygame.draw.rect(screen, color, rect, width)


# ==========================================
# 主程式
# ==========================================
def main():
    # ==================================
    # 讀 config
    # ==================================
    config = load_config()

    if config is None:
        return

    user_id = config["user_id"]
    server_url = config["server_url"]
    target_wifi = config["target_wifi"]

    print("========== Driving Mode ==========")
    print("[USER ID]", user_id)
    print("[SERVER URL]", server_url)
    print("[TARGET WIFI]", target_wifi)
    print("==================================")

    # ==================================
    # 讀 rule
    # ==================================
    rule = load_rule_auto(
        user_id,
        server_url,
        target_wifi
    )

    if rule is None:
        print("[STOP] 無法取得 rule，正式上路模式停止")
        return

    thresholds = get_rule_thresholds(rule)

    if thresholds is None:
        print("[STOP] rule 格式錯誤，正式上路模式停止")
        return

    print("========== Rule Thresholds ==========")
    for k, v in thresholds.items():
        print(f"{k}: {v}")
    print("=====================================")

    # ==================================
    # dlib model
    # ==================================
    model_path = "shape_predictor_68_face_landmarks.dat"

    if not os.path.exists(model_path):
        print("找不到 shape_predictor_68_face_landmarks.dat")
        print("請把模型檔放在跟這個 Python 檔同一個資料夾")
        return

    detector = dlib.get_frontal_face_detector()
    predictor = dlib.shape_predictor(model_path)

    # ==================================
    # pygame / camera
    # ==================================
    pygame.init()
    pygame.camera.init()

    alarm_sound = init_alarm()

    cameras = pygame.camera.list_cameras()

    if len(cameras) == 0:
        print("找不到攝影機")
        return

    print("[CAMERA LIST]", cameras)
    print("[USING CAMERA]", cameras[0])

    cam = pygame.camera.Camera(
        cameras[0],
        (CAMERA_WIDTH, CAMERA_HEIGHT),
        "RGB"
    )
    cam.start()

    screen = pygame.display.set_mode(
        (CAMERA_WIDTH, CAMERA_HEIGHT)
    )

    pygame.display.set_caption(
        "AI Fatigue Driving Detection - Rule Mode"
    )

    font = pygame.font.SysFont("Arial", 18)
    big_font = pygame.font.SysFont("Arial", 26)

    clock = pygame.time.Clock()

    # ==================================
    # 計數與平滑
    # ==================================
    blink_count = 0
    is_blinking = False
    blink_times = deque()

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

    prev_time = time.time()
    fps = 0

    current_status = "NORMAL"
    current_label = 0

    abnormal_start = None
    last_alert_time = 0

    running = True

    print("======================================")
    print("正式上路模式啟動")
    print("不需輸入姓名，不按 Label，不上傳資料庫")
    print("Q = QUIT")
    print("======================================")

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    print("[INFO] Quit")
                    running = False

        if not cam.query_image():
            clock.tick(DISPLAY_FPS)
            continue

        frame_surface = cam.get_image()
        frame_surface = pygame.transform.scale(
            frame_surface,
            (CAMERA_WIDTH, CAMERA_HEIGHT)
        )
        frame_surface = pygame.transform.flip(
            frame_surface,
            True,
            False
        )

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

            if (
                no_face_count < NO_FACE_LIMIT
                and last_face is not None
                and last_points is not None
            ):
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

            draw_rect(
                screen,
                face.left(),
                face.top(),
                face.right(),
                face.bottom(),
                color=(0, 0, 255),
                width=2
            )

            if using_cached_face:
                draw_text(
                    screen,
                    font,
                    "Face cached",
                    500,
                    25,
                    color=(255, 255, 0)
                )
            else:
                draw_text(
                    screen,
                    font,
                    "Face detected",
                    500,
                    25,
                    color=(0, 255, 0)
                )

            # ==================================
            # 特徵計算
            # ==================================
            left_ear = calculate_ear(
                [all_points[i] for i in LEFT_EYE]
            )
            right_ear = calculate_ear(
                [all_points[i] for i in RIGHT_EYE]
            )

            raw_ear = robust_ear(
                left_ear,
                right_ear,
                prev_ear
            )
            raw_ear = robust_value(
                raw_ear,
                prev_ear,
                EAR_JUMP_LIMIT
            )
            ear = median_smooth(
                ear_queue,
                raw_ear
            )
            prev_ear = ear

            raw_mar = calculate_mar(
                [all_points[i] for i in MOUTH]
            )
            raw_mar = robust_value(
                raw_mar,
                prev_mar,
                MAR_JUMP_LIMIT
            )
            mar = median_smooth(
                mar_queue,
                raw_mar
            )
            prev_mar = mar

            face_h = euclidean(
                all_points[BROW_CENTER],
                all_points[CHIN]
            )

            if face_h == 0:
                nod_ratio_raw = 0
            else:
                nod_ratio_raw = euclidean(
                    all_points[BROW_CENTER],
                    all_points[NOSE_TIP]
                ) / face_h

            nod_ratio = median_smooth(
                nod_queue,
                nod_ratio_raw
            )

            face_w = euclidean(
                all_points[FACE_LEFT],
                all_points[FACE_RIGHT]
            )

            if face_w == 0:
                h_ratio_raw = 0
            else:
                h_ratio_raw = euclidean(
                    all_points[FACE_LEFT],
                    all_points[NOSE_TIP]
                ) / face_w

            h_ratio = median_smooth(
                head_queue,
                h_ratio_raw
            )

            if prev_head is None:
                head_motion_raw = 0
            else:
                head_motion_raw = abs(
                    h_ratio - prev_head
                )

            head_motion = median_smooth(
                head_motion_queue,
                head_motion_raw
            )
            prev_head = h_ratio

            # ==================================
            # BlinkRate10s
            # ==================================
            current_time = time.time()

            if ear < thresholds["EAR_THRESHOLD"]:
                if not is_blinking:
                    is_blinking = True
            else:
                if is_blinking:
                    blink_count += 1
                    blink_times.append(current_time)
                    is_blinking = False

            while (
                len(blink_times) > 0
                and current_time - blink_times[0] > BLINK_WINDOW_SECONDS
            ):
                blink_times.popleft()

            blink_rate_10s = len(blink_times)

            # ==================================
            # 用 rule 判斷
            # ==================================
            label, status_name = judge_by_rule(
                ear,
                mar,
                blink_rate_10s,
                nod_ratio,
                h_ratio,
                head_motion,
                thresholds
            )

            current_label = label
            current_status = status_name

            # ==================================
            # 警報防抖
            # ==================================
            if current_status == "NORMAL":
                abnormal_start = None
            else:
                if abnormal_start is None:
                    abnormal_start = current_time

                abnormal_duration = current_time - abnormal_start

                if abnormal_duration >= ALERT_HOLD_SECONDS:
                    if current_time - last_alert_time >= ALERT_COOLDOWN_SECONDS:
                        play_alert_sound(
                            alarm_sound,
                            current_status
                        )

                        print(
                            f"[ALERT] {current_status} "
                            f"EAR={ear:.3f} MAR={mar:.3f} "
                            f"BlinkRate10s={blink_rate_10s} "
                            f"Nod={nod_ratio:.3f} "
                            f"Head={h_ratio:.3f} "
                            f"HeadMotion={head_motion:.3f}"
                        )

                        last_alert_time = current_time

            # ==================================
            # FPS
            # ==================================
            now = time.time()
            if now - prev_time != 0:
                fps = 1 / (now - prev_time)
            prev_time = now

            # ==================================
            # 畫面顯示
            # ==================================
            if current_status == "NORMAL":
                status_color = (0, 255, 0)
            else:
                status_color = (255, 0, 0)

            draw_text(
                screen,
                font,
                f"USER: {user_id}",
                10,
                25,
                color=(255, 255, 255)
            )
            draw_text(
                screen,
                font,
                f"FPS: {int(fps)}",
                10,
                55,
                color=(0, 255, 0)
            )
            draw_text(
                screen,
                font,
                f"EAR: {ear:.2f} / TH: {thresholds['EAR_THRESHOLD']:.2f}",
                10,
                85
            )
            draw_text(
                screen,
                font,
                f"MAR: {mar:.2f} / TH: {thresholds['YAWN_THRESHOLD']:.2f}",
                10,
                115
            )
            draw_text(
                screen,
                font,
                f"Blink10s: {blink_rate_10s} / TH: {thresholds['BLINK_RATE_THRESHOLD']:.1f}",
                10,
                145
            )
            draw_text(
                screen,
                font,
                f"Nod: {nod_ratio:.2f} / Base: {thresholds['BASELINE_NOD']:.2f}",
                10,
                175
            )
            draw_text(
                screen,
                font,
                f"Head: {h_ratio:.2f} / Base: {thresholds['BASELINE_HEAD']:.2f}",
                10,
                205
            )
            draw_text(
                screen,
                font,
                f"HeadMotion: {head_motion:.3f} / TH: {thresholds['SHAKE_THRESHOLD']:.3f}",
                10,
                235
            )
            draw_text(
                screen,
                big_font,
                f"STATUS: {current_status}",
                10,
                275,
                color=status_color
            )

        else:
            current_status = "NO_FACE"

            draw_text(
                screen,
                big_font,
                "No face detected",
                180,
                220,
                color=(255, 0, 0)
            )
            draw_text(
                screen,
                font,
                f"No face count: {no_face_count}",
                220,
                260,
                color=(255, 255, 0)
            )

        draw_text(
            screen,
            font,
            "Q = QUIT",
            10,
            CAMERA_HEIGHT - 35,
            color=(255, 255, 0)
        )

        pygame.display.update()
        clock.tick(DISPLAY_FPS)

    cam.stop()
    pygame.camera.quit()
    pygame.quit()


if __name__ == "__main__":
    main()