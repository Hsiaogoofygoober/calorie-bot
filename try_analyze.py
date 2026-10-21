"""不用 LINE，直接在電腦上測試辨識。

python try_analyze.py 便當.jpg
python try_analyze.py 便當.jpg --note "肉是煎雞胸和煎魚"
python try_analyze.py --text "半糖珍奶大杯"
"""
import argparse
import mimetypes
import os

from dotenv import load_dotenv

from analyzer import Analyzer
from nutrition import NutritionDB

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("image", nargs="?")
parser.add_argument("--text")
parser.add_argument("--note", help="對照片的補充說明")
args = parser.parse_args()

use_db = os.getenv("USE_NUTRITION_DB", "false").lower() == "true"
analyzer = Analyzer(os.environ["GEMINI_API_KEY"],
                    os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
                    NutritionDB() if use_db else None,
                    fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash"))

image, mime = None, "image/jpeg"
if args.image:
    with open(args.image, "rb") as f:
        image = f.read()
    mime = mimetypes.guess_type(args.image)[0] or mime

analysis = analyzer.analyze(image=image, text=args.text, mime_type=mime, note=args.note)
print("模型：", analyzer.last_model, "｜類型：", analysis.kind.value)
if analysis.body:
    from body import compute_targets, format_report
    print(format_report(analysis.body))
    kcal, protein, notes = compute_targets(analysis.body)
    print("\n".join(notes))
    raise SystemExit
items = analyzer.build_items(analysis)
for i in items:
    src = f"資料庫:{i['db_name']}" if i["source"] == "db" else "AI估"
    print(f"[{i['category']}] {i['name']:<10} {i['grams']:>5}g  {i['kcal']:>5} kcal  "
          f"P{i['protein_g']:g} C{i['carb_g']:g} F{i['fat_g']:g}  ({src})")
print(f"合計 {sum(i['kcal'] for i in items)} kcal")
if p := analysis.plate:
    print(f"211 餐盤：蔬菜 {p.veg_pct:.0f}% / 蛋白質 {p.protein_pct:.0f}% / 澱粉 {p.starch_pct:.0f}%"
          "（理想 50/25/25）")
print("建議：", analysis.advice)
if analysis.question:
    print("提問：", analysis.question)
