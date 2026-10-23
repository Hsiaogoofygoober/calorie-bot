"""身體組成報告 → 每日熱量與營養素目標。

主要由 AI 營養師規劃（analyzer.plan），程式再加上安全底線（guard_plan）：
- 熱量不低於基礎代謝
- 蛋白質 1.0–2.2 g/kg 體重
AI 規劃失敗時改用固定規則（rules_plan）：
- 每日消耗用「活動代謝」，沒有就用 基礎代謝 × 1.3
- 需要減脂（脂肪控制 < 0）→ 每日消耗 − 300 kcal，但不低於基礎代謝
- 蛋白質：體重 × 1.2 g；需要增肌 → × 1.5 g
"""
import math

from analyzer import BodyMetrics

DEFICIT_KCAL = 300
PROTEIN_BASE = 1.2
PROTEIN_MUSCLE = 1.5
PROTEIN_MIN, PROTEIN_MAX = 1.0, 2.2  # g/kg 安全範圍


def needs_muscle(m: BodyMetrics) -> bool:
    if m.muscle_control_kg and m.muscle_control_kg > 0:
        return True
    return any(k in f for f in m.flags for k in ("蛋白質", "肌肉", "儲肌") if "偏低" in f)


def round_kcal(kcal: float, floor: float | None = None) -> int:
    """取整到十位數；有下限時向上進位，避免 1273 → 1270 反而低於基礎代謝。"""
    if floor and kcal <= floor:
        return int(math.ceil(floor / 10) * 10)
    return int(round(kcal / 10) * 10)


def rules_plan(m: BodyMetrics) -> dict | None:
    """AI 規劃失敗時的備案；資料不足（沒有代謝數值）回傳 None。"""
    tdee = m.activity_kcal or (m.bmr_kcal * 1.3 if m.bmr_kcal else None)
    if not tdee:
        return None
    lose_fat = bool(m.fat_control_kg and m.fat_control_kg < 0)
    kcal = round_kcal(tdee - DEFICIT_KCAL if lose_fat else tdee, m.bmr_kcal)
    protein = int(round(m.weight_kg * (PROTEIN_MUSCLE if needs_muscle(m) else PROTEIN_BASE))) \
        if m.weight_kg else None
    fat = int(round(kcal * 0.28 / 9))
    carb = int(round((kcal - (protein or 0) * 4 - fat * 9) / 4))
    return {
        "kcal": kcal, "protein_g": protein, "carb_g": carb, "fat_g": fat,
        "fiber_g": 25, "water_ml": int(round((m.weight_kg or 50) * 35, -2)),
        "meals": [],
        "summary": "（AI 營養師暫時無法使用，以下為固定規則計算的目標）",
        "strategy": ("活動代謝減 300 kcal 小幅減脂" if lose_fat else "依活動代謝維持")
                    + ("，蛋白質提高到 1.5 g/kg 幫助增肌" if needs_muscle(m) else ""),
        "tips": [], "caution": "", "source": "rules",
    }


def guard_plan(plan: dict, m: BodyMetrics) -> tuple[dict, list[str]]:
    """套用安全底線；回傳 (調整後的規劃, 調整說明)。"""
    notes = []
    if m.bmr_kcal and plan["kcal"] < m.bmr_kcal:
        new = round_kcal(plan["kcal"], m.bmr_kcal)
        notes.append(f"熱量 {plan['kcal']} 低於基礎代謝 {m.bmr_kcal:.0f}，已調整為 {new}")
        plan["kcal"] = new
    if m.weight_kg and plan.get("protein_g"):
        lo, hi = m.weight_kg * PROTEIN_MIN, m.weight_kg * PROTEIN_MAX
        if not lo <= plan["protein_g"] <= hi:
            new = int(round(min(max(plan["protein_g"], lo), hi)))
            notes.append(f"蛋白質 {plan['protein_g']}g 超出安全範圍，已調整為 {new}g")
            plan["protein_g"] = new
    return plan, notes


