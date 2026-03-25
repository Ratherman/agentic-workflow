# Section 0 - Basic LLM Backend

## What This Section Demonstrates
- LLM chat API (`/chat`)
- Model switching (`gpt-5.4`, `gpt-5.4-nano`, `gpt-4o`)
- Conversation memory (1~10 rounds)
- RAG (Top-1 retrieval from local QA JSON + vector DB)
- Image input (upload photo and let LLM read it)

## Files
- `app.py`: HTTP backend server (port configurable)
- `llm.py`: LLM orchestration (memory, rag, image)
- `prompt.py`: prompt builder
- `embedding.py`: generate vector DB from `company_qa.json`
- `sample_data/company_qa.json`: 10 enterprise QA records with `id`
- `sample_data/qa_vectors.json`: generated vector DB

## 1) Generate Vector DB (first time)
```bash
python section_0_basic_llm/embedding.py
```

## 1.1 Update QA And Rebuild Embeddings
當你新增或修改 `sample_data/company_qa.json` 後，請重新產生向量檔：

```bash
python section_0_basic_llm/embedding.py
```

會更新：
- `section_0_basic_llm/sample_data/qa_vectors.json`

建議流程：
1. 先編輯 `company_qa.json`（每筆保留 `id`, `question`, `answer`）
2. 執行 `embedding.py` 重建向量
3. 重新啟動 Section 0（或至少重啟後端）讓最新向量生效

## 2) Run via manager
```bash
python manager.py --section 0
```

## 3) Prompt Samples (Copy/Paste)
### Basic policy Q&A
- `住宿報銷上限是多少？`
- `忘記密碼應該怎麼處理？`

### Memory test
1. `我叫王小明，請記住我的名字。`
2. `我剛剛叫什麼名字？`

### RAG relevance test
- `公司試用期多久？`
- `今天台北會下雨嗎？`  
  (RAG 不相關時，模型不應硬套 QA 答案)

### Same fact, varied wording test
- `年假最小請假單位是什麼？`
- `如果我要請年假，最少要請幾天？`
- `請用另一種說法回答：年假最低請假單位是？`
- `不要改變事實，但換個語氣再回答一次。`

### Image test
- 上傳一張收據照片，問：`請幫我判斷這張收據內容有什麼重點？`
- 上傳一張會議白板照片，問：`請整理這張圖的待辦事項。`

## Notes
- 若啟用 RAG，回覆若有使用到檢索結果，會帶 `(Reference: QA #id)`。
- 即使 reference 相同（例如都命中 QA #2），模型也會嘗試用不同措辭回覆。
- `OPENAI_API_KEY` 請放在專案根目錄 `.env`。
