import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, request

from openai import OpenAI
from pydantic import BaseModel

from section_2_tool_calling.agent import handle_section2_chat


class CalendarSlot(BaseModel):
    has_date: bool = False
    has_time: bool = False
    date_phrase: str = ""
    time_phrase: str = ""


class CalendarExtractResult(BaseModel):
    has_date: bool
    has_time: bool
    date_phrase: str
    time_phrase: str

WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

CN_HOUR_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}

_SKILL_FILE_PATH = Path(__file__).resolve().parent / "skill.md"

DEFAULT_INVOICE_FIELDS = ["tax_id", "title", "date"]


def _is_confirmation_message(text: str) -> Optional[bool]:
    normalized = text.strip().lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    return None


def _to_webhook_enabled(config: Dict[str, Any]) -> bool:
    webhook_cfg = config.get("webhook", {}) if isinstance(config, dict) else {}
    return bool(webhook_cfg.get("enabled", False))


def _to_calendar_webhook_url(config: Dict[str, Any]) -> str:
    webhook_cfg = config.get("webhook", {}) if isinstance(config, dict) else {}
    endpoints = webhook_cfg.get("endpoints", {}) if isinstance(webhook_cfg, dict) else {}
    if isinstance(endpoints, dict):
        return str(endpoints.get("calendar_query", "")).strip()
    return ""


def _to_webhook_mode(config: Dict[str, Any]) -> str:
    webhook_cfg = config.get("webhook", {}) if isinstance(config, dict) else {}
    mode = webhook_cfg.get("mode", "manual") if isinstance(webhook_cfg, dict) else "manual"
    return mode if mode in {"auto", "manual"} else "manual"


def _to_skill_enabled(config: Dict[str, Any]) -> bool:
    skill_cfg = config.get("skills", {}) if isinstance(config, dict) else {}
    return bool(skill_cfg.get("enabled", False))


