"""用 Gemini 分析照片／文字：食物（依 211 餐盤估份量、熱量、三大營養素）或體脂計的身體組成截圖。"""
from enum import Enum

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from nutrition import NutritionDB

# 資料庫名稱太多時不放進提示詞（避免每次都多花 token），改靠模糊比對
MAX_NAMES_IN_PROMPT = 300

SYSTEM_PROMPT = """你是台灣的飲食紀錄助理。先判斷輸入是哪一種（kind）：
- 食物：食物照片或文字描述的餐點
- 身體組成：體脂計／體重計 App 的身體組成報告截圖
- 其他：都不是

【食物】用「211 餐盤」原則分析：餐盤體積 1/2 蔬菜、1/4 蛋白質（豆魚蛋肉）、1/4 全穀澱粉。
照片通常有使用者的手放在旁邊當比例尺（成人手掌寬約 8 公分）。
只算使用者自己的那一份（個人餐盤或碗），背景的共用菜盤、別人的餐點不要算。
若有「使用者補充說明」，以補充說明為準，修正食物名稱、烹調方式、份量或吃了多少
（例：說「肉是煎雞胸和煎魚」就不要判斷成豆腐；說「飯只吃一半」就把飯的克數減半）。
1. 列出每一樣食物，每一道菜都要分開列，不要合併（例：肉末四季豆、炒空心菜、
   白菜滷豆皮是三項；雞肉和魚肉是兩項）。分隔餐盤要逐格檢查，一格裡有幾道菜就列幾項。
   主食、配菜、飲料、醬料也分開列。分類：
   蔬菜：葉菜、瓜類、菇類、海藻等（根莖類澱粉如馬鈴薯、地瓜、玉米、南瓜算全穀澱粉）
   蛋白質：豆、魚、蛋、肉、海鮮、豆製品
   全穀澱粉：飯、麵、麵包、根莖類
   其他：水果、乳品、飲料、甜點、油脂醬料
2. 估計每樣「實際入口」的重量（公克；飲料用 ml 當作公克）。
   台灣常見份量：一碗白飯約 200g、便當白飯約 250g、一顆滷蛋約 55g、
   一份燙青菜約 100g、手搖飲中杯 500ml、大杯 700ml、一片吐司約 30g。
   混合菜（如肉末四季豆）依主要成分分類，但熱量與營養素要包含裡面的肉。
3. 依實際烹調方式（油炸、勾芡、醬汁、含糖量）估計「每 100g」的熱量與蛋白質、碳水、脂肪，
   台式炒青菜通常含油，每 100g 約 60–100 kcal，不要當成水煮青菜；
   參考台灣衛福部食品營養成分資料庫。注意全部都是每 100g 的數值，不是整份；
   且 蛋白質×4 + 碳水×4 + 脂肪×9 要約等於每 100g 熱量。
4. db_name 請從「資料庫名稱」中挑最接近的；都不像或沒有提供清單就留空字串。
5. plate 填入蔬菜、蛋白質、全穀澱粉各佔餐盤體積的百分比（三者合計 100，不含「其他」類）。
6. advice 用一句話、口語地建議如何更接近 211；若有提供「使用者狀態」，
   要結合他的目標（例如蛋白質還差多少、今天熱量還剩多少）給建議。已經很好就稱讚一下。
7. 若份量或內容很不確定（例如看不出有沒有吃皮、含糖量），在 question 用一句話問使用者，否則留空。
body 設為 null。

【身體組成】把截圖上的數值逐一讀進 body，看不到的欄位填 null，不要自己推算。
activity_kcal 是「活動代謝」或「每日總消耗」；control 類欄位保留正負號（例：-6.3、+4.0 → 4.0）。
flags 列出被標示為「偏低」或「偏高」的項目，例如「蛋白質率偏低」。
items 留空、plate 設為 null、advice 和 question 留空。

【其他】items 留空、plate 和 body 設為 null、advice 和 question 留空。"""


class Kind(str, Enum):
    food = "食物"
    body = "身體組成"
    other = "其他"


