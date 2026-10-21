"""LINE 熱量紀錄 Bot。

啟動：uvicorn app:app --port 8000
"""
import logging
import os
import re
import threading
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient, Configuration, MessageAction, MessagingApi, MessagingApiBlob,
    QuickReply, QuickReplyItem, ReplyMessageRequest, ShowLoadingAnimationRequest, TextMessage,
)
from linebot.v3.webhooks import (
    FollowEvent, ImageMessageContent, MessageEvent, TextMessageContent,
)

import body
from analyzer import Analysis, Analyzer, BodyMetrics, Kind
from nutrition import NutritionDB
from storage import Storage

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calorie-bot")

line_config = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
# 預設熱量完全由 AI 估計；設 USE_NUTRITION_DB=true 則資料庫查得到的優先
db = NutritionDB() if os.getenv("USE_NUTRITION_DB", "false").lower() == "true" else None
analyzer = Analyzer(os.environ["GEMINI_API_KEY"],
                    os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), db,
                    fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash"))
storage = Storage(os.getenv("DB_PATH", "calorie.db"),
                  int(os.getenv("DEFAULT_GOAL_KCAL", "1800")))

app = FastAPI()

HELP_TEXT = (
    "📷 傳餐點照片（把手放在旁邊當比例尺），或直接打字（例：半糖珍奶大杯）就會記錄，"
    "並用 211 餐盤（蔬菜½、蛋白質¼、全穀澱粉¼）分析\n"
    "　傳照片後可以補充說明（例：肉是煎雞胸、飯只吃一半）\n"
    "📊 傳體脂計截圖，AI 營養師會規劃你的每日熱量與營養素\n"
    "　可以補充目標（例：想減脂、每週重訓兩次）\n\n"
    "・修改上一筆：AI 判斷錯了，直接跟它說哪裡錯\n"
    "・換照片：照片傳錯了\n"
    "・刪除上一筆\n"
    "・今日／狀態／營養計畫\n"
    "・目標 1800：手動設定每日熱量"
)
MEAL_QUICK = ["修改上一筆", "換照片", "今日"]
ANALYZE_NOW, CANCEL = "直接分析", "取消"
NOTE_QUICK = [ANALYZE_NOW, CANCEL]
SKIP_WORDS = {ANALYZE_NOW, "不用", "沒有", "不用補充", "否", "no", "No"}
DISCLAIMER = "※ 體脂計數值與 AI 建議僅供參考，有慢性病（如腎臟病、糖尿病）請先諮詢醫師"


@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body_text = (await request.body()).decode("utf-8")
    try:
        await run_in_threadpool(handler.handle, body_text, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"


@app.get("/")
def health():
    return {"status": "ok"}


# ---------- 對話狀態（只放記憶體、不寫硬碟；Bot 重啟就清空） ----------
# _state：正在等使用者回覆的事
#   {"mode": "note", "image": bytes}：照片等補充說明
#   {"mode": "fix"}：等使用者說上一筆哪裡錯
# _last_meal：最近一筆紀錄的原始輸入（照片／文字），修改時讓 AI 重看一次
STATE_TTL = 30 * 60       # 超過 30 分鐘沒回應就放棄，避免之後的文字被誤判
LAST_MEAL_TTL = 6 * 3600  # 6 小時內的紀錄還能帶照片重新判斷
_state: dict[str, dict] = {}
_last_meal: dict[str, dict] = {}
_lock = threading.Lock()


def set_state(user_id: str, **state) -> None:
    with _lock:
        _state[user_id] = {**state, "ts": time.time()}


def peek_state(user_id: str) -> dict | None:
    with _lock:
        s = _state.get(user_id)
    return s if s and time.time() - s["ts"] < STATE_TTL else None


def pop_state(user_id: str) -> tuple[dict | None, bool]:
    """取出狀態；回傳 (狀態或 None, 是否因逾時被丟棄)。"""
    with _lock:
        s = _state.pop(user_id, None)
    if not s:
        return None, False
    if time.time() - s["ts"] > STATE_TTL:
        return None, True
    return s, False


def remember_meal(user_id: str, meal_id: int, image: bytes | None,
                  text: str | None, note: str | None) -> None:
    with _lock:
        _last_meal[user_id] = {"meal_id": meal_id, "image": image, "text": text,
                               "note": note, "ts": time.time()}


def recall_meal(user_id: str) -> dict | None:
    with _lock:
        m = _last_meal.get(user_id)
    return m if m and time.time() - m["ts"] < LAST_MEAL_TTL else None


def forget_meal(user_id: str) -> None:
    with _lock:
        _last_meal.pop(user_id, None)


# ---------- 回覆 ----------

def quick_reply(labels: list[str]) -> QuickReply:
    return QuickReply(items=[QuickReplyItem(action=MessageAction(label=l, text=l)) for l in labels])


def show_loading(user_id: str, seconds: int = 30) -> None:
    """聊天室先顯示「…」載入動畫，Bot 回覆時自動消失（只支援一對一聊天）。"""
    try:
        with ApiClient(line_config) as client:
            MessagingApi(client).show_loading_animation(
                ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=seconds)
            )
    except Exception:
        log.warning("無法顯示載入動畫", exc_info=True)


