# Section 2 - Tool Calling

這一節的目標：
1. 讓 Agent 具備「實際呼叫工具」能力
2. 使用 `Enable Tool Calling` 作為總開關
3. 理解 `Tool Mode` 的差異：`Auto` vs `Manual`

## 本節功能範圍（精簡版）

本節只保留兩個工具：
- `Create Task`
- `Search Web (Tavily)`

不包含其他工具（例如寄信、查排程）。

## 啟動方式

```bash
python manager.py --section 2
```

啟動後請在 UI 右側確認目前是 `Section 2`。

## 環境變數

請在專案根目錄 `.env` 設定：

```env
TAVILY_API_KEY=你的_tavily_api_key
```

若未設定，`Search Web` 會回傳提示錯誤訊息，不會中斷整體對話。

## Control Panel（Tool Calling）

### 1. Enable Tool Calling
- `Off`：即使 Router 判斷應該用 tool，也不執行工具，會 fallback 到一般 LLM 回答
- `On`：允許工具被執行

### 2. Available Tools
固定顯示：
- `Create Task`
- `Search Web (Tavily)`

### 3. Tool Mode
- `Auto (LLM decides)`：Router 判斷為 tool 後，直接執行
- `Manual (debug)`：Router 判斷為 tool 後，先詢問 Yes/No，再決定是否執行

## 可直接測試的句子

### A. Create Task
1. `幫我建立任務：明天下午三點交報告`
2. `新增任務：整理下週課程投影片`

預期：
- 會呼叫 `create_task`
- 任務會寫入 `data/tasks.json`
- 右側 Task Panel 可看到新任務（source 會是 `tool`）

### B. Search Web (Tavily)
1. `請幫我搜尋：OpenAI function calling best practices`
2. `幫我查網路：2026 AI agent trend`

預期：
- 會呼叫 `search_web`
- 回覆中會先顯示 LLM 摘要，並附上 Tavily 來源連結（References）

## 教學重點建議

1. 先把 `Enable Tool Calling` 關閉，讓學生看 fallback 行為
2. 再打開 `Enable Tool Calling`，比較「有工具」和「無工具」差異
3. 最後切換 `Auto` / `Manual`，讓學生理解「自動執行 vs 人工確認」

## 補充說明

- `Create Task` 會與 UI Task Panel 共用同一份 persistent JSON（`data/tasks.json`）
- `Manual` 模式下，確認流程使用聊天室中的 Yes/No 按鈕
- Workflow 類動作（非本節重點）仍會提示將於 Section 3 實作

