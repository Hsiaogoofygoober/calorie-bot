"""Bot 對話流程（端對端，外部服務全部是假的）。"""
import threading
import time

from conftest import USER, body_report, food, other

RICE = ("白飯", "全穀澱粉", 200, 183)
CHICKEN = ("煎雞胸", "蛋白質", 100, 165)
TOFU = ("煎豆腐", "蛋白質", 80, 130)


# ---------- 傳照片 → 補充說明 → 記錄 ----------

def test_photo_asks_for_note_before_analyzing(bot):
    r = bot.photo("A")
    assert "要補充說明嗎" in r["text"]
    assert r["buttons"] == ["直接分析", "換照片", "取消"]
    assert bot.analyze_calls == []          # 還沒分析


def test_note_is_sent_with_photo(bot):
    bot.analyze_results = [food(RICE, CHICKEN)]
    bot.photo("A")
    r = bot.text("肉是煎雞胸")
    assert bot.analyze_calls[0]["images"] == [b"A"]
    assert bot.analyze_calls[0]["note"] == "肉是煎雞胸"
    assert "🍱 已記錄" in r["text"] and "煎雞胸" in r["text"]
    assert r["buttons"] == ["修改上一筆", "換照片", "今日"]
    assert bot.storage.today_total(USER) == round(200 * 1.83) + 165


def test_analyze_now_sends_no_note(bot):
    bot.analyze_results = [food(RICE)]
    bot.photo("A")
    bot.text("直接分析")
    assert bot.analyze_calls[0]["note"] is None


def test_commands_while_waiting_keep_the_photo(bot):
    bot.analyze_results = [food(RICE)]
    bot.photo("A")
    assert "今天還沒有紀錄" in bot.text("今日")["text"]
    bot.text("飯只吃一半")
    assert bot.analyze_calls[0]["images"] == [b"A"]
    assert bot.analyze_calls[0]["note"] == "飯只吃一半"


def test_cancel_discards_photo(bot):
    bot.photo("A")
    assert "不記錄" in bot.text("取消")["text"]
    bot.analyze_results = [food(RICE)]
    bot.text("一碗白飯")                     # 之後的文字不會被當成補充說明
    assert bot.analyze_calls[0]["images"] == [] and bot.analyze_calls[0]["text"] == "一碗白飯"


def test_expired_photo_is_not_used(bot):
    bot.photo("A")
    bot.app._state[USER]["ts"] = time.time() - 31 * 60
    bot.analyze_results = [food(RICE)]
    bot.text("一碗白飯")
    assert bot.analyze_calls[0]["images"] == []


def test_non_food_is_not_recorded(bot):
    bot.analyze_results = [other()]
    bot.photo("A")
    assert "看不出是食物" in bot.text("直接分析")["text"]
    assert bot.storage.last_meal(USER) is None


def test_ai_failure_replies_politely_and_records_nothing(bot):
    bot.analyze_results = [RuntimeError("503")]
    bot.photo("A")
    assert "辨識失敗" in bot.text("直接分析")["text"]
    assert bot.storage.last_meal(USER) is None


def test_text_meal_without_photo(bot):
    bot.analyze_results = [food(("珍珠奶茶", "其他", 700, 68))]
    assert "珍珠奶茶" in bot.text("半糖珍奶大杯")["text"]
    assert bot.analyze_calls[0]["text"] == "半糖珍奶大杯"


# ---------- 多張照片 ----------

def test_batch_replies_once_when_all_arrive(bot):
    assert bot.photo("P1", set_id="S", index=1, total=3) is None
    bot.photo("P2", set_id="S", index=2, total=3)
    assert bot.replies == []                 # 還沒到齊不回覆
    r = bot.photo("P3", set_id="S", index=3, total=3)
    assert len(bot.replies) == 1 and "收到 3 張照片" in r["text"]
    bot.analyze_results = [food(RICE)]
    assert "已記錄（3 張照片）" in bot.text("直接分析")["text"]
    assert bot.analyze_calls[0]["images"] == [b"P1", b"P2", b"P3"]


