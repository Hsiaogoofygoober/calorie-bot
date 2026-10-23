"""接線檢查：webhook 簽章、按鈕都對得到指令、金鑰掃描、測試工具能執行。"""
import base64
import hashlib
import hmac
import importlib.util
import json
import runpy
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT, body_report, food


# ---------- webhook ----------

def signed(body: str, secret: str = "test-secret") -> str:
    return base64.b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode()


def test_webhook_rejects_bad_signature(bot):
    client = TestClient(bot.app.app)
    r = client.post("/callback", content='{"events":[]}', headers={"X-Line-Signature": "fake"})
    assert r.status_code == 400


def test_webhook_accepts_line_signature_and_dispatches(bot):
    body = json.dumps({"destination": "x", "events": [{
        "type": "message", "mode": "active", "timestamp": 0, "webhookEventId": "e",
        "deliveryContext": {"isRedelivery": False}, "replyToken": "tok",
        "source": {"type": "user", "userId": "U-test"},
        "message": {"id": "1", "type": "text", "quoteToken": "q", "text": "說明"}}]})
    r = TestClient(bot.app.app).post("/callback", content=body,
                                     headers={"X-Line-Signature": signed(body)})
    assert r.status_code == 200
    assert "傳餐點照片" in bot.last["text"]


def test_health(bot):
    assert TestClient(bot.app.app).get("/").json() == {"status": "ok"}


# ---------- 所有按鈕都要對得到功能（改指令名稱時最容易壞） ----------

def test_rich_menu_buttons_are_real_commands(bot):
    import setup_richmenu
    for _, title, _, text, _ in setup_richmenu.BUTTONS:
        assert bot.app.run_command("U-test", "tok", text), f"選單「{title}」送出的「{text}」不是指令"


def test_rich_menu_areas_cover_image_without_overlap():
    import setup_richmenu as m
    cells = [m.cell(i) for i in range(len(m.BUTTONS))]
    assert len(m.BUTTONS) == m.COLS * m.ROWS
    assert sum(w * h for _, _, w, h in cells) == m.WIDTH * m.HEIGHT
    for x, y, w, h in cells:
        assert x + w <= m.WIDTH and y + h <= m.HEIGHT


def test_quick_reply_buttons_are_handled(bot):
    for label in bot.app.MEAL_QUICK + bot.app.NOTE_QUICK + ["填寫基本資料", "營養計畫"]:
        handled = bot.app.run_command("U-test", "tok", label) or label in bot.app.SKIP_WORDS
        assert handled, f"按鈕「{label}」沒有對應的處理"
    for label in (bot.app.MEAL_QUICK + bot.app.NOTE_QUICK):
        assert len(label) <= 20, "LINE 快速按鈕文字最多 20 字"


def test_help_mentions_every_command(bot):
    for word in ("修改上一筆", "換照片", "刪除上一筆", "今日", "狀態", "營養計畫", "基本資料", "目標"):
        assert word in bot.app.HELP_TEXT


# ---------- 金鑰掃描 ----------

@pytest.fixture(scope="module")
def secrets():
    spec = importlib.util.spec_from_file_location("check_secrets", ROOT / ".githooks" / "check_secrets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flagged(secrets, line: str) -> bool:
    return any(p.search(line) for p, _ in secrets.SECRET_PATTERNS)


@pytest.mark.parametrize("line", [
    "key = 'AIza" + "x" * 35 + "'",
    "key = 'AQ.Ab" + "z" * 48 + "'",
    "GEMINI_API_KEY=" + "a" * 30,
    "LINE_CHANNEL_SECRET=" + "0123456789abcdef" * 2,
    "token = '" + "A" * 172 + "'",
])
def test_secret_patterns_catch_keys(secrets, line):
    assert flagged(secrets, line)


@pytest.mark.parametrize("line", [
    "GEMINI_API_KEY=",
    'os.environ["LINE_CHANNEL_SECRET"]',
    "GEMINI_MODEL=gemini-3.8-flash",
])
def test_secret_patterns_ignore_normal_code(secrets, line):
    assert not flagged(secrets, line)


def test_real_files_pass_secret_scan(secrets):
    for path in [*ROOT.glob("*.py"), ROOT / ".env.example", ROOT / "README.md"]:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not flagged(secrets, line), f"{path.name}: {line}"


@pytest.mark.parametrize("path, blocked", [
    (".env", True), ("sub/.env.local", True), ("calorie.db", True), (".env.example", False),
    ("app.py", False),
])
def test_blocked_files(secrets, path, blocked):
    hit = any(p.search(path) for p, _ in secrets.BLOCKED_FILES)
    assert (hit and path.split("/")[-1] not in secrets.ALLOWED_FILES) == blocked


# ---------- try_analyze.py 能實際跑完（曾因函式改名而壞掉） ----------

@pytest.mark.parametrize("kind", ["food", "body"])
def test_try_analyze_runs(monkeypatch, tmp_path, capsys, kind):
    import analyzer
    result = food(("白飯", "全穀澱粉", 200, 183)) if kind == "food" else body_report()
    monkeypatch.setattr(analyzer.Analyzer, "analyze", lambda self, **kw: result)
    monkeypatch.setattr(analyzer.Analyzer, "last_model", "fake", raising=False)
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(sys, "argv", ["try_analyze.py", str(photo), str(photo)])
    try:
        runpy.run_path(str(ROOT / "try_analyze.py"), run_name="__main__")
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "照片： 2 張" in out
    assert ("合計" in out) if kind == "food" else ("固定規則參考" in out)
