"""測試共用工具：假的 LINE、假的 Gemini、乾淨的記憶體資料庫。

不會呼叫任何外部 API，也不會碰到真正的 calorie.db。
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 必須在 import app 之前設定：假金鑰＋記憶體資料庫（load_dotenv 不會覆蓋已存在的值）
os.environ["LINE_CHANNEL_SECRET"] = "test-secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test-token"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["DB_PATH"] = ":memory:"
os.environ["DEFAULT_GOAL_KCAL"] = "1800"
os.environ["USE_NUTRITION_DB"] = "false"

import app as app_module  # noqa: E402
from analyzer import Analysis, NutritionPlan  # noqa: E402
from storage import Storage  # noqa: E402

USER = "U-test"


def food(*items, advice="不錯", question="", plate=(50, 25, 25)) -> Analysis:
    """items：(名稱, 分類, 克數, 每100g熱量)；營養素固定為 每100g 蛋白質10、碳水20、脂肪5。"""
    return Analysis.model_validate({
        "kind": "食物", "question": question, "body": None, "advice": advice,
        "plate": {"veg_pct": plate[0], "protein_pct": plate[1], "starch_pct": plate[2]},
        "items": [{"name": n, "category": c, "db_name": "", "grams": g, "est_kcal_per_100g": k,
                   "protein_per_100g": 10, "carb_per_100g": 20, "fat_per_100g": 5}
                  for n, c, g, k in items],
    })


def body_report(**overrides) -> Analysis:
    """體脂計截圖的分析結果（預設為使用者提供的範例截圖數值）。"""
    metrics = {
        "weight_kg": 56.6, "bmi": 22.7, "body_fat_pct": 33.2, "water_pct": 47.9,
        "skeletal_muscle_pct": 40.7, "protein_pct": 14.8, "muscle_pct": 62.7,
        "visceral_fat": 6, "subcutaneous_fat_kg": 17.4, "fat_free_mass_kg": 37.8,
        "bmr_kcal": 1273, "activity_kcal": 1680, "body_age": 49, "standard_weight_kg": 54.3,
        "weight_control_kg": -2.3, "fat_control_kg": -6.3, "muscle_control_kg": 4.0,
        "flags": ["蛋白質率偏低", "肌肉率偏低"],
    }
    metrics.update(overrides)
    return Analysis.model_validate({"kind": "身體組成", "items": [], "plate": None,
                                    "advice": "", "question": "", "body": metrics})


def other() -> Analysis:
    return Analysis.model_validate({"kind": "其他", "items": [], "plate": None,
                                    "advice": "", "question": "", "body": None})


def nutrition_plan(**overrides) -> NutritionPlan:
    data = {"kcal": 1400, "protein_g": 90, "carb_g": 150, "fat_g": 45, "fiber_g": 25,
            "water_ml": 2000, "meals": [{"name": "早餐", "kcal": 400, "suggestion": "豆漿＋蛋"}],
            "summary": "評估", "strategy": "策略", "tips": ["多喝水"], "caution": ""}
    data.update(overrides)
    return NutritionPlan(**data)


class Bot:
    """模擬 LINE 使用者跟 Bot 對話；記錄 Bot 的回覆與交給 AI 的參數。"""

    def __init__(self, monkeypatch):
        self.replies: list[dict] = []
        self.analyze_calls: list[dict] = []
        self.plan_calls: list[tuple] = []
        self.analyze_results: list = []   # 依序回傳；可放 Exception 模擬失敗
        self.plan_results: list = []
        self.downloads: dict[str, bytes | Exception] = {}

        app = app_module
        monkeypatch.setattr(app, "storage", Storage(":memory:", 1800))
        app._state.clear()
        app._last_meal.clear()
        monkeypatch.setattr(app, "reply", self._reply)
        monkeypatch.setattr(app, "show_loading", lambda *a, **k: None)
        monkeypatch.setattr(app.analyzer, "analyze", self._analyze)
        monkeypatch.setattr(app.analyzer, "plan", self._plan)
        bot = self

        class FakeBlob:
            def __init__(self, client):
                pass

            def get_message_content(self, message_id):
                data = bot.downloads.get(message_id, message_id.encode())
                if isinstance(data, Exception):
                    raise data
                return data

        monkeypatch.setattr(app, "MessagingApiBlob", FakeBlob)
        self.app = app

    # ---- 假的外部服務 ----
    def _reply(self, token, text, with_quick_reply=False, quick=None):
        buttons = quick or (self.app.MEAL_QUICK if with_quick_reply else [])
        self.replies.append({"token": token, "text": text, "buttons": list(buttons)})

    def _analyze(self, **kwargs):
        self.analyze_calls.append(kwargs)
        result = self.analyze_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def _plan(self, metrics, prev, goal_note):
        self.plan_calls.append((metrics, prev, goal_note))
        result = self.plan_results.pop(0) if self.plan_results else nutrition_plan()
        if isinstance(result, Exception):
            raise result
        return result

    # ---- 使用者動作 ----
    def text(self, text: str, user: str = USER, token: str = "tok"):
        self.app.on_text(NS(source=NS(user_id=user), reply_token=token,
                            message=NS(text=text)))
        return self.last

    def photo(self, message_id: str = "IMG", user: str = USER, token: str = "tok",
              set_id: str | None = None, index: int = 1, total: int = 1):
        image_set = NS(id=set_id, index=index, total=total) if set_id else None
        self.app.on_image(NS(source=NS(user_id=user), reply_token=token,
                             message=NS(id=message_id, image_set=image_set)))
        return self.last

    @property
    def last(self) -> dict | None:
        return self.replies[-1] if self.replies else None

    @property
    def storage(self) -> Storage:
        return self.app.storage


@pytest.fixture
def bot(monkeypatch) -> Bot:
    return Bot(monkeypatch)
