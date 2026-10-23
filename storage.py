"""SQLite 儲存：每人每日的「今日帳本」。"""
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")


def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


class Storage:
    def __init__(self, path: str, default_goal: int):
        self.default_goal = default_goal
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                goal_kcal INTEGER NOT NULL,
                protein_goal_g INTEGER
            );
            CREATE TABLE IF NOT EXISTS body_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_body_user ON body_reports(user_id, id);
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                created_at TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_kcal REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_meals_user_day ON meals(user_id, day);
            """
        )
        self._migrate()

    def _migrate(self) -> None:
        """舊資料庫補上新欄位（已有的資料不動）。"""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
        with self.conn:
            for col, typ in (("carb_goal_g", "INTEGER"), ("fat_goal_g", "INTEGER"),
                             ("plan_json", "TEXT"), ("profile_json", "TEXT")):
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")

    def set_plan(self, user_id: str, plan: dict) -> None:
        """營養師規劃：同時更新熱量與三大營養素目標。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO users(user_id, goal_kcal, protein_goal_g, carb_goal_g, fat_goal_g, plan_json) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "goal_kcal = excluded.goal_kcal, protein_goal_g = excluded.protein_goal_g, "
                "carb_goal_g = excluded.carb_goal_g, fat_goal_g = excluded.fat_goal_g, "
                "plan_json = excluded.plan_json",
                (user_id, plan["kcal"], plan.get("protein_g"), plan.get("carb_g"),
                 plan.get("fat_g"), json.dumps(plan, ensure_ascii=False)),
            )

    def set_profile(self, user_id: str, profile: dict) -> None:
        """問答填寫的基本資料（性別、年齡、身高、體重、活動量、目標）。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO users(user_id, goal_kcal, profile_json) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET profile_json = excluded.profile_json",
                (user_id, self.default_goal, json.dumps(profile, ensure_ascii=False)),
            )

    def get_profile(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT profile_json FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return json.loads(row["profile_json"]) if row and row["profile_json"] else None

    def get_plan(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT plan_json FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return json.loads(row["plan_json"]) if row and row["plan_json"] else None

    def get_macro_goals(self, user_id: str) -> dict:
        """{"protein": g, "carb": g, "fat": g}，沒設定的為 None。"""
        row = self.conn.execute(
            "SELECT protein_goal_g, carb_goal_g, fat_goal_g FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return {"protein": None, "carb": None, "fat": None}
        return {"protein": row["protein_goal_g"], "carb": row["carb_goal_g"],
                "fat": row["fat_goal_g"]}

    def today_macros(self, user_id: str) -> dict:
        items = [i for m in self.today_meals(user_id) for i in m["items"]]
        return {k: sum(i.get(f"{k}_g", 0) for i in items) for k in ("protein", "carb", "fat")}

    def get_meal(self, meal_id: int, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id)
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "items": json.loads(row["items_json"]),
                "total_kcal": row["total_kcal"]}

    def get_goal(self, user_id: str) -> int:
        row = self.conn.execute(
            "SELECT goal_kcal FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["goal_kcal"] if row else self.default_goal

    def set_goal(self, user_id: str, goal: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO users(user_id, goal_kcal) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET goal_kcal = excluded.goal_kcal",
                (user_id, goal),
            )

    def get_protein_goal(self, user_id: str) -> int | None:
        row = self.conn.execute(
            "SELECT protein_goal_g FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["protein_goal_g"] if row else None

    def set_targets(self, user_id: str, goal_kcal: int | None, protein_g: int | None) -> None:
        """身體報告算出的目標；None 的項目維持原值。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO users(user_id, goal_kcal, protein_goal_g) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "goal_kcal = COALESCE(?, goal_kcal), protein_goal_g = COALESCE(?, protein_goal_g)",
                (user_id, goal_kcal or self.default_goal, protein_g, goal_kcal, protein_g),
            )

    def add_body_report(self, user_id: str, metrics: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO body_reports(user_id, created_at, metrics_json) VALUES (?, ?, ?)",
                (user_id, datetime.now(TZ).isoformat(), json.dumps(metrics, ensure_ascii=False)),
            )

    def latest_body_reports(self, user_id: str, n: int = 2) -> list[dict]:
        """最新的在前，每筆含 created_at 與 metrics。"""
        rows = self.conn.execute(
            "SELECT created_at, metrics_json FROM body_reports WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?", (user_id, n),
        ).fetchall()
        return [{"created_at": r["created_at"], "metrics": json.loads(r["metrics_json"])}
                for r in rows]

    def today_protein(self, user_id: str) -> float:
        return sum(i.get("protein_g", 0) for m in self.today_meals(user_id) for i in m["items"])

    def add_meal(self, user_id: str, items: list[dict]) -> int:
        total = sum(i["kcal"] for i in items)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO meals(user_id, day, created_at, items_json, total_kcal) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, today(), datetime.now(TZ).isoformat(),
                 json.dumps(items, ensure_ascii=False), total),
            )
        return cur.lastrowid

    def last_meal(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM meals WHERE user_id = ? AND day = ? ORDER BY id DESC LIMIT 1",
            (user_id, today()),
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "items": json.loads(row["items_json"]),
                "total_kcal": row["total_kcal"]}

    def update_meal(self, meal_id: int, items: list[dict]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE meals SET items_json = ?, total_kcal = ? WHERE id = ?",
                (json.dumps(items, ensure_ascii=False), sum(i["kcal"] for i in items), meal_id),
            )

    def delete_meal(self, meal_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))

    def today_meals(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM meals WHERE user_id = ? AND day = ? ORDER BY id",
            (user_id, today()),
        ).fetchall()
        return [{"created_at": r["created_at"], "items": json.loads(r["items_json"]),
                 "total_kcal": r["total_kcal"]} for r in rows]

    def today_total(self, user_id: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(total_kcal), 0) AS t FROM meals WHERE user_id = ? AND day = ?",
            (user_id, today()),
        ).fetchone()
        return row["t"]