def reply(reply_token: str, text: str, with_quick_reply: bool = False,
          quick: list[str] | None = None) -> None:
    """with_quick_reply：附上記錄後的調整按鈕；quick：自訂按鈕。"""
    labels = quick or (MEAL_QUICK if with_quick_reply else None)
    msg = TextMessage(text=text, quick_reply=quick_reply(labels) if labels else None)
    with ApiClient(line_config) as client:
        MessagingApi(client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[msg])
        )


CATEGORY_ICON = {"蔬菜": "🥬", "蛋白質": "🍗", "全穀澱粉": "🍚", "其他": "・"}


def format_items(items: list[dict]) -> str:
    lines = []
    for i in items:
        # 只有混用資料庫時才需要標示哪些是 AI 估的
        mark = "（AI估）" if db and i["source"] == "ai" else ""
        icon = CATEGORY_ICON.get(i.get("category"), "・")
        lines.append(f"{icon}{i['name']} {i['grams']}g … {i['kcal']} kcal{mark}")
    return "\n".join(lines)


def macros_line(items: list[dict]) -> str:
    p = sum(i["protein_g"] for i in items)
    c = sum(i["carb_g"] for i in items)
    f = sum(i["fat_g"] for i in items)
    return f"蛋白質 {p:.0f}g｜碳水 {c:.0f}g｜脂肪 {f:.0f}g"


def plate_line(plate) -> str:
    return (f"🍽️ 211 餐盤：蔬菜 {plate.veg_pct:.0f}%｜蛋白質 {plate.protein_pct:.0f}%"
            f"｜澱粉 {plate.starch_pct:.0f}%\n　　（理想 50%｜25%｜25%）")


def remaining_line(user_id: str) -> str:
    total = storage.today_total(user_id)
    goal = storage.get_goal(user_id)
    left = goal - total
    status = f"剩餘 {left:.0f}" if left >= 0 else f"超過 {-left:.0f}"
    line = f"今日 {total:.0f} / {goal} kcal｜{status} kcal"
    goals, today = storage.get_macro_goals(user_id), storage.today_macros(user_id)
    names = {"protein": "蛋白質", "carb": "碳水", "fat": "脂肪"}
    parts = [f"{label} {today[k]:.0f}/{goals[k]}g" for k, label in names.items() if goals[k]]
    if parts:
        line += "\n今日 " + "｜".join(parts)
    return line


def meal_message(title: str, user_id: str, items: list[dict],
                 analysis: Analysis | None = None) -> str:
    msg = f"{title}\n{format_items(items)}\n━━━━━━━━\n"
    if analysis and analysis.plate:
        msg += f"{plate_line(analysis.plate)}\n"
    if analysis and analysis.advice:
        msg += f"💬 {analysis.advice}\n"
    msg += (f"━━━━━━━━\n本餐 {sum(i['kcal'] for i in items)} kcal\n"
            f"{macros_line(items)}\n{remaining_line(user_id)}")
    if analysis and analysis.question:
        msg += f"\n\n❓ {analysis.question}（可按「修改上一筆」告訴我）"
    return msg