def test_batch_arriving_in_parallel_replies_once(bot):
    threads = [threading.Thread(target=bot.photo, args=(f"P{i}",),
                                kwargs={"set_id": "S", "index": i, "total": 5, "token": f"t{i}"})
               for i in range(1, 6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(bot.replies) == 1 and "收到 5 張照片" in bot.last["text"]
    assert sorted(bot.app._state[USER]["images"]) == [f"P{i}".encode() for i in range(1, 6)]


def test_photos_one_by_one_accumulate(bot):
    assert "收到照片" in bot.photo("A")["text"]
    assert "收到 2 張照片" in bot.photo("B")["text"]
    bot.analyze_results = [food(RICE)]
    bot.text("直接分析")
    assert bot.analyze_calls[0]["images"] == [b"A", b"B"]


def test_max_photos_and_failed_download(bot):
    bot.downloads["BAD"] = IOError("download failed")
    ids = ["P1", "P2", "BAD", "P4", "P5", "P6", "P7", "P8"]
    for i, mid in enumerate(ids, 1):
        bot.photo(mid, set_id="S", index=i, total=len(ids))
    text = bot.last["text"]
    assert "收到 6 張照片" in text and "1 張照片下載失敗" in text and "多出的 1 張" in text
    assert len(bot.app._state[USER]["images"]) == bot.app.MAX_PHOTOS


def test_all_downloads_failed(bot):
    bot.downloads["BAD"] = IOError("download failed")
    assert "下載失敗" in bot.photo("BAD")["text"]
    assert USER not in bot.app._state


def test_replace_photo_clears_whole_batch(bot):
    bot.photo("A")
    bot.photo("B")
    assert "這 2 張照片都不記錄" in bot.text("換照片")["text"]
    bot.photo("C")
    bot.analyze_results = [food(RICE)]
    bot.text("直接分析")
    assert bot.analyze_calls[0]["images"] == [b"C"]


# ---------- 修改上一筆、換照片 ----------

def test_fix_sends_photos_previous_items_and_correction(bot):
    bot.analyze_results = [food(RICE, TOFU), food(RICE, CHICKEN)]
    bot.photo("A")
    bot.text("直接分析")
    assert "煎豆腐" in bot.text("修改上一筆")["text"]
    r = bot.text("豆腐其實是煎雞胸")
    call = bot.analyze_calls[1]
    assert call["images"] == [b"A"] and call["correction"] == "豆腐其實是煎雞胸"
    assert [p["name"] for p in call["previous"]] == ["白飯", "煎豆腐"]
    assert "已修改上一筆" in r["text"]
    assert [i["name"] for i in bot.storage.last_meal(USER)["items"]] == ["白飯", "煎雞胸"]
    assert len(bot.storage.today_meals(USER)) == 1    # 改同一筆，不是新增


def test_fix_can_repeat(bot):
    bot.analyze_results = [food(RICE), food(RICE), food(("白飯", "全穀澱粉", 100, 183))]
    bot.photo("A")
    bot.text("直接分析")
    bot.text("修改：雞腿比較小")
    bot.text("修改：飯只吃半碗")
    assert bot.analyze_calls[2]["images"] == [b"A"]
    assert bot.storage.last_meal(USER)["items"][0]["grams"] == 100


def test_fix_without_meal(bot):
    assert "沒有可以修改" in bot.text("修改上一筆")["text"]


def test_fix_after_restart_uses_saved_items(bot):
    bot.analyze_results = [food(RICE), food(("白飯", "全穀澱粉", 100, 183))]
    bot.photo("A")
    bot.text("直接分析")
    bot.app._last_meal.clear()               # 模擬 Bot 重新啟動，照片不見了
    bot.text("修改：飯只吃半碗")
    call = bot.analyze_calls[1]
    assert call["images"] is None and call["previous"][0]["name"] == "白飯"


def test_replace_recorded_photo_deletes_meal(bot):
    bot.analyze_results = [food(RICE)]
    bot.photo("A")
    bot.text("直接分析")
    assert "已刪除上一筆" in bot.text("換照片")["text"]
    assert bot.storage.last_meal(USER) is None


def test_photos_during_fix_delete_last_meal_only_once(bot):
    bot.analyze_results = [food(RICE), food(CHICKEN)]
    bot.photo("A"); bot.text("直接分析")
    bot.photo("B"); bot.text("直接分析")
    bot.text("修改上一筆")
    threads = [threading.Thread(target=bot.photo, args=(f"N{i}",),
                                kwargs={"set_id": "S", "index": i, "total": 2})
               for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(bot.storage.today_meals(USER)) == 1   # 只刪掉 B 那一筆
    assert "已刪除上一筆" in bot.last["text"]


def test_delete_last(bot):
    bot.analyze_results = [food(RICE)]
    bot.photo("A")
    bot.text("直接分析")
    assert "已刪除上一筆" in bot.text("刪除上一筆")["text"]
    assert bot.storage.today_total(USER) == 0


# ---------- 身體報告與營養師 ----------

def test_body_report_creates_plan_and_goals(bot):
    bot.analyze_results = [body_report()]
    bot.photo("REPORT")
    r = bot.text("想減脂、每週重訓兩次")
    metrics, prev, note = bot.plan_calls[0]
    assert metrics.weight_kg == 56.6 and prev is None and "每週重訓兩次" in note
    assert "已更新身體狀態" in r["text"] and "營養師的每日規劃" in r["text"]
    assert bot.storage.get_goal(USER) == 1400
    assert bot.storage.get_macro_goals(USER) == {"protein": 90, "carb": 150, "fat": 45}


def test_body_plan_failure_falls_back_to_rules(bot):
    bot.analyze_results = [body_report()]
    bot.plan_results = [RuntimeError("AI down")]
    bot.photo("REPORT")
    r = bot.text("直接分析")
    assert "固定規則" in r["text"]
    assert bot.storage.get_goal(USER) == 1380        # 1680 − 300


def test_unsafe_ai_plan_is_corrected(bot):
    from conftest import nutrition_plan
    bot.analyze_results = [body_report()]
    bot.plan_results = [nutrition_plan(kcal=900, protein_g=300)]
    bot.photo("REPORT")
    r = bot.text("直接分析")
    assert bot.storage.get_goal(USER) >= 1273           # 不低於基礎代謝
    assert bot.storage.get_macro_goals(USER)["protein"] <= round(56.6 * 2.2)
    assert "🛡️" in r["text"]


def test_second_report_passes_previous(bot):
    bot.analyze_results = [body_report(), body_report(weight_kg=56.0)]
    bot.photo("R1"); bot.text("直接分析")
    bot.photo("R2"); r = bot.text("直接分析")
    assert bot.plan_calls[1][1].weight_kg == 56.6
    assert "-0.6kg" in r["text"]


def test_status_and_plan_without_data_offer_intake(bot):
    for command in ("狀態", "營養計畫"):
        r = bot.text(command)
        assert "填寫基本資料" in r["buttons"]


# ---------- 問答填寫基本資料 ----------

def test_intake_full_conversation(bot):
    assert "1/6" in bot.text("基本資料")["text"]
    bot.text("男性")
    assert "好像不太對" in bot.text("二十五")["text"]     # 看不懂會重問同一題
    bot.text("25")
    bot.text("173cm")
    bot.text("60公斤")
    assert "久坐" in bot.last["buttons"]
    bot.text("中度活動")
    r = bot.text("想減脂但保留肌肉")
    assert "BMR：1561" in r["text"] and "TDEE：2420" in r["text"]
    metrics, _, note = bot.plan_calls[0]
    assert metrics.bmr_kcal == 1561 and "想減脂但保留肌肉" in note and "25 歲" in note
    assert bot.storage.get_profile(USER)["height"] == 173
    assert bot.analyze_calls == []                        # 問答過程不呼叫看圖 AI


def test_intake_can_be_cancelled(bot):
    bot.text("基本資料")
    bot.text("女性")
    bot.text("取消")
    bot.analyze_results = [food(RICE)]
    bot.text("40")                                        # 不會被當成年齡
    assert bot.analyze_calls[0]["text"] == "40"
    assert bot.storage.get_profile(USER) is None


def test_profile_is_used_for_later_body_report(bot):
    for answer in ("基本資料", "女性", "40", "160", "55", "久坐", "跳過"):
        bot.text(answer)
    bot.analyze_results = [body_report()]
    bot.photo("REPORT")
    bot.text("直接分析")
    assert "女性、40 歲、身高 160 cm" in bot.plan_calls[1][2]


# ---------- 其他 ----------

def test_users_do_not_share_state(bot):
    bot.photo("A", user="mom")
    bot.analyze_results = [food(RICE)]
    bot.text("一碗白飯", user="dad")
    assert bot.analyze_calls[0]["images"] == []           # 媽媽的照片不會跑到爸爸那裡
    assert "mom" in bot.app._state


def test_follow_event_sends_welcome(bot):
    from types import SimpleNamespace as NS
    bot.app.on_follow(NS(reply_token="tok", source=NS(user_id=USER)))
    assert "歡迎使用" in bot.last["text"] and "填寫基本資料" in bot.last["buttons"]


def test_remaining_line_after_meal(bot):
    bot.storage.set_plan(USER, {"kcal": 1400, "protein_g": 90, "carb_g": 150, "fat_g": 45})
    bot.analyze_results = [food(CHICKEN)]
    r = bot.text("一塊煎雞胸")
    assert "今日 165 / 1400 kcal｜剩餘 1235 kcal" in r["text"]
    assert "蛋白質 10/90g" in r["text"]
