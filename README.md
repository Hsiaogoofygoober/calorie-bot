# 家庭熱量紀錄 LINE Bot（MVP）

傳食物照片（手放旁邊當比例尺）或文字給 LINE Bot → Gemini 依 **211 餐盤** 分類食物，
估計份量、熱量與三大營養素 → 記進今日帳本，並給一句均衡建議。

**211 餐盤**：餐盤體積 ½ 蔬菜、¼ 蛋白質（豆魚蛋肉）、¼ 全穀澱粉。

回覆範例：
```
🍱 已記錄
🍚白飯 220g … 403 kcal
🍗炸排骨 120g … 348 kcal
🥬燙青菜 80g … 36 kcal
━━━━━━━━
🍽️ 211 餐盤：蔬菜 20%｜蛋白質 30%｜澱粉 50%
　　（理想 50%｜25%｜25%）
💬 青菜少了，飯可以減半、多夾一份青菜
━━━━━━━━
本餐 787 kcal
蛋白質 31g｜碳水 102g｜脂肪 24g
今日 787 / 1800 kcal｜剩餘 1013 kcal
```

## 傳照片的流程

1. 傳照片 → Bot 問「要補充說明嗎？」（照片只放記憶體，不存檔）
2. 打字補充（例：「肉是煎雞胸和煎魚」「飯只吃一半」）或按「直接分析」
3. 記錄後若 AI 判斷錯：按「修改上一筆」，用一般的話說哪裡錯（例：「雞肉其實是豆腐」），
   AI 會拿原始照片＋上次結果＋你的修正重新判斷，更新同一筆；可以連續修改。
   也可以一句話：`修改：飯只吃半碗`
4. 照片傳錯：按「換照片」（還沒分析就丟掉；已記錄就刪掉那筆）

等待補充或修改超過 30 分鐘會自動放棄；修改時的原始照片保留 6 小時（Bot 重啟會清空，之後只根據上次結果修改）。

## AI 營養師（體脂計截圖）

傳體脂計 App 的身體組成截圖（可補充目標，例：「想減脂、每週重訓兩次」）：

1. AI 讀出截圖數值
2. AI 以營養師角色規劃：每日熱量、蛋白質／碳水／脂肪、纖維、水、三餐分配與建議
3. 程式再套安全底線（`body.py` 的 `guard_plan`）：熱量不低於基礎代謝、蛋白質 1.0–2.2 g/kg
4. AI 規劃失敗時改用固定規則（`rules_plan`）

之後每餐建議都會參考目前狀態與今日三大營養素進度。

## 圖文選單

```bash
python setup_richmenu.py --preview   # 只產生 richmenu.png 預覽
python setup_richmenu.py             # 上傳並設為預設選單（重跑會先刪掉舊的）
```
按鈕：今日紀錄、修改上一筆、換照片、我的狀態、營養計畫、使用說明。修改 `BUTTONS` 即可調整。

預設熱量完全由 AI 估計。若想讓常吃的食物用固定數值，在 `.env` 設 `USE_NUTRITION_DB=true`，
`data/foods.csv` 查得到的就會優先用資料庫。

## 拍照小技巧
- 手和食物放在**同一個平面**，從斜上方約 45° 拍，比較看得出厚度
- 整份餐點都入鏡，211 比例才算得準

## 檔案

| 檔案 | 用途 |
|---|---|
| `app.py` | FastAPI + LINE webhook、指令處理 |
| `analyzer.py` | Gemini 辨識（結構化 JSON 輸出） |
| `body.py` | 營養規劃的安全底線、備用規則、訊息格式 |
| `setup_richmenu.py` | 產生並設定圖文選單 |
| `nutrition.py` | 營養資料庫查詢（完全比對 → 模糊比對） |
| `storage.py` | SQLite 每人每日帳本 |
| `data/foods.csv` | 選用的營養資料（約 40 筆近似值示範資料，`USE_NUTRITION_DB=true` 才會用） |
| `try_analyze.py` | 不用 LINE，直接在電腦測試辨識 |