def latest_body(user_id: str) -> tuple[BodyMetrics | None, BodyMetrics | None, str | None]:
    """回傳 (最新報告, 前一份報告, 最新報告日期)。"""
    reports = storage.latest_body_reports(user_id, 2)
    metrics = [BodyMetrics.model_validate(r["metrics"]) for r in reports]
    date = reports[0]["created_at"][:10] if reports else None
    return (metrics[0] if metrics else None,
            metrics[1] if len(metrics) > 1 else None, date)


def user_context(user_id: str) -> str:
    current, _, _ = latest_body(user_id)
    return body.context_line(
        current, storage.get_goal(user_id), storage.get_macro_goals(user_id),
        storage.today_total(user_id), storage.today_macros(user_id),
    )


# ---------- 分析 ----------

def handle_input(user_id: str, reply_token: str, image: bytes | None = None,
                 text: str | None = None, note: str | None = None) -> None:
    """text：純文字描述的餐點；note：家人對照片的補充說明。"""
    try:
        analysis = analyzer.analyze(image=image, text=text, note=note,
                                    context=user_context(user_id))
    except Exception:
        log.exception("Gemini 分析失敗")
        reply(reply_token, "抱歉，辨識失敗了，請稍後再試一次 🙏")
        return

    if analysis.kind == Kind.body and analysis.body:
        save_body_report(user_id, reply_token, analysis.body, goal_note=note)
    elif analysis.kind == Kind.food and analysis.items:
        items = analyzer.build_items(analysis)
        meal_id = storage.add_meal(user_id, items)
        remember_meal(user_id, meal_id, image, text, note)
        reply(reply_token, meal_message("🍱 已記錄", user_id, items, analysis),
              with_quick_reply=True)
    else:
        reply(reply_token, "看不出是食物或身體報告喔～\n\n" + HELP_TEXT)


def apply_fix(user_id: str, reply_token: str, correction: str) -> None:
    """依使用者的說明修正上一筆：把原始照片、上次結果和修正一起交給 AI。"""
    source = recall_meal(user_id)
    meal = storage.get_meal(source["meal_id"], user_id) if source else None
    if not meal:  # Bot 重啟過或超過 6 小時：沒有原始照片，只根據上次的結果修改
        source, meal = None, storage.last_meal(user_id)
    if not meal:
        reply(reply_token, "今天還沒有可以修改的紀錄喔")
        return

    show_loading(user_id)
    try:
        analysis = analyzer.analyze(
            image=source["image"] if source else None,
            text=source["text"] if source else "（原始照片已不在，請依上一次的結果修改）",
            note=source["note"] if source else None,
            context=user_context(user_id), previous=meal["items"], correction=correction,
        )
    except Exception:
        log.exception("Gemini 修改失敗")
        reply(reply_token, "抱歉，修改失敗了，請再說一次哪裡要改 🙏", quick=["修改上一筆"])
        return
    if analysis.kind != Kind.food or not analysis.items:
        reply(reply_token, "AI 沒看懂要怎麼改，請換個說法再試一次 🙏", quick=["修改上一筆"])
        return

    items = analyzer.build_items(analysis)
    storage.update_meal(meal["id"], items)
    if source:
        remember_meal(user_id, meal["id"], source["image"], source["text"], source["note"])
    reply(reply_token, meal_message("✏️ 已修改上一筆", user_id, items, analysis),
          with_quick_reply=True)


