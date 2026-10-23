"""資料庫：舊資料庫遷移、餐點、目標、基本資料。"""
import sqlite3

from storage import Storage

U = "U1"


def item(kcal=100, protein=10.0):
    return {"name": "飯", "category": "全穀澱粉", "grams": 100, "kcal": kcal,
            "kcal_per_100g": kcal, "protein_g": protein, "carb_g": 20.0, "fat_g": 5.0}


def test_migrates_old_database_without_losing_data(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (user_id TEXT PRIMARY KEY, goal_kcal INTEGER NOT NULL, protein_goal_g INTEGER);
        INSERT INTO users VALUES ('U1', 1500, 80);
    """)
    old.commit()
    old.close()

    s = Storage(str(path), 1800)
    cols = {r[1] for r in s.conn.execute("PRAGMA table_info(users)")}
    assert {"carb_goal_g", "fat_goal_g", "plan_json", "profile_json"} <= cols
    assert s.get_goal("U1") == 1500 and s.get_protein_goal("U1") == 80
    Storage(str(path), 1800)  # 再開一次不會出錯


def test_meal_add_update_delete_and_totals():
    s = Storage(":memory:", 1800)
    meal_id = s.add_meal(U, [item(300), item(200)])
    assert s.today_total(U) == 500
    s.update_meal(meal_id, [item(100)])
    assert s.today_total(U) == 100
    assert s.get_meal(meal_id, U)["items"][0]["kcal"] == 100
    assert s.get_meal(meal_id, "someone-else") is None
    s.delete_meal(meal_id)
    assert s.last_meal(U) is None and s.today_total(U) == 0


def test_users_are_separated():
    s = Storage(":memory:", 1800)
    s.add_meal("A", [item(300)])
    assert s.today_total("B") == 0 and s.last_meal("B") is None


def test_plan_sets_all_goals():
    s = Storage(":memory:", 1800)
    s.set_plan(U, {"kcal": 1400, "protein_g": 90, "carb_g": 150, "fat_g": 45})
    assert s.get_goal(U) == 1400
    assert s.get_macro_goals(U) == {"protein": 90, "carb": 150, "fat": 45}
    assert s.get_plan(U)["kcal"] == 1400


def test_today_macros_sum():
    s = Storage(":memory:", 1800)
    s.add_meal(U, [item(protein=12.5), item(protein=7.5)])
    assert s.today_macros(U) == {"protein": 20, "carb": 40, "fat": 10}


def test_profile_round_trip_keeps_goal():
    s = Storage(":memory:", 1800)
    s.set_goal(U, 1500)
    s.set_profile(U, {"sex": "female", "age": 40})
    assert s.get_profile(U) == {"sex": "female", "age": 40}
    assert s.get_goal(U) == 1500
