# Section 3 - Workflow Integration (n8n Webhook)

這一節的目標：
1. 在聊天室中觸發 `calendar_query` workflow
2. 使用 LLM structured output 抽取日期/時間資訊
3. 缺欄位時先反問補齊，再用 Yes/No 確認
4. 最後呼叫 n8n webhook 並回傳結果到聊天室

## 啟動

```bash
python manager.py --section 3
```

## UI 設定

右側 `Webhook Integration`：

1. 打開 `Enable Webhook Mode`
2. 在 `Calendar Query Webhook URL` 貼上 n8n 的 **Production URL**

> 建議不要用 `webhook-test` URL，測試模式只在 n8n 按下 Listen 時有效。

## 對話流程

使用者：`幫我查行事曆，看看我這週五有沒有會議`

系統會：
1. 判斷為 `calendar_query`
2. 用 structured output 抽取日期/時間
3. 若缺資料，反問（例如：請補充時間區間）
4. 收齊後顯示 Yes/No 確認
5. Yes 後呼叫 webhook

## 傳給 n8n 的 payload

```json
{
  "workflow": "calendar_query",
  "query_text": "幫我查行事曆，看看我這週五有沒有會議",
  "date": "這週五",
  "time": "下午",
  "date_iso": "2026-03-27",
  "time_slot": "afternoon",
  "start_time": "13:00",
  "end_time": "18:00",
  "timezone": "Asia/Taipei",
  "requested_at": "2026-03-25T20:30:00"
}
```

## n8n 節點建議

1. `Webhook`（POST）
2. （可選）`Set` / `Code` 整理輸入
3. （可選）串 Google Calendar / Outlook / DB
4. `Respond to Webhook` 回傳 JSON

## n8n 回傳格式建議

```json
{
  "ok": true,
  "answer": "你在這週五下午有 2 場會議：10:00 產品會議、15:00 客戶同步"
}
```

聊天室會顯示為：

```text
[Workflow Executed] calendar_query
你在這週五下午有 2 場會議：10:00 產品會議、15:00 客戶同步
```

## 測試句子

1. `幫我查行事曆，看看我這週五有沒有會議`
2. `查一下 2026-03-27 下午有沒有會`
3. `我要看明天整天的行程`

## 範例互動（可直接上課 Demo）

### 範例 1：資訊不完整，系統先反問

使用者：
`幫我查行事曆，看看我這週五有沒有會議`

系統（可能）：
`請補充你要查詢的時間區間（例如 上午/下午/晚上/整天，或 15:00-17:00）。`

使用者：
`下午`

系統：
`我整理到的查詢條件：
- 日期：這週五
- 時間：下午
- 正規化日期：2026-03-27
- 正規化時段：afternoon

是否要送出 calendar webhook 查詢？（Yes / No）`

使用者：
`Yes`

系統：
`[Workflow Executed] calendar_query
你在這週五下午有 2 場會議：10:00 產品會議、15:00 客戶同步`

### 範例 2：一次提供完整資訊

使用者：
`幫我查 2026-03-27 15:00-17:00 有沒有會議`

系統：
`[Router → WORKFLOW] calendar_query ...（略）
是否要送出 calendar webhook 查詢？（Yes / No）`

使用者：
`Yes`

系統：
`[Workflow Executed] calendar_query ...`

### 範例 3：使用者拒絕執行

使用者：
`幫我查明天下午有沒有會議`

（收集完條件後）

使用者：
`No`

系統：
`你選擇不執行此步驟，已取消 calendar webhook 查詢。`

## 課堂 Demo 建議順序

1. 先測「資訊不完整」情境（讓學生看到反問）
2. 再測「完整資訊」情境（讓學生看到直接進確認）
3. 最後測 `No`（讓學生看到人類保留決策權）