class Category(str, Enum):
    veg = "蔬菜"
    protein = "蛋白質"
    starch = "全穀澱粉"
    other = "其他"


class FoodItem(BaseModel):
    name: str = Field(description="食物名稱（繁體中文）")
    category: Category
    db_name: str = Field(description="最接近的資料庫名稱，沒有就空字串")
    grams: float = Field(description="這一份的重量")
    est_kcal_per_100g: float
    protein_per_100g: float
    carb_per_100g: float
    fat_per_100g: float


class PlateRatio(BaseModel):
    veg_pct: float
    protein_pct: float
    starch_pct: float


# Gemini 的 response_schema 不支援預設值，所以欄位都是「必填但可為 null」
class BodyMetrics(BaseModel):
    weight_kg: float | None
    bmi: float | None
    body_fat_pct: float | None
    water_pct: float | None
    skeletal_muscle_pct: float | None
    protein_pct: float | None
    muscle_pct: float | None
    visceral_fat: float | None
    subcutaneous_fat_kg: float | None
    fat_free_mass_kg: float | None
    bmr_kcal: float | None = Field(description="基礎代謝")
    activity_kcal: float | None = Field(description="活動代謝／每日總消耗")
    body_age: float | None
    standard_weight_kg: float | None
    weight_control_kg: float | None
    fat_control_kg: float | None
    muscle_control_kg: float | None
    flags: list[str]


class Analysis(BaseModel):
    kind: Kind
    items: list[FoodItem]
    plate: PlateRatio | None
    advice: str
    question: str
    body: BodyMetrics | None


PLAN_PROMPT = """你是台灣的專業營養師。依使用者的身體組成數據、他說的目標（若有）、
以及與上一次數據相比的變化，規劃每日飲食。

規則：
- 每日熱量不可低於基礎代謝；減脂時每日赤字約 300–500 kcal，不要極端節食。
- 「活動代謝」若有，視為每日總消耗。
- 蛋白質 1.2–2.0 g/kg 體重；需要增肌（肌肉偏低、肌肉控制為正）取較高值。
- 脂肪約佔總熱量 20–35%；其餘給碳水，以全穀、根莖類為主。
- 蛋白質×4 + 碳水×4 + 脂肪×9 要約等於每日熱量（誤差 5% 內）。
- 飲食型態配合「211 餐盤」（蔬菜½、蛋白質¼、全穀澱粉¼）。
- 使用者沒說目標時，依報告的體重控制、脂肪控制、肌肉控制推斷。
- meals 把每日熱量分配到早餐、午餐、晚餐（需要時加點心），合計等於每日熱量，
  suggestion 用台灣常見食物舉具體例子。
- summary 用 2 句評估現況；strategy 用 2 句說明為什麼這樣訂；tips 給 3 條具體可做的建議。
- caution：若有需要注意的狀況（例：內臟脂肪偏高、極端數值）或建議就醫諮詢的情形就寫，否則留空。
- 用繁體中文、口語、親切，不要太長。"""


class MealPlan(BaseModel):
    name: str = Field(description="早餐／午餐／晚餐／點心")
    kcal: int
    suggestion: str


class NutritionPlan(BaseModel):
    kcal: int
    protein_g: int
    carb_g: int
    fat_g: int
    fiber_g: int
    water_ml: int
    meals: list[MealPlan]
    summary: str
    strategy: str
    tips: list[str]
    caution: str


