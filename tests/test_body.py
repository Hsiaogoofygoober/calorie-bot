"""營養規劃的安全底線、備用規則、狀態顯示。"""
from analyzer import BodyMetrics
import body


def metrics(**kw) -> BodyMetrics:
    data = {k: None for k in BodyMetrics.model_fields}
    data["flags"] = []
    data.update(kw)
    return BodyMetrics(**data)


def test_guard_raises_kcal_to_bmr():
    plan, notes = body.guard_plan({"kcal": 1000, "protein_g": 80}, metrics(bmr_kcal=1273, weight_kg=56))
    assert plan["kcal"] >= 1273
    assert notes


def test_guard_clamps_protein_to_safe_range():
    m = metrics(weight_kg=50)
    high, _ = body.guard_plan({"kcal": 1500, "protein_g": 200}, m)
    low, _ = body.guard_plan({"kcal": 1500, "protein_g": 20}, m)
    assert high["protein_g"] == 110   # 2.2 g/kg
    assert low["protein_g"] == 50     # 1.0 g/kg


def test_guard_keeps_reasonable_plan_untouched():
    plan, notes = body.guard_plan({"kcal": 1400, "protein_g": 85}, metrics(bmr_kcal=1273, weight_kg=56.6))
    assert plan["kcal"] == 1400 and plan["protein_g"] == 85 and notes == []


def test_rules_plan_deficit_and_muscle():
    m = metrics(weight_kg=56.6, bmr_kcal=1273, activity_kcal=1680,
                fat_control_kg=-6.3, muscle_control_kg=4.0)
    plan = body.rules_plan(m)
    assert plan["kcal"] == 1380                  # 1680 − 300
    assert plan["protein_g"] == round(56.6 * 1.5)
    total = plan["protein_g"] * 4 + plan["carb_g"] * 4 + plan["fat_g"] * 9
    assert abs(total - plan["kcal"]) <= 10


def test_rules_plan_never_below_bmr():
    m = metrics(weight_kg=50, bmr_kcal=1300, activity_kcal=1450, fat_control_kg=-5)
    assert body.rules_plan(m)["kcal"] >= 1300


def test_rounding_never_goes_below_bmr():
    """曾經的 bug：基礎代謝 1273 四捨五入成 1270，反而低於基礎代謝。"""
    m = metrics(weight_kg=50, bmr_kcal=1273, activity_kcal=1500, fat_control_kg=-5)
    assert body.rules_plan(m)["kcal"] == 1280
    assert body.round_kcal(1000, 1273) == 1280
    assert body.round_kcal(1384, 1273) == 1380


def test_rules_plan_needs_metabolism_data():
    assert body.rules_plan(metrics(weight_kg=60)) is None


def test_format_report_hides_missing_values():
    text = body.format_report(metrics(weight_kg=60, bmi=20.0, bmr_kcal=1561, activity_kcal=2420))
    assert "體重 60kg" in text and "每日消耗 2420" in text
    assert "體脂" not in text and "—" not in text


def test_format_report_shows_changes():
    text = body.format_report(metrics(weight_kg=56.1, body_fat_pct=32.6),
                              metrics(weight_kg=56.6, body_fat_pct=33.2))
    assert "-0.5kg" in text and "-0.6%" in text


def test_context_line_includes_goals_and_progress():
    line = body.context_line(metrics(weight_kg=56.6, flags=["蛋白質率偏低"]), 1380,
                             {"protein": 85, "carb": 150, "fat": None},
                             450, {"protein": 30, "carb": 60, "fat": 10})
    assert "每日目標1380kcal" in line and "蛋白質目標85g，今日已吃30g" in line
    assert "脂肪目標" not in line