def save_body_report(user_id: str, reply_token: str, metrics: BodyMetrics,
                     goal_note: str | None = None) -> None:
    prev, _, prev_date = latest_body(user_id)
    storage.add_body_report(user_id, metrics.model_dump())

    show_loading(user_id, 60)  # 營養規劃要多想一下
    try:
        plan = analyzer.plan(metrics, prev, goal_note).model_dump()
        plan["source"] = "ai"
    except Exception:
        log.exception("AI 營養規劃失敗，改用固定規則")
        plan = body.rules_plan(metrics)

    msg = "📊 已更新身體狀態\n" + body.format_report(metrics, prev)
    if prev_date:
        msg += f"\n（括號內為與 {prev_date} 相比）"
    if plan:
        plan, adjustments = body.guard_plan(plan, metrics)
        plan["adjustments"] = adjustments
        storage.set_plan(user_id, plan)
        msg += "\n━━━━━━━━\n" + body.format_plan(plan)
    else:
        msg += "\n\n截圖裡沒有代謝數值，每日目標維持不變"
    reply(reply_token, msg + "\n\n" + DISCLAIMER)


def today_summary(user_id: str, reply_token: str) -> None:
    meals = storage.today_meals(user_id)
    if not meals:
        reply(reply_token, "今天還沒有紀錄喔，傳張食物照片試試看 📷")
        return
    parts = []
    for n, m in enumerate(meals, 1):
        hhmm = m["created_at"][11:16]
        names = "、".join(i["name"] for i in m["items"])
        parts.append(f"{n}. {hhmm} {names}（{m['total_kcal']:.0f} kcal）")
    all_items = [i for m in meals for i in m["items"]]
    reply(reply_token, "📋 今日紀錄\n" + "\n".join(parts)
          + f"\n━━━━━━━━\n{macros_line(all_items)}\n{remaining_line(user_id)}")


def body_status(user_id: str, reply_token: str) -> None:
    current, prev, date = latest_body(user_id)
    if not current:
        reply(reply_token, "還沒有身體狀態喔，傳一張體脂計的身體組成截圖給我 📊")
        return
    msg = f"📊 身體狀態（{date}）\n" + body.format_report(current, prev)
    msg += f"\n━━━━━━━━\n{remaining_line(user_id)}"
    if storage.get_plan(user_id):
        msg += "\n\n輸入「營養計畫」看營養師的完整規劃"
    reply(reply_token, msg, quick=["營養計畫"] if storage.get_plan(user_id) else None)


def show_plan(user_id: str, reply_token: str) -> None:
    plan = storage.get_plan(user_id)
    if not plan:
        reply(reply_token, "還沒有營養計畫喔，傳一張體脂計的身體組成截圖給我，"
                           "可以順便補充你的目標 📊")
        return
    reply(reply_token, body.format_plan(plan) + "\n\n" + DISCLAIMER)


# ---------- LINE 事件 ----------

ASK_NOTE = (
    "📷 收到照片！要補充說明嗎？\n"
    "例如：「肉是煎雞胸和煎魚」「飯只吃一半」「飲料無糖」\n"
    "體脂截圖可以補充目標：「想減脂、每週重訓兩次」\n\n"
    "直接打字補充，或按「直接分析」"
)
FIX_PROMPT = (
    "✏️ 上一筆記錄的是：\n{items}\n\n"
    "哪裡要改？直接跟我說，例如：\n"
    "「雞肉其實是煎豆腐」「飯只吃半碗」「少算了一杯無糖豆漿」「沒有吃青菜」"
)


@handler.add(FollowEvent)
def on_follow(event: FollowEvent):
    reply(event.reply_token, "👋 歡迎使用減脂小幫手！\n\n" + HELP_TEXT
          + "\n\n建議先傳一張體脂計截圖，讓營養師幫你規劃每日目標 📊")


@handler.add(MessageEvent, message=ImageMessageContent)
def on_image(event: MessageEvent):
    """先暫存照片並詢問補充說明；分析等家人回覆後再做。"""
    user_id = event.source.user_id
    with ApiClient(line_config) as client:
        image = bytes(MessagingApiBlob(client).get_message_content(event.message.id))

    state = peek_state(user_id)
    prefix = ""
    if state and state["mode"] == "note":
        prefix = "（已改用這張新照片，前一張不記錄）\n"
    elif state and state["mode"] == "fix":
        # 正在修改上一筆時傳照片 → 視為照片傳錯，換成這張
        meal = storage.last_meal(user_id)
        if meal:
            storage.delete_meal(meal["id"])
            forget_meal(user_id)
            prefix = "🗑️ 已刪除上一筆，改用這張新照片\n"
    set_state(user_id, mode="note", image=image)
    reply(event.reply_token, prefix + ASK_NOTE, quick=NOTE_QUICK)