class Analyzer:
    def __init__(self, api_key: str, model: str, db: NutritionDB | None = None,
                 fallback_model: str | None = None):
        """db 為 None 時熱量完全由 AI 估計；有 db 時資料庫查得到的優先。
        主模型忙碌（503 等）時改用 fallback_model，避免家人等太久。"""
        # 不重試、直接換備援模型，並設逾時：LINE 的 reply token 約 1 分鐘就失效
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=25_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.models = [m for m in (model, fallback_model) if m]
        self.db = db
        system = SYSTEM_PROMPT
        if db and len(db.names) <= MAX_NAMES_IN_PROMPT:
            system += "\n\n資料庫名稱：" + "、".join(db.names)
        self.config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=Analysis,
            temperature=0.2,
            # 看圖估份量不需要深度推理；降低思考與圖片解析度可省幾秒
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            media_resolution="MEDIA_RESOLUTION_MEDIUM",
        )
        # 營養規劃一次只有幾百字、不常用，給多一點思考換取品質
        self.plan_config = types.GenerateContentConfig(
            system_instruction=PLAN_PROMPT,
            response_mime_type="application/json",
            response_schema=NutritionPlan,
            temperature=0.3,
            thinking_config=types.ThinkingConfig(thinking_level="MEDIUM"),
        )

    def _generate(self, contents: list, config: types.GenerateContentConfig):
        """依序嘗試主模型、備援模型，回傳解析後的物件。"""
        last_error: Exception | None = None
        for model in self.models:
            try:
                resp = self.client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                if resp.parsed is None:
                    raise ValueError(f"Gemini 回傳無法解析：{resp.text!r}")
                self.last_model = model
                return resp.parsed
            except Exception as e:  # 換下一個模型再試
                last_error = e
        raise last_error

    def analyze(self, image: bytes | None = None, text: str | None = None,
                mime_type: str = "image/jpeg", context: str | None = None,
                note: str | None = None, previous: list[dict] | None = None,
                correction: str | None = None) -> Analysis:
        """note：對照片的補充說明；context：使用者狀態與今日進度。
        previous + correction：修正上一次的分析（使用者指出哪裡錯）。"""
        contents: list = []
        if image:
            contents.append(types.Part.from_bytes(data=image, mime_type=mime_type))
        prompt = text or "請分析這張圖片。"
        if note:
            prompt += f"\n\n使用者補充說明（以此為準）：{note}"
        if previous is not None and correction:
            prev = "\n".join(f"- {p['name']}（{p.get('category', '')}）{p['grams']}g {p['kcal']}kcal"
                             for p in previous)
            prompt += (f"\n\n你上一次的分析結果：\n{prev}\n\n"
                       f"使用者指出的錯誤（以此為準修正）：{correction}\n"
                       "請依修正重新輸出這一餐的完整結果：使用者沒提到的項目維持原樣，"
                       "提到的項目修改名稱、分類、份量或烹調方式；說少算了就新增、說沒吃就移除。")
        if context:
            prompt += f"\n\n使用者狀態：{context}"
        contents.append(prompt)
        return self._generate(contents, self.config)

    def plan(self, metrics: BodyMetrics, prev: BodyMetrics | None = None,
             goal_note: str | None = None) -> NutritionPlan:
        """以營養師角色，依身體組成規劃每日熱量與營養素。"""
        data = {k: v for k, v in metrics.model_dump().items() if v not in (None, [])}
        prompt = f"身體組成數據：{data}"
        if prev:
            old = {k: v for k, v in prev.model_dump().items() if v not in (None, []) and k != "flags"}
            prompt += f"\n上一次的數據：{old}"
        prompt += f"\n使用者的目標與補充：{goal_note}" if goal_note else "\n使用者沒有特別說明目標。"
        return self._generate([prompt], self.plan_config)

    def build_items(self, analysis: Analysis) -> list[dict]:
        """把模型的辨識結果換成帳本項目；有資料庫時熱量優先用資料庫。"""
        items = []
        for it in analysis.items:
            hit = self.db.lookup(it.db_name, it.name) if self.db else None
            if hit:
                db_name, per100, source = hit[0], hit[1], "db"
            else:
                db_name, per100, source = "", it.est_kcal_per_100g, "ai"
            items.append({
                "name": it.name,
                "category": it.category.value,
                "db_name": db_name,
                "grams": round(it.grams),
                "kcal_per_100g": per100,
                "kcal": round(it.grams * per100 / 100),
                # 整份營養素 = 克數 × 每 100g 數值，避免模型把每 100g 當成整份
                "protein_g": round(it.grams * it.protein_per_100g / 100, 1),
                "carb_g": round(it.grams * it.carb_per_100g / 100, 1),
                "fat_g": round(it.grams * it.fat_per_100g / 100, 1),
                "source": source,
            })
        return items
