"""不用 LINE，直接在電腦上測試辨識。

python try_analyze.py 便當.jpg
python try_analyze.py 主餐.jpg 飲料.jpg            # 多張照片當成同一餐
python try_analyze.py 便當.jpg --note "肉是煎雞胸和煎魚"
python try_analyze.py --text "半糖珍奶大杯"
"""
import argparse
import os

from dotenv import load_dotenv

from analyzer import Analyzer
from nutrition import NutritionDB

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("images", nargs="*", help="一或多張照片（同一餐）")
parser.add_argument("--text")
parser.add_argument("--note", help="對照片的補充說明")
args = parser.parse_args()

use_db = os.getenv("USE_NUTRITION_DB", "false").lower() == "true"
analyzer = Analyzer(os.environ["GEMINI_API_KEY"],
                    os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
                    NutritionDB() if use_db else None,
                    fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash"))

images = []
for path in args.images:
    with open(path, "rb") as f:
        images.append(f.read())

analysis = analyzer.analyze(images=images, text=args.text, note=args.note)
print("模型：", analyzer.last_model, "｜照片：", len(images), "張｜類型：", analysis.kind.value)
if analysis.body:
    from body import format_report, rules_plan
    print(format_report(analysis.body))
    if plan := rules_plan(analysis.body):
        print(f"（固定規則參考）每日 {plan['kcal']} kcal｜蛋白質 {plan['protein_g']}g")
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
