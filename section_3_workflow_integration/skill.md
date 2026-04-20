# Skill: invoice_ocr

## Meta
- skill_id: `invoice_ocr`
- version: `1.1.0`
- owner: `section_3_workflow_integration`
- load_policy: `on_demand`
- enable_flag: `config.skills.enabled`
- trigger_hint:
  - 使用者在同一則訊息提到發票辨識需求（例如：發票、OCR、統編、抬頭、日期、價格）
  - 使用者有上傳發票圖片

## 目的
從發票圖片擷取欄位，並輸出 JSON。

## 輸出格式（JSON only）
```json
{
  "tax_id": "string",
  "title": "string",
  "date": "string",
}
```

## 欄位規則
1. 只輸出上方 Output Schema 中定義的欄位。
2. 欄位找不到時請回傳空字串 `""`。
3. `date` 若可判斷，優先正規化為 `YYYY-MM-DD`；否則保留原文。
4. 不要補出圖片裡沒有的資訊。

## 教學備註
你可以直接修改本檔 `Output Schema` 欄位，系統會依照這裡的欄位回傳與顯示結果。