## 使用指令

- 傳照片（可補充說明）／打字（如「半糖珍奶大杯」）→ 記錄
- 傳體脂計截圖 → AI 營養師更新每日目標與規劃
- `修改上一筆`／`修改：...` → 對話修正 AI 的判斷
- `換照片`、`取消`
- `今日` → 今天的紀錄、營養素總計與剩餘
- `狀態` → 最新身體狀態與目標；`營養計畫` → 完整規劃
- `刪除上一筆`
- `目標 1800` → 手動設定每日熱量

## 安裝

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # 填入金鑰
```

### 1. 取得 Gemini API Key
到 Google AI Studio 建立 API key，填進 `.env` 的 `GEMINI_API_KEY`。
先測試辨識：

```bash
python try_analyze.py 便當.jpg
python try_analyze.py --text "一碗牛肉麵加一顆滷蛋"
```

### 2. 建立 LINE Bot
1. 到 LINE Developers Console 建立 Provider → Messaging API channel
2. 「Basic settings」複製 **Channel secret**；「Messaging API」發行 **Channel access token**，填進 `.env`
3. 在 LINE Official Account Manager 關閉「自動回應訊息」

### 3. 啟動並連上 LINE
```bash
uvicorn app:app --port 8000
```
LINE 需要公開的 HTTPS 網址，本機測試可用 ngrok 或 cloudflared：
```bash
ngrok http 8000
```
把 `https://xxxx.ngrok-free.app/callback` 填到 Messaging API 的 **Webhook URL**，開啟 **Use webhook**，按 Verify。
用手機掃 QR code 加好友就能用了。

## 換成食藥署營養資料庫（建議）

`data/foods.csv` 只要兩欄：`name,kcal_per_100g`。
到政府資料開放平台下載「食品營養成分資料庫」，把「樣品名稱」和每 100g「熱量」兩欄整理成這個格式即可。
資料超過 300 筆時，程式不會把名稱清單放進提示詞（省 token），改用模糊比對。

## 推上 GitHub 前：金鑰保護

- `.gitignore` 已排除 `.env`、資料庫（家人紀錄）、照片截圖
- `.githooks/pre-commit` 每次 commit 前會掃描 Gemini API key、LINE token、`.env`、`.db`，發現就擋下
- hook 設定**每次 clone 都要重做一次**：
  ```bash
  git config core.hooksPath .githooks
  ```
- 手動掃描整個專案：`python .githooks/check_secrets.py --all`
- 萬一金鑰已經推上去：立刻到 Google AI Studio／LINE Developers **重新產生金鑰**（刪 commit 不夠，可能已被抓走）

## 正式部署（家裡的電腦＋Cloudflare Tunnel）

- Cloudflare Tunnel 以 Windows 服務執行，把 `https://bot.<網域>/` 轉到 `localhost:8000`
- Bot 由工作排程器在**開機時**以 SYSTEM 執行 `run_bot.ps1`（不需登入；當掉 10 秒後自動重啟）
  ```bash
  powershell -ExecutionPolicy Bypass -File D:\calorie-bot\install_autostart.ps1            # 安裝（系統管理員）
  powershell -ExecutionPolicy Bypass -File D:\calorie-bot\install_autostart.ps1 -Uninstall # 移除
  ```
- 執行紀錄：`logs\bot.log`（超過 5MB 自動換檔）
- 改了程式或 `.env` 要重啟：工作排程器 → `calorie-bot` → 結束 → 執行
- 電腦要設定「永不睡眠」，否則睡眠時 Bot 收不到訊息

## 下一步可以加

- 每晚推播當日總結（需 LINE push message，有每月免費則數）
- 每人的份量習慣（例：「爸爸飯都半碗」）
- 蛋白質、碳水等營養素
- LIFF 網頁看週／月趨勢圖
