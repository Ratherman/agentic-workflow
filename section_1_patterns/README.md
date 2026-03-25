# Section 1 - Patterns + Structured Output

這一節的目標：
1. 用 Router 判斷使用者意圖（`tool` / `workflow` / `code` / `llm`）
2. 比較兩種結構化輸出（`prompt_only` vs `pydantic`）
3. 只做判斷與 Yes/No 確認，不真正執行 action

## 啟動

```bash
python manager.py --section 1
```

## UI 設定建議

在右側 `Patterns`：

1. `LLM Mode`
- `LLM-based (advanced)`：由 LLM 當 Router
- `Rule-based`：由關鍵字規則判斷，不使用 Router LLM（中文優先）

2. `Structured Mode`
- `prompt_only`
- `pydantic`

注意：`Structured Mode` 只在 `LLM-based` 有作用；`Rule-based` 會忽略它。

## Rule-based 中文關鍵字（摘要）

- `create_task`：`建立任務`、`新增任務`、`代辦`、`待辦`、`提醒我`
- `search_web`：`查網路`、`上網查`、`搜尋網路`、`查資料`
- `calendar_query`：`查行事曆`、`查日曆`、`看行程`、`排程`、`時間安排`
- `code_execution`：`執行程式碼`、`執行 python`、`跑程式`、`code execution`

## Router 支援的目標

- Tool
  - `create_task`
  - `search_web`
- Workflow
  - `calendar_query`
- Code
  - `code_execution`
- LLM
  - `none`

## Rule-based Demo（建議先測）

1. `幫我建立任務：明天下午 3 點交報告`
預期：`[Router → TOOL] create_task`

2. `請幫我上網查一下 2026 AI agent 最新趨勢`
預期：`[Router → TOOL] search_web`

3. `幫我查行事曆，看看我這週五有沒有會議`
預期：`[Router → WORKFLOW] calendar_query`

4. `幫我執行一段 python，計算 1 到 100 的總和`
預期：`[Router → CODE] code_execution`

5. `請解釋一下什麼是 RAG`
預期：`[Router → LLM]`

## Yes / No 確認流程

當 Router 判斷為 `tool` / `workflow` / `code` 時，聊天室會出現：

`是否要執行這個動作？（Yes / No）`

- `Yes`
  - Tool: 顯示「將於 Section 2 實作」
  - Workflow `calendar_query`: 顯示「將於 Section 3 實作」
  - Code `code_execution`: 顯示「將於 Section 4 實作」
- `No`
  - 取消本次動作