def _looks_like_calendar_intent(text: str) -> bool:
    raw = (text or "").strip()
    lowered = raw.lower()
    direct_keywords = [
        "行事曆",
        "日曆",
        "行程",
        "會議",
        "calendar",
        "schedule",
        "查詢時間",
        "排程",
        "查空檔",
        "查空閒",
    ]
    availability_keywords = [
        "有沒有空",
        "有空嗎",
        "是否有空",
        "空檔",
        "空嗎",
        "available",
        "availability",
        "free time",
        "free slot",
    ]
    datetime_keywords = [
        "今天",
        "明天",
        "後天",
        "這週",
        "本週",
        "下週",
        "週",
        "星期",
        "禮拜",
        "上午",
        "下午",
        "晚上",
        "中午",
        "整天",
        "全天",
        "點",
        ":",
        "am",
        "pm",
    ]

    has_direct = any(k in lowered for k in direct_keywords)
    has_availability = any(k in lowered for k in availability_keywords)
    has_datetime = (
        any(k in raw for k in datetime_keywords)
        or bool(re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", raw))
        or bool(re.search(r"\d{1,2}[/-]\d{1,2}", raw))
    )
    return has_direct or (has_availability and has_datetime)


def _looks_like_invoice_skill_intent(text: str) -> bool:
    lowered = (text or "").lower()
    direct_keywords = [
        "發票辨識",
        "辨識發票",
        "發票ocr",
        "invoice ocr",
        "invoice recognition",
    ]
    context_keywords = ["發票", "invoice"]
    field_keywords = ["辨識", "ocr", "統一編號", "統編", "抬頭", "發票內容", "價格", "金額", "price", "amount"]
    return (
        any(k in lowered for k in direct_keywords)
        or (
            any(k in lowered for k in context_keywords)
            and any(k in lowered for k in field_keywords)
        )
    )


def _load_invoice_skill_markdown() -> str:
    if not _SKILL_FILE_PATH.exists():
        return (
            "# Invoice OCR Skill\n"
            "請從圖片擷取統一編號、抬頭、日期，並以 JSON 回傳 tax_id/title/date。"
        )
    return _SKILL_FILE_PATH.read_text(encoding="utf-8")


def _parse_skill_output_fields(skill_markdown: str) -> List[str]:
    block_match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", skill_markdown, flags=re.IGNORECASE)
    if not block_match:
        return DEFAULT_INVOICE_FIELDS.copy()

    try:
        payload = json.loads(block_match.group(1))
    except Exception:
        return DEFAULT_INVOICE_FIELDS.copy()

    if not isinstance(payload, dict):
        return DEFAULT_INVOICE_FIELDS.copy()

    fields: List[str] = []
    for key in payload.keys():
        cleaned = str(key).strip()
        if cleaned:
            fields.append(cleaned)
    return fields or DEFAULT_INVOICE_FIELDS.copy()


def _normalize_skill_output(raw_payload: Dict[str, Any], fields: List[str]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for field in fields:
        value = raw_payload.get(field, "")
        if value is None:
            normalized[field] = ""
        elif isinstance(value, str):
            normalized[field] = value.strip()
        else:
            normalized[field] = str(value).strip()
    return normalized


def _extract_invoice_fields_with_skill(
    user_message: str,
    image_data_url: str,
    llm_cfg: Dict[str, Any],
) -> Dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY，暫時無法執行發票辨識 Skill。")

    model = llm_cfg.get("model", "gpt-4o") if isinstance(llm_cfg, dict) else "gpt-4o"
    skill_markdown = _load_invoice_skill_markdown()
    fields = _parse_skill_output_fields(skill_markdown)
    fields_text = ", ".join(fields)
    system_prompt = (
        "你是 Invoice OCR Skill Runner，僅在需要時讀取並遵守以下 skill 指引。\n"
        "你只能回傳 JSON，不要加任何額外文字。\n"
        f"JSON 欄位只能有：{fields_text}。\n"
        "date 優先轉為 YYYY-MM-DD，無法判斷時保留原字串。\n\n"
        f"{skill_markdown}"
    )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "請依 skill.md 規則辨識這張發票。\n"
                            f"使用者補充：{user_message}"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
    )

    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("Skill 回傳格式錯誤：不是 JSON 物件。")
    return _normalize_skill_output(raw_payload=payload, fields=fields)


def _format_invoice_skill_result(result: Dict[str, str]) -> str:
    lines = ["[Skill Executed] invoice_ocr"]
    for field, value in result.items():
        display_value = value or "(未辨識)"
        lines.append(f"- {field}: {display_value}")
    lines.append("")
    lines.append("欄位由 skill.md 的 Output Schema 決定；修改 skill.md 後會直接生效。")
    return "\n".join(lines)


def _to_invoice_skill_error_message(exc: Exception) -> str:
    text = str(exc).lower()
    if "api key" in text or "authentication" in text or "401" in text:
        return "OCR 驗證失敗，請確認 OPENAI_API_KEY。"
    return "發票辨識暫時失敗，請稍後再試。"


def _heuristic_extract(text: str) -> CalendarExtractResult:
    lowered = (text or "").lower()
    date_tokens = [
        "今天", "明天", "後天", "本週", "這週", "下週", "週", "星期", "禮拜", "月", "號", "日", "-", "/",
    ]
    time_tokens = [
        "整天", "全天", "上午", "早上", "中午", "下午", "晚上", "今晚", "pm", "am", ":", "點",
    ]

    has_date = any(t in text for t in date_tokens)
    has_time = any(t in lowered for t in time_tokens)

    date_phrase = text.strip() if has_date else ""
    time_phrase = text.strip() if has_time else ""

    return CalendarExtractResult(
        has_date=has_date,
        has_time=has_time,
        date_phrase=date_phrase,
        time_phrase=time_phrase,
    )


def _extract_datetime_with_llm(user_message: str, llm_cfg: Dict[str, Any]) -> CalendarExtractResult:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _heuristic_extract(user_message)

    model = llm_cfg.get("model", "gpt-4o") if isinstance(llm_cfg, dict) else "gpt-4o"
    prompt = (
        "你是日期時間抽取器。請從使用者輸入抽取行事曆查詢需要的欄位，輸出 JSON。\\n"
        "欄位：has_date(boolean), has_time(boolean), date_phrase(string), time_phrase(string)。\\n"
        "規則：\\n"
        "1) '這週五'、'下週二'、'明天' 都算 has_date=true。\\n"
        "2) '上午/下午/晚上/整天/15:00/三點' 都算 has_time=true。\\n"
        "3) 無法判斷就填 false，字串填空。"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        payload = json.loads(raw)
        return CalendarExtractResult.model_validate(payload)
    except Exception:
        return _heuristic_extract(user_message)


def _merge_slot(current: CalendarSlot, extracted: CalendarExtractResult) -> CalendarSlot:
    date_phrase = current.date_phrase
    time_phrase = current.time_phrase

    if extracted.has_date and extracted.date_phrase.strip():
        date_phrase = extracted.date_phrase.strip()
    if extracted.has_time and extracted.time_phrase.strip():
        time_phrase = extracted.time_phrase.strip()

    return CalendarSlot(
        has_date=bool(date_phrase),
        has_time=bool(time_phrase),
        date_phrase=date_phrase,
        time_phrase=time_phrase,
    )


def _build_missing_question(slot: CalendarSlot) -> str:
    if not slot.has_date and not slot.has_time:
        return "我需要先確認查詢條件：請提供日期與時間區間（例如 2026-03-27 下午）。"
    if not slot.has_date:
        return "請補充你要查詢的日期（例如 2026-03-27，或這週五）。"
    if not slot.has_time:
        return "請補充你要查詢的時間區間（例如 上午/下午/晚上/整天，或 15:00-17:00）。"
    return ""


def _normalize_date_phrase(raw_text: str) -> Optional[str]:
    text = (raw_text or "").strip()
    if not text:
        return None

    today = datetime.now().date()

    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if m:
        y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        try:
            return datetime(today.year, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            return None

    if "今天" in text:
        return today.strftime("%Y-%m-%d")
    if "明天" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "後天" in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    m = re.search(r"(這|本|下)?\s*(週|周|星期|禮拜)\s*([一二三四五六日天])", text)
    if m:
        prefix = m.group(1) or ""
        target_wd = WEEKDAY_MAP[m.group(3)]
        start_of_week = today - timedelta(days=today.weekday())
        week_offset = 1 if prefix == "下" else 0
        candidate = start_of_week + timedelta(days=target_wd, weeks=week_offset)
        if prefix == "" and candidate < today:
            candidate = candidate + timedelta(weeks=1)
        return candidate.strftime("%Y-%m-%d")

    return None


def _normalize_time_phrase(raw_text: str) -> Dict[str, str]:
    text = (raw_text or "").strip().lower()
    if not text:
        return {"time_slot": "", "start_time": "", "end_time": ""}

    if any(k in text for k in ["整天", "全天", "all day"]):
        return {"time_slot": "full_day", "start_time": "00:00", "end_time": "23:59"}
    if any(k in text for k in ["上午", "早上", "morning"]):
        return {"time_slot": "morning", "start_time": "09:00", "end_time": "12:00"}
    if "中午" in text:
        return {"time_slot": "noon", "start_time": "12:00", "end_time": "13:30"}
    if any(k in text for k in ["下午", "afternoon"]):
        return {"time_slot": "afternoon", "start_time": "13:00", "end_time": "18:00"}
    if any(k in text for k in ["晚上", "今晚", "evening", "night"]):
        return {"time_slot": "evening", "start_time": "18:00", "end_time": "22:00"}

    m = re.search(r"(\d{1,2}):(\d{2})\s*[-~到]\s*(\d{1,2}):(\d{2})", text)
    if m:
        return {
            "time_slot": "custom_range",
            "start_time": f"{int(m.group(1)):02d}:{int(m.group(2)):02d}",
            "end_time": f"{int(m.group(3)):02d}:{int(m.group(4)):02d}",
        }

    m = re.search(r"(\d{1,2})\s*[-~到]\s*(\d{1,2})\s*點", text)
    if m:
        return {
            "time_slot": "custom_range",
            "start_time": f"{int(m.group(1)):02d}:00",
            "end_time": f"{int(m.group(2)):02d}:00",
        }

    m = re.search(r"(\d{1,2})(?::(\d{2}))?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or "0")
        if "下午" in text and hour < 12:
            hour += 12
        if "晚上" in text and hour < 12:
            hour += 12
        end_hour = min(hour + 1, 23)
        return {
            "time_slot": "specific_time",
            "start_time": f"{hour:02d}:{minute:02d}",
            "end_time": f"{end_hour:02d}:{minute:02d}",
        }

    m = re.search(r"(十一|十二|十|[一二三四五六七八九])\s*點", text)
    if m:
        cn = m.group(1)
        hour = CN_HOUR_MAP.get(cn, 9)
        if "下午" in text and hour < 12:
            hour += 12
        if "晚上" in text and hour < 12:
            hour += 12
        end_hour = min(hour + 1, 23)
        return {
            "time_slot": "specific_time",
            "start_time": f"{hour:02d}:00",
            "end_time": f"{end_hour:02d}:00",
        }

    return {"time_slot": "", "start_time": "", "end_time": ""}


def _normalize_slot(slot: CalendarSlot) -> Dict[str, str]:
    normalized_date = _normalize_date_phrase(slot.date_phrase)
    normalized_time = _normalize_time_phrase(slot.time_phrase)
    return {
        "date_iso": normalized_date or "",
        "time_slot": normalized_time["time_slot"],
        "start_time": normalized_time["start_time"],
        "end_time": normalized_time["end_time"],
    }


def _build_confirm_summary(slot: CalendarSlot) -> str:
    normalized = _normalize_slot(slot)
    return (
        "我整理到的查詢條件：\n"
        f"- 日期：{slot.date_phrase}\n"
        f"- 時間：{slot.time_phrase}\n"
        f"- 正規化日期：{normalized['date_iso'] or '(待人工解讀)'}\n"
        f"- 正規化時段：{normalized['time_slot'] or '(待人工解讀)'}\n\n"
        "是否要送出 calendar webhook 查詢？（Yes / No）"
    )


def _post_calendar_webhook(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {"ok": True, "answer": "Webhook 已執行，但未回傳內容。"}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"ok": True, "answer": raw}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"webhook HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"webhook 呼叫失敗：{exc}") from exc


def _format_webhook_result(result: Dict[str, Any]) -> str:
    def pick_text(payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, (int, float, bool)):
            return str(payload)
        if isinstance(payload, dict):
            preferred_keys = ["answer", "result", "message", "text", "output"]
            for key in preferred_keys:
                if key in payload:
                    picked = pick_text(payload.get(key))
                    if picked:
                        return picked
            # Common wrappers from automation systems.
            wrapper_keys = ["body", "data", "json", "response"]
            for key in wrapper_keys:
                if key in payload:
                    picked = pick_text(payload.get(key))
                    if picked:
                        return picked
            # Fallback: search all values.
            for value in payload.values():
                picked = pick_text(value)
                if picked:
                    return picked
            return ""
        if isinstance(payload, list):
            for item in payload:
                picked = pick_text(item)
                if picked:
                    return picked
            return ""
        return ""

    answer = pick_text(result)
    if answer:
        return f"[Workflow Executed] calendar_query\n{answer}"

    return "[Workflow Executed] calendar_query\n已完成 webhook 查詢。"


def _execute_calendar_webhook(config: Dict[str, Any], slot: CalendarSlot, original_query: str) -> Dict[str, Any]:
    webhook_enabled = _to_webhook_enabled(config)
    webhook_url = _to_calendar_webhook_url(config)
    if not webhook_enabled:
        return {
            "reply": "Webhook Mode 尚未啟用，請先在右側開啟 Enable Webhook Mode。",
            "router": {
                "action_type": "workflow",
                "target": "calendar_query",
                "reason": "webhook disabled",
                "mode": "structured",
            },
            "pending_route": None,
        }
    if not webhook_url:
        return {
            "reply": "尚未設定 Calendar Query Webhook URL，請先在右側填入 n8n webhook。",
            "router": {
                "action_type": "workflow",
                "target": "calendar_query",
                "reason": "missing webhook url",
                "mode": "structured",
            },
            "pending_route": None,
        }

    normalized = _normalize_slot(slot)
    payload = {
        "workflow": "calendar_query",
        "query_text": original_query,
        "date": slot.date_phrase,
        "time": slot.time_phrase,
        "date_iso": normalized["date_iso"],
        "time_slot": normalized["time_slot"],
        "start_time": normalized["start_time"],
        "end_time": normalized["end_time"],
        "timezone": "Asia/Taipei",
        "requested_at": datetime.now().isoformat(timespec="seconds"),
    }
    result = _post_calendar_webhook(webhook_url, payload)
    return {
        "reply": _format_webhook_result(result),
        "router": {
            "action_type": "workflow",
            "target": "calendar_query",
            "reason": "webhook executed",
            "mode": "structured",
        },
        "pending_route": None,
    }


def handle_section3_chat(
    user_message: str,
    config: Dict[str, Any],
    history: List[Dict[str, Any]],
    image_data_url: Optional[str] = None,
    router_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    llm_cfg = config.get("llm", {}) if isinstance(config, dict) else {}
    webhook_mode = _to_webhook_mode(config)
    skill_enabled = _to_skill_enabled(config)

    if router_context and router_context.get("stage") == "collect_datetime":
        extracted = _extract_datetime_with_llm(user_message, llm_cfg)
        current_slot = CalendarSlot.model_validate(router_context.get("slot") or {})
        merged = _merge_slot(current_slot, extracted)

        if not (merged.has_date and merged.has_time):
            ask = _build_missing_question(merged)
            return {
                "reply": ask,
                "router": {
                    "action_type": "workflow",
                    "target": "calendar_query",
                    "reason": "collecting datetime fields",
                    "mode": "structured",
                },
                "pending_route": {
                    "action_type": "workflow",
                    "target": "calendar_query",
                    "stage": "collect_datetime",
                    "slot": merged.model_dump(),
                    "original_query": router_context.get("original_query", user_message),
                },
            }

        if webhook_mode == "auto":
            return _execute_calendar_webhook(
                config=config,
                slot=merged,
                original_query=router_context.get("original_query", user_message),
            )
        return {
            "reply": _build_confirm_summary(merged),
            "router": {
                "action_type": "workflow",
                "target": "calendar_query",
                "reason": "datetime collected",
                "mode": "structured",
            },
            "pending_route": {
                "action_type": "workflow",
                "target": "calendar_query",
                "stage": "confirm_execute",
                "slot": merged.model_dump(),
                "original_query": router_context.get("original_query", user_message),
            },
        }

    if router_context and router_context.get("stage") == "confirm_execute":
        confirm = _is_confirmation_message(user_message)
        if confirm is None:
            return {
                "reply": "請使用聊天室中的 Yes 或 No 按鈕確認是否執行 calendar webhook。",
                "router": {
                    "action_type": "workflow",
                    "target": "calendar_query",
                    "reason": "awaiting yes/no",
                    "mode": "structured",
                },
                "pending_route": router_context,
            }

        if confirm is False:
            return {
                "reply": "你選擇不執行此步驟，已取消 calendar webhook 查詢。",
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "user rejected calendar webhook",
                    "mode": "structured",
                },
                "pending_route": None,
            }

        slot = CalendarSlot.model_validate(router_context.get("slot") or {})
        return _execute_calendar_webhook(
            config=config,
            slot=slot,
            original_query=router_context.get("original_query", ""),
        )

    if _looks_like_invoice_skill_intent(user_message):
        if not image_data_url:
            return {
                "reply": (
                    "[Router → SKILL] invoice_ocr\n"
                    "Reason: 偵測到發票辨識需求。\n\n"
                    "請同時上傳發票圖片，我才能執行 Invoice OCR Skill。"
                ),
                "router": {
                    "action_type": "skill",
                    "target": "invoice_ocr",
                    "reason": "invoice skill detected but missing image",
                    "mode": "structured",
                },
                "pending_route": None,
            }

        if not skill_enabled:
            return {
                "reply": (
                    "[Router → SKILL] invoice_ocr\n"
                    "Reason: 偵測到發票辨識需求。\n\n"
                    "你尚未開啟 `Enable Skills`。\n"
                    "請到右側 Control Panel 開啟後，再重新送出同一則訊息與圖片。"
                ),
                "router": {
                    "action_type": "skill",
                    "target": "invoice_ocr",
                    "reason": "invoice skill detected but skills disabled",
                    "mode": "structured",
                },
                "pending_route": None,
            }

        try:
            extracted = _extract_invoice_fields_with_skill(
                user_message=user_message,
                image_data_url=image_data_url,
                llm_cfg=llm_cfg,
            )
            return {
                "reply": _format_invoice_skill_result(extracted),
                "router": {
                    "action_type": "skill",
                    "target": "invoice_ocr",
                    "reason": "invoice skill executed",
                    "mode": "structured",
                },
                "pending_route": None,
            }
        except Exception as exc:  # noqa: BLE001
            safe_error = _to_invoice_skill_error_message(exc)
            return {
                "reply": (
                    "[Router → SKILL] invoice_ocr\n"
                    "Reason: 偵測到發票辨識需求。\n\n"
                    f"Skill 執行失敗：{safe_error}"
                ),
                "router": {
                    "action_type": "skill",
                    "target": "invoice_ocr",
                    "reason": f"invoice skill failed: {safe_error}",
                    "mode": "structured",
                },
                "pending_route": None,
            }

    if _looks_like_calendar_intent(user_message):
        extracted = _extract_datetime_with_llm(user_message, llm_cfg)
        slot = CalendarSlot(
            has_date=extracted.has_date,
            has_time=extracted.has_time,
            date_phrase=extracted.date_phrase.strip(),
            time_phrase=extracted.time_phrase.strip(),
        )

        if not (slot.has_date and slot.has_time):
            ask = _build_missing_question(slot)
            return {
                "reply": f"[Router → WORKFLOW] calendar_query\nReason: 偵測到行事曆查詢需求。\n\n{ask}",
                "router": {
                    "action_type": "workflow",
                    "target": "calendar_query",
                    "reason": "calendar intent detected",
                    "mode": "structured",
                },
                "pending_route": {
                    "action_type": "workflow",
                    "target": "calendar_query",
                    "stage": "collect_datetime",
                    "slot": slot.model_dump(),
                    "original_query": user_message,
                },
            }

        if webhook_mode == "auto":
            return _execute_calendar_webhook(config=config, slot=slot, original_query=user_message)

        summary = (
            "[Router → WORKFLOW] calendar_query\n"
            "Reason: 偵測到行事曆查詢需求。\n\n"
            f"{_build_confirm_summary(slot)}"
        )
        return {
            "reply": summary,
            "router": {
                "action_type": "workflow",
                "target": "calendar_query",
                "reason": "calendar intent detected",
                "mode": "structured",
            },
            "pending_route": {
                "action_type": "workflow",
                "target": "calendar_query",
                "stage": "confirm_execute",
                "slot": slot.model_dump(),
                "original_query": user_message,
            },
        }

    return handle_section2_chat(
        user_message=user_message,
        config=config,
        history=history,
        image_data_url=image_data_url,
        router_context=router_context,
    )