def format_plan(plan: dict) -> str:
    lines = [
        "🥗 營養師的每日規劃",
        f"🎯 熱量 {plan['kcal']} kcal",
        f"🍗 蛋白質 {plan['protein_g']}g｜🍚 碳水 {plan['carb_g']}g｜🥑 脂肪 {plan['fat_g']}g",
        f"🥦 纖維 {plan['fiber_g']}g｜💧 水 {plan['water_ml']} ml",
    ]
    if plan.get("summary"):
        lines += ["━━━━━━━━", f"📝 {plan['summary']}"]
    if plan.get("strategy"):
        lines.append(f"💡 {plan['strategy']}")
    if plan.get("meals"):
        lines += ["━━━━━━━━", "🍽️ 三餐分配"]
        lines += [f"・{x['name']} {x['kcal']} kcal：{x['suggestion']}" for x in plan["meals"]]
    if plan.get("tips"):
        lines += ["━━━━━━━━", "✅ 建議"]
        lines += [f"{n}. {t}" for n, t in enumerate(plan["tips"], 1)]
    if plan.get("caution"):
        lines.append(f"⚠️ {plan['caution']}")
    for note in plan.get("adjustments", []):
        lines.append(f"🛡️ {note}")
    return "\n".join(lines)


def _delta(new: float | None, old: float | None, unit: str) -> str:
    if new is None or old is None:
        return ""
    d = new - old
    return f"（{d:+.1f}{unit}）" if abs(d) >= 0.05 else ""


def format_report(m: BodyMetrics, prev: BodyMetrics | None = None) -> str:
    def v(x, fmt="{:g}"):
        return "—" if x is None else fmt.format(x)

    p = prev or BodyMetrics.model_construct(**{k: None for k in BodyMetrics.model_fields})

    def join(*parts: str | None) -> str | None:
        parts = [x for x in parts if x]
        return "｜".join(parts) if parts else None

    # 沒有的數值（例：問答填寫沒有體脂）就不顯示
    lines = [x for x in (
        join(m.weight_kg and f"體重 {v(m.weight_kg)}kg{_delta(m.weight_kg, p.weight_kg, 'kg')}",
             m.body_fat_pct and f"體脂 {v(m.body_fat_pct)}%{_delta(m.body_fat_pct, p.body_fat_pct, '%')}"),
        join(m.bmi and f"BMI {v(m.bmi)}",
             m.muscle_pct and f"肌肉率 {v(m.muscle_pct)}%{_delta(m.muscle_pct, p.muscle_pct, '%')}"),
        join(m.bmr_kcal and f"基礎代謝 {v(m.bmr_kcal, '{:.0f}')}",
             m.activity_kcal and f"每日消耗 {v(m.activity_kcal, '{:.0f}')} kcal"),
    ) if x]
    if m.flags:
        lines.append("⚠️ " + "、".join(m.flags))
    return "\n".join(lines)


def context_line(m: BodyMetrics | None, kcal_goal: int, goals: dict,
                 kcal_today: float, today: dict) -> str:
    """給 Gemini 的精簡使用者狀態（約 80 字），讓每餐建議個人化。"""
    parts = []
    if m:
        if m.weight_kg:
            parts.append(f"體重{m.weight_kg:g}kg")
        if m.body_fat_pct:
            parts.append(f"體脂{m.body_fat_pct:g}%")
        if m.flags:
            parts.append("、".join(m.flags))
    parts.append(f"每日目標{kcal_goal}kcal，今日已吃{kcal_today:.0f}kcal")
    names = {"protein": "蛋白質", "carb": "碳水", "fat": "脂肪"}
    for k, label in names.items():
        if goals.get(k):
            parts.append(f"{label}目標{goals[k]}g，今日已吃{today.get(k, 0):.0f}g")
    return "；".join(parts)
