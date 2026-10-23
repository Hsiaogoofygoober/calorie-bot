"""Gemini 呼叫的組裝：提示詞、多張照片、備援模型、營養素換算（用假的 client，不連網）。"""
from types import SimpleNamespace as NS

import pytest

from analyzer import Analyzer
from conftest import food

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 10
JPG = b"\xff\xd8\xff" + b"0" * 10


class FakeModels:
    def __init__(self, fail_models=()):
        self.calls = []
        self.fail_models = set(fail_models)

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents})
        if model in self.fail_models:
            raise RuntimeError("503 UNAVAILABLE")
        return NS(parsed=food(("飯", "全穀澱粉", 200, 183)), text="")


@pytest.fixture
def analyzer():
    a = Analyzer("test-key", "main-model", fallback_model="backup-model")
    a.client = NS(models=FakeModels())
    return a


def prompt_of(a) -> str:
    return a.client.models.calls[-1]["contents"][-1]


def images_of(a) -> list:
    return a.client.models.calls[-1]["contents"][:-1]


def test_build_items_scales_per_100g_values():
    a = Analyzer("test-key", "m")
    items = a.build_items(food(("飯", "全穀澱粉", 250, 180)))
    assert items[0]["kcal"] == 450                 # 250g × 180/100
    assert items[0]["protein_g"] == 25.0           # 250g × 10/100
    assert items[0]["carb_g"] == 50.0 and items[0]["fat_g"] == 12.5


def test_multiple_photos_are_sent_together(analyzer):
    analyzer.analyze(images=[JPG, PNG, JPG])
    parts = images_of(analyzer)
    assert len(parts) == 3
    assert [p.inline_data.mime_type for p in parts] == ["image/jpeg", "image/png", "image/jpeg"]
    assert "3 張照片" in prompt_of(analyzer)


def test_note_and_context_in_prompt(analyzer):
    analyzer.analyze(images=[JPG], note="肉是煎雞胸", context="每日目標1380kcal")
    p = prompt_of(analyzer)
    assert "使用者補充說明（以此為準）：肉是煎雞胸" in p and "使用者狀態：每日目標1380kcal" in p


def test_correction_includes_previous_result(analyzer):
    prev = [{"name": "煎豆腐", "category": "蛋白質", "grams": 80, "kcal": 104}]
    analyzer.analyze(images=[JPG], previous=prev, correction="豆腐其實是雞胸")
    p = prompt_of(analyzer)
    assert "煎豆腐（蛋白質）80g" in p and "使用者指出的錯誤（以此為準修正）：豆腐其實是雞胸" in p


def test_text_only_meal(analyzer):
    analyzer.analyze(text="一碗牛肉麵")
    assert images_of(analyzer) == [] and prompt_of(analyzer).startswith("一碗牛肉麵")


def test_falls_back_to_backup_model(analyzer):
    analyzer.client.models.fail_models = {"main-model"}
    result = analyzer.analyze(text="一碗飯")
    assert result.items[0].name == "飯"
    assert analyzer.last_model == "backup-model"


def test_raises_when_all_models_fail(analyzer):
    analyzer.client.models.fail_models = {"main-model", "backup-model"}
    with pytest.raises(RuntimeError):
        analyzer.analyze(text="一碗飯")
