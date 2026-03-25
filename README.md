# agentic-workflow
Agentic Workflow Engineering：從 LLM Agent 到企業自動化流程

## Environment Setup
```bash
conda create -n "agentic-workflow" python=3.11.13
conda activate agentic-workflow
```

## Run Shared UI With Manager
`manager.py` 是專案入口。你只需要兩種模式：`--fresh` 與 `--section`。

### 1. Fresh Mode（Section 0）
```bash
python manager.py --fresh
```
- 開啟 shared UI
- 只解鎖 Section 0 設定
- 若後端未啟動，前端會自動使用 mock thinking 回覆

### 2. 指定 Section
```bash
python manager.py --section 0
python manager.py --section 1
python manager.py --section 2
python manager.py --section 3
python manager.py --section 4
python manager.py --section 5
python manager.py --section 6
```
- `--section N` 會把 UI 解鎖到 Section N
- 例如 `--section 3` 可調整 Section 0~3

## Manager 行為
1. 啟動 shared UI（`shared/ui/index.html`）
2. 自動帶入 `max_section` 控制可用能力
3. 嘗試啟動對應 section 的 `app.py`（若存在）
4. 若沒有 section 後端，會自動 fallback 到 UI-only mock 模式

## Quick Start
```bash
python manager.py --fresh
```
