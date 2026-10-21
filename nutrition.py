"""營養資料庫：用名稱查每 100g 熱量。熱量以資料庫為準，查不到才用 AI 估計值。"""
import csv
import difflib
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "foods.csv"


class NutritionDB:
    def __init__(self, path: Path = DATA_PATH):
        self.kcal: dict[str, float] = {}
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                name = row["name"].strip()
                if name:
                    self.kcal[name] = float(row["kcal_per_100g"])

    @property
    def names(self) -> list[str]:
        return list(self.kcal)

    def lookup(self, *candidates: str) -> tuple[str, float] | None:
        """依序嘗試候選名稱：完全相同 → 模糊比對。回傳 (資料庫名稱, kcal/100g)。"""
        for name in filter(None, candidates):
            if name in self.kcal:
                return name, self.kcal[name]
        for name in filter(None, candidates):
            match = difflib.get_close_matches(name, self.names, n=1, cutoff=0.6)
            if match:
                return match[0], self.kcal[match[0]]
        return None
