# Section 4 - Code Execution

本節目標：
1. 讓 Agent 依使用者需求生成客製化 Python code
2. 真的執行 code
3. 回傳執行結果（文字 / 圖片）

## 啟動方式

```bash
python manager.py --section 4
```

## 安裝套件

```bash
pip install -r requirements.txt
```

`openpyxl` 已包含在 requirements（pandas 讀寫 xlsx 需要）。

## Code Execution 控制

1. `Enable Code Execution`
- 開啟後才會進入 code generation + execution 流程
- 會強制開啟 Conversation Memory，且至少 4 輪

2. `Execution Flow`
- `Automatic (execute directly)`：產生 code 後直接執行
- `Manual (show code + Yes/No)`：先顯示 code，再由你按 Yes/No

3. `Environment Libraries (read-only)`
- UI 不再提供 checkbox 勾選
- 只顯示目前 backend 環境可用套件（例如 pandas / numpy / matplotlib）

## 重要行為

- 不使用固定 code template
- 由 LLM 客製化生成程式碼
- 若資訊不足（例如圖表缺 labels / 標題 / 資料），會先反問再執行

## Excel 測試資料

本專案已提供：
- [sales_demo.xlsx](c:/Users/rathe/Project/agentic-workflow/section_4_code_execution/data/sales_demo.xlsx)

欄位：
- `date`
- `product`
- `quantity`
- `unit_price`
- `channel`
- `region`

其中有少量缺值，方便測 pandas 清洗流程。

## 檔案上傳（UI）

聊天輸入框右下的 `選擇檔案` 支援：
- 圖片：`png/jpeg/webp`
- 資料檔：`csv/xlsx`

當你上傳 `csv/xlsx` 後，前端會先把檔案送到 Section 4 後端，再把檔案路徑提供給 Agent 做分析。

## 推薦測試語句

### A. 基礎計算
1. `幫我執行一段 python，計算 1 到 100 的總和`
2. `用 python 幫我算 23 * 19 + 44`

### B. 圖表（客製化）
1. `請幫我畫折線圖，資料點是 10, 18, 12, 25, 30，標題與座標軸都幫我用英文`
2. `請幫我畫圓餅圖，資料是 40, 35, 25，labels 用 dog, cat, human，標題是 lifes`

### C. pandas + numpy（搭配 sales_demo.xlsx）
1. `請用 pandas 讀取 sales_demo.xlsx，先顯示前 5 筆資料`
2. `計算每個 product 的總銷售額（quantity * unit_price）並排序`
3. `請用 numpy 算 unit_price 的平均、標準差與 95 分位數`
4. `幫我針對 Laptop 這個產品，讀取這份 xlsx 的 date 與 quantity 用 matplotlib 繪製 折線圖，title 寫上 laptop，橫軸放上 date，縱軸放上 quantity`

## 預期結果

聊天室會顯示：
- 生成的 Python code
- 執行結果文字
- 若有繪圖，直接顯示圖表圖片
- 若有產生清洗後 DataFrame（`RESULT_DF`），會提供下載連結（xlsx）