@handler.add(MessageEvent, message=TextMessageContent)
def on_text(event: MessageEvent):
    user_id = event.source.user_id
    token = event.reply_token
    text = event.message.text.strip()

    # 指令照常執行，正在等的照片／修改繼續等
    if run_command(user_id, token, text):
        return

    state, expired = pop_state(user_id)
    if state and state["mode"] == "note":
        show_loading(user_id)
        handle_input(user_id, token, image=state["image"],
                     note=None if text in SKIP_WORDS else text)
    elif state and state["mode"] == "fix":
        apply_fix(user_id, token, text)
    elif m := re.fullmatch(r"(?:修改\s*[:：]?|改\s*[:：])\s*(.+)", text, re.S):
        apply_fix(user_id, token, m.group(1))  # 「修改：雞肉是豆腐」一句話直接改
    elif text in SKIP_WORDS:
        reply(token, "照片等太久（超過 30 分鐘）已經略過了，請重新傳一次 📷" if expired
              else "目前沒有等待分析的照片喔，傳張食物照片給我 📷")
    else:
        if expired:
            log.info("使用者 %s 的等待狀態逾時，已丟棄", user_id)
        show_loading(user_id)
        handle_input(user_id, token, text=text)


def run_command(user_id: str, token: str, text: str) -> bool:
    """處理固定指令；不是指令就回傳 False。"""
    if text in ("今日", "今天", "今日紀錄"):
        today_summary(user_id, token)
    elif text in ("狀態", "身體狀態", "我的狀態"):
        body_status(user_id, token)
    elif text in ("營養計畫", "計畫"):
        show_plan(user_id, token)
    elif text == "修改上一筆":
        state = peek_state(user_id)
        meal = storage.last_meal(user_id)
        if state and state["mode"] == "note":
            reply(token, "你有一張照片還沒分析，先按「直接分析」或「取消」喔", quick=NOTE_QUICK)
        elif not meal:
            reply(token, "今天還沒有可以修改的紀錄喔")
        else:
            set_state(user_id, mode="fix")
            reply(token, FIX_PROMPT.format(items=format_items(meal["items"])),
                  quick=[CANCEL])
    elif text == "換照片":
        state, _ = pop_state(user_id)
        meal = storage.last_meal(user_id)
        if state and state["mode"] == "note":
            reply(token, "好的，這張照片不記錄，請重新傳一張 📷")
        elif meal:
            storage.delete_meal(meal["id"])
            forget_meal(user_id)
            names = "、".join(i["name"] for i in meal["items"])
            reply(token, f"🗑️ 已刪除上一筆（{names}）\n請重新傳正確的照片 📷")
        else:
            reply(token, "目前沒有可以換的照片喔")
    elif text == CANCEL:
        state, _ = pop_state(user_id)
        reply(token, "已取消，這張照片不記錄" if state and state["mode"] == "note"
              else "已取消" if state else "目前沒有進行中的動作")
    elif text == "刪除上一筆":
        meal = storage.last_meal(user_id)
        if meal:
            storage.delete_meal(meal["id"])
            forget_meal(user_id)
            reply(token, f"🗑️ 已刪除上一筆\n{remaining_line(user_id)}")
        else:
            reply(token, "今天還沒有紀錄喔")
    elif m := re.fullmatch(r"目標\s*(\d{3,4})", text):
        storage.set_goal(user_id, int(m.group(1)))
        reply(token, f"🎯 每日目標已設為 {m.group(1)} kcal\n{remaining_line(user_id)}")
    elif text in ("說明", "使用說明", "help", "?", "？"):
        reply(token, HELP_TEXT)
    else:
        return False
    return True
