# Section 6 - Production Ready

Section 6 聚焦兩件事：

1. Multi-Demand（單一 prompt 多任務）
2. Cost Management（token / cost 觀測）

## 啟動

```bash
python manager.py --section 6
```

## UI（Production Mode）

Section 6 的 `Production Mode` 只保留兩個開關：

- `Enable Multi-Demand`
- `Enable Cost Management`

## 模型費率表（可自行修改）

檔案：

- `section_6_production_ready/pricing.json`

目前預設（含匯率）：

- `usd_to_twd`: 32.0
- `gpt-5.4`: input USD $2.50 / 1M, output USD $15.00 / 1M
- `gpt-5.4-nano`: input USD $0.20 / 1M, output USD $1.25 / 1M
- `gpt-4o`: input USD $2.50 / 1M, output USD $10.00 / 1M

你可以讓學員直接改這份 JSON，系統會自動套用。

## 成本與 token 顯示

當 `Enable Cost Management` 開啟後：

- 每個 assistant 對話泡泡底部會顯示：
  - model
  - input token（text/image/file + total）
  - output token
  - total token
  - cost
- 聊天室標題會顯示累積：`Tokens` 與 `NTD`（台幣）。

> 註：目前 token 為教學版估算（會以 `≈` 標示），已包含文字、圖片、表格檔案估算分量。

## Multi-Demand 行為

當 `Enable Multi-Demand` 開啟時，系統會嘗試把一段訊息拆成多個子任務依序執行。

可用格式示例：

```text
1. 幫我搜尋 Nvidia 和 Apple 市值
2. 再幫我畫 Nvidia vs Apple 柱狀圖
```

或：

```text
先幫我建立任務：明天下午交報告；然後再上網查 OpenAI function calling best practices
```

系統會用 `[Multi-Demand]` 回傳每個子任務結果。

## 測試範例

### A. 成本觀測

1. 切模型到 `gpt-5.4`
2. 問：`請幫我整理 2026 AI agent trend 的三點重點`
3. 切模型到 `gpt-4o`
4. 再問：`同樣主題，改成給我比較商務導向的版本`

預期：

- 兩則回覆泡泡的 model / token / cost 會不同
- 聊天室累積成本會把兩種模型都加總

### B. 多任務（相依）

```text
1. 請幫我上網查 Nvidia 和 Apple 市值
2. 根據查到的結果畫柱狀圖，標題寫 nvidia vs apple
```

### C. 多任務（非相依）

```text
請幫我建立任務：整理下週課程投影片；另外再查 OpenAI function calling best practices
```
