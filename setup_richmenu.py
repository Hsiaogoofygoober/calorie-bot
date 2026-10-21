"""產生圖文選單圖片並設定成 LINE 官方帳號的預設選單。

python setup_richmenu.py            # 產生圖片並上傳設定
python setup_richmenu.py --preview  # 只產生 richmenu.png 預覽，不上傳

再執行一次會先刪掉舊的選單（同名）再建立新的。
"""
import argparse
import io
import os
from pathlib import Path

from dotenv import load_dotenv
from linebot.v3.messaging import (
    ApiClient, Configuration, MessageAction, MessagingApi, MessagingApiBlob,
    RichMenuArea, RichMenuBounds, RichMenuRequest, RichMenuSize,
)
from PIL import Image, ImageDraw, ImageFont

MENU_NAME = "calorie-bot-menu"
# LINE 允許的最大尺寸；2 欄 × 3 列，按鈕大、字大，長輩比較好按
WIDTH, HEIGHT = 2500, 1686
COLS, ROWS = 2, 3

# (圖示字, 標題, 說明, 送出的文字, 底色)
BUTTONS = [
    ("今", "今日紀錄", "今天吃了什麼", "今日", "#E8F5E9"),
    ("改", "修改上一筆", "AI 判斷錯了", "修改上一筆", "#FFF3E0"),
    ("換", "換照片", "照片傳錯了", "換照片", "#FCE4EC"),
    ("我", "我的狀態", "身體數據與目標", "狀態", "#E3F2FD"),
    ("營", "營養計畫", "營養師的規劃", "營養計畫", "#F3E5F5"),
    ("?", "使用說明", "怎麼使用", "說明", "#ECEFF1"),
]
ACCENT = ["#43A047", "#FB8C00", "#D81B60", "#1E88E5", "#8E24AA", "#546E7A"]

FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("msjhbd.ttc", "msjh.ttc") if bold else ("msjh.ttc",)):
        path = FONT_DIR / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise SystemExit("找不到微軟正黑體（msjh.ttc），請修改 FONT_DIR")


def cell(i: int) -> tuple[int, int, int, int]:
    w, h = WIDTH // COLS, HEIGHT // ROWS
    x, y = (i % COLS) * w, (i // COLS) * h
    # 最後一欄／列補足除不盡的像素
    return x, y, (WIDTH - x if i % COLS == COLS - 1 else w), (HEIGHT - y if i // COLS == ROWS - 1 else h)


def draw_menu() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    d = ImageDraw.Draw(img)
    icon_f, title_f, sub_f = font(170, True), font(150, True), font(80)
    for i, (icon, title, sub, _, bg) in enumerate(BUTTONS):
        x, y, w, h = cell(i)
        d.rectangle([x, y, x + w, y + h], fill=bg)
        d.rectangle([x, y, x + w - 1, y + h - 1], outline="white", width=10)
        # 左側圓形圖示
        r, cx, cy = 150, x + 230, y + h // 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT[i])
        d.text((cx, cy), icon, font=icon_f, fill="white", anchor="mm")
        # 右側標題＋說明
        tx = x + 430
        d.text((tx, cy + 10), title, font=title_f, fill="#263238", anchor="ls")
        d.text((tx, cy + 120), sub, font=sub_f, fill="#607D8B", anchor="ls")
    return img


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    img = draw_menu()
    img.save("richmenu.png")
    print("已產生預覽：richmenu.png")
    if args.preview:
        return

    load_dotenv(".env")
    areas = []
    for i, (_, title, _, text, _) in enumerate(BUTTONS):
        x, y, w, h = cell(i)
        areas.append(RichMenuArea(bounds=RichMenuBounds(x=x, y=y, width=w, height=h),
                                  action=MessageAction(label=title, text=text)))
    request = RichMenuRequest(size=RichMenuSize(width=WIDTH, height=HEIGHT), selected=True,
                              name=MENU_NAME, chat_bar_text="選單", areas=areas)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with ApiClient(Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])) as c:
        api, blob = MessagingApi(c), MessagingApiBlob(c)
        for old in api.get_rich_menu_list().richmenus:
            if old.name == MENU_NAME:
                api.delete_rich_menu(old.rich_menu_id)
                print("已刪除舊選單", old.rich_menu_id)
        menu_id = api.create_rich_menu(request).rich_menu_id
        blob.set_rich_menu_image(menu_id, body=buf.getvalue(),
                                 _headers={"Content-Type": "image/png"})
        api.set_default_rich_menu(menu_id)
    print("✅ 圖文選單已設定為預設：", menu_id)


if __name__ == "__main__":
    main()
