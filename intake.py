"""沒有體脂計截圖時，用問答收集基本資料，計算 BMR／TDEE。

BMR 採 Mifflin-St Jeor 公式：
  男性：10 × 體重(kg) + 6.25 × 身高(cm) − 5 × 年齡 + 5
  女性：10 × 體重(kg) + 6.25 × 身高(cm) − 5 × 年齡 − 161
TDEE = BMR × 活動係數
"""
import re

from analyzer import BodyMetrics

# (按鈕文字, 說明, 係數)
ACTIVITY = [
    ("久坐", "幾乎不運動、坐辦公室", 1.2),
    ("輕度活動", "每週運動 1–3 天", 1.375),
    ("中度活動", "每週運動 3–5 天", 1.55),
    ("高度活動", "每週運動 6–7 天", 1.725),
    ("非常高", "勞力工作或一天練兩次", 1.9),
]
GOALS = ["減脂", "維持體重", "增肌", "跳過"]

# 每一步：(欄位, 問題, 快速按鈕)
STEPS = [
    ("sex", "1/6 請問你的生理性別？", ["男性", "女性"]),
    ("age", "2/6 請問你幾歲？（直接打數字，例：35）", None),
    ("height", "3/6 身高幾公分？（例：165）", None),
    ("weight", "4/6 體重幾公斤？（例：58.5）", None),
    ("activity", "5/6 平常的活動量？\n" + "\n".join(
        f"{n}. {label}：{desc}" for n, (label, desc, _) in enumerate(ACTIVITY, 1)),
     [a[0] for a in ACTIVITY]),
    ("goal", "6/6 你的目標是什麼？\n可以按按鈕，或直接打字說明\n（例：想減脂但保留肌肉，每週重訓兩次）", GOALS),
]
RANGES = {"age": (10, 100), "height": (100, 230), "weight": (25, 250)}
UNITS = {"age": "歲", "height": "公分", "weight": "公斤"}


def parse(field: str, text: str):
    """解析使用者回答；看不懂就回傳 None。"""
    text = text.strip()
    if field == "sex":
        if "男" in text:
            return "male"
        if "女" in text:
            return "female"
        return None
    if field in RANGES:
        m = re.search(r"\d+(?:\.\d+)?", text)
        if not m:
            return None
        value = float(m.group())
        lo, hi = RANGES[field]
        return value if lo <= value <= hi else None
    if field == "activity":
        if text.isdigit() and 1 <= int(text) <= len(ACTIVITY):
            return int(text) - 1
        for i, (label, _, _) in enumerate(ACTIVITY):
            if label in text:
                return i
        return None
    if field == "goal":
        return None if text in ("跳過", "沒有", "不用") else text
    return None


def retry_hint(field: str) -> str:
    if field == "sex":
        return "請按「男性」或「女性」"
    if field in RANGES:
        lo, hi = RANGES[field]
        return f"請輸入 {lo}–{hi} 之間的數字（{UNITS[field]}）"
    if field == "activity":
        return "請按下面的按鈕，或輸入 1–5"
    return ""


def compute(profile: dict) -> dict:
    """回傳 {"bmr", "tdee", "bmi", "factor", "activity_label"}。"""
    w, h, a = profile["weight"], profile["height"], profile["age"]
    bmr = 10 * w + 6.25 * h - 5 * a + (5 if profile["sex"] == "male" else -161)
    label, desc, factor = ACTIVITY[profile["activity"]]
    return {"bmr": round(bmr), "tdee": round(bmr * factor), "bmi": round(w / (h / 100) ** 2, 1),
            "factor": factor, "activity_label": f"{label}（{desc}）"}


def to_metrics(profile: dict, calc: dict) -> BodyMetrics:
    """轉成和體脂計截圖相同的格式，後續的營養規劃、狀態顯示都能共用。"""
    fields = {k: None for k in BodyMetrics.model_fields}
    fields.update(weight_kg=profile["weight"], bmi=calc["bmi"], bmr_kcal=calc["bmr"],
                  activity_kcal=calc["tdee"], flags=[])
    return BodyMetrics(**fields)


def describe(profile: dict, calc: dict) -> str:
    """給 AI 營養師的使用者描述。"""
    sex = "男性" if profile["sex"] == "male" else "女性"
    return (f"{sex}、{profile['age']:g} 歲、身高 {profile['height']:g} cm、體重 {profile['weight']:g} kg，"
            f"活動量：{calc['activity_label']}。目標：{profile.get('goal') or '沒有特別說明'}。"
            "（沒有體脂計數據，BMR／TDEE 由 Mifflin-St Jeor 公式計算）")


def format_calc(profile: dict, calc: dict) -> str:
    sex = "男性" if profile["sex"] == "male" else "女性"
    return "\n".join([
        "📐 基礎代謝計算（Mifflin-St Jeor）",
        f"{sex}｜{profile['age']:g} 歲｜{profile['height']:g} cm｜{profile['weight']:g} kg｜BMI {calc['bmi']}",
        f"基礎代謝 BMR：{calc['bmr']} kcal",
        f"每日總消耗 TDEE：{calc['tdee']} kcal（{calc['activity_label']} ×{calc['factor']}）",
        f"溫和減重參考：{calc['tdee'] - 300} kcal（−300）",
        f"一般減重參考：{calc['tdee'] - 500} kcal（−500）",
    ])
