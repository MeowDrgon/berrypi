
import json
import urllib.request
from datetime import datetime, timedelta

# Windows 本機 Flask 伺服器
URL = "http://127.0.0.1:5000/upload"

# 三筆模擬資料：正常、疲勞、未知
samples = [
    {
        "name": "正常駕駛",
        "label": 0,
        "label_name": "NORMAL",
        "ear": 0.31,
        "mar": 0.12,
    },
    {
        "name": "打哈欠",
        "label": 1,
        "label_name": "YAWN",
        "ear": 0.29,
        "mar": 0.85,
    },
    {
        "name": "點頭",
        "label": 3,
        "label_name": "NOD",
        "ear": 0.20,
        "mar": 0.15,
    },
]

for i, sample in enumerate(samples):
    data = {
        "user_id": "111",
        "user_type": "general",
        "Time": (
            datetime.now() + timedelta(seconds=i)
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "EAR": sample["ear"],
        "MAR": sample["mar"],
        "Blink": 0,
        "BlinkRate10s": 2,
        "NodRatio": 0.0,
        "HeadRatio": 0.0,
        "HeadMotion": 0.0,
        "Label": sample["label"],
        "LabelName": sample["label_name"],
    }

    request = urllib.request.Request(
        URL,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            result = response.read().decode("utf-8")
            print(sample["name"], "上傳成功:", result)
    except Exception as e:
        print(sample["name"], "上傳失敗:", e)

print("測試資料上傳流程結束")
