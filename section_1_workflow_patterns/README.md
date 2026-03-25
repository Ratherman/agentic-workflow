# Section 1 - LLM Routing + Structured Output

這一節的目標是：
1. 用 Router 判斷使用者意圖（`tool` / `workflow` / `llm`）
2. 比較兩種結構化輸出（`prompt_only` vs `pydantic`）
3. 只做判斷與 Yes/No 確認，不真正執行 action

## 啟動

```bash
python manager.py --section 1
```

## UI 設定建議

在右側 `Workflow Routing`：

1. `LLM Mode`
- `LLM-based (advanced)`：由 LLM 當 Router
- `Rule-based`：由關鍵字規則判斷，不使用 Router LLM（中文優先）

2. `Structured Mode`
- `prompt_only`
- `pydantic`

注意：`Structured Mode` 只在 `LLM-based` 有作用；`Rule-based` 會忽略它。

## Rule-based 中文關鍵字（摘要）

- `create_task`：`建立任務`、`新增任務`、`代辦`、`待辦`、`提醒我`、`幫我記得`
- `search_web`：`查網路`、`上網查`、`搜尋網路`、`查資料`
- `article_research`：`研究文章`、`文章研究`、`文獻研究`、`資料彙整`
- `calendar_query`：`查行事曆`、`查日曆`、`看行程`、`排程`、`時間安排`

## Router 支援的目標

- Tool
  - `create_task`
  - `search_web`
- Workflow
  - `article_research`
  - `calendar_query`
- LLM
  - `none`

## Rule-based Demo（建議先測）

先把 `LLM Mode` 切到 `Rule-based`。

可直接貼這些句子：

1. `幫我建立任務：明天下午 3 點交報告`
預期：`[Router → TOOL] create_task`

2. `請幫我上網查一下 2026 AI agent 最新趨勢`
預期：`[Router → TOOL] search_web`

3. `幫我做一個 article research，主題是多代理協作`
預期：`[Router → WORKFLOW] article_research`

4. `幫我查行事曆，看看我這週五有沒有會議`
預期：`[Router → WORKFLOW] calendar_query`

5. `請解釋一下什麼是 RAG`
預期：`[Router → LLM]`

## LLM-based + Structured Mode Demo

把 `LLM Mode` 切到 `LLM-based (advanced)`。

### A. prompt_only（較不穩定）

1. `請幫我安排一個任務：下週一提醒我寄出合約`
2. `幫我做文章研究，主題是企業導入 Agent 的風險`
3. `請幫我搜尋網路：OpenAI function calling best practices`

觀察重點：
- 有時候 Router JSON 可能格式不穩
- 系統會 fallback，reason 可能出現 parse failed

### B. pydantic（較穩定）

1. `幫我查一下這週的會議行程`
2. `請幫我搜尋網路：OpenAI function calling best practices`

觀察重點：
- 輸出會更穩定地符合 schema
- 若第一次驗證失敗，系統會 retry，再 fallback
- 常見錯誤（例如把 `calendar_query` 填在 `action_type`）會自動校正

## Yes / No 確認流程

當 Router 判斷為 `tool` 或 `workflow` 時，聊天室會出現：

`是否要執行這個動作？（Yes / No）`

- `Yes`
  - Tool: 顯示「將於 Section 2 實作」
  - Workflow: 顯示「將於 Section 3 實作」
- `No`
  - fallback 到一般 LLM 回答

## 教學提示

1. 同一句話在 `Rule-based` 通常固定結果
2. 同一句話在 `LLM-based` 可能因語境有不同判斷
3. `prompt_only` 與 `pydantic` 的差異，是這節最重要的教學點
