"""問答填寫基本資料：解析回答、BMR／TDEE 公式。"""
import pytest

import intake


@pytest.mark.parametrize("text, expected", [
    ("男性", "male"), ("男生", "male"), ("我是男的", "male"),
    ("女性", "female"), ("女", "female"),
    ("不知道", None),
])
def test_parse_sex(text, expected):
    assert intake.parse("sex", text) == expected


@pytest.mark.parametrize("field, text, expected", [
    ("age", "25", 25), ("age", "35歲", 35), ("age", "二十五", None), ("age", "5", None),
    ("height", "173cm", 173), ("height", "158.5", 158.5), ("height", "300", None),
    ("weight", "60公斤", 60), ("weight", "58.5 kg", 58.5), ("weight", "300", None),
    ("weight", "", None),
])
def test_parse_numbers_with_range(field, text, expected):
    assert intake.parse(field, text) == expected


@pytest.mark.parametrize("text, expected", [
    ("久坐", 0), ("中度活動", 2), ("非常高", 4), ("1", 0), ("5", 4), ("6", None), ("隨便", None),
])
def test_parse_activity(text, expected):
    assert intake.parse("activity", text) == expected


def test_parse_goal_free_text_and_skip():
    assert intake.parse("goal", "想減脂但保留肌肉") == "想減脂但保留肌肉"
    assert intake.parse("goal", "跳過") is None


def test_mifflin_male_matches_reference_site():
    """對照使用者截圖的網站：男、25 歲、173 cm、60 kg、中度活動 → 1561 / 2420。"""
    calc = intake.compute({"sex": "male", "age": 25, "height": 173, "weight": 60, "activity": 2})
    assert calc["bmr"] == 1561
    assert calc["tdee"] == 2420
    assert calc["bmi"] == 20.0


def test_mifflin_female():
    # 10×62 + 6.25×158 − 5×52 − 161 = 1186.5
    calc = intake.compute({"sex": "female", "age": 52, "height": 158, "weight": 62, "activity": 1})
    assert calc["bmr"] in (1186, 1187)
    assert calc["tdee"] == round(1186.5 * 1.375)


def test_every_step_has_a_question_and_activity_buttons_parse():
    fields = [s[0] for s in intake.STEPS]
    assert fields == ["sex", "age", "height", "weight", "activity", "goal"]
    activity_buttons = intake.STEPS[4][2]
    assert [intake.parse("activity", b) for b in activity_buttons] == list(range(len(activity_buttons)))
    for button in intake.STEPS[0][2]:
        assert intake.parse("sex", button) is not None


def test_to_metrics_feeds_planner_fields():
    profile = {"sex": "male", "age": 25, "height": 173, "weight": 60, "activity": 2}
    calc = intake.compute(profile)
    m = intake.to_metrics(profile, calc)
    assert m.weight_kg == 60 and m.bmr_kcal == 1561 and m.activity_kcal == 2420
    assert m.body_fat_pct is None and m.flags == []
