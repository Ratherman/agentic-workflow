import json
from typing import Any, Dict, Tuple

from openai import OpenAI
from section_1_patterns.schemas import RouteDecision

ALLOWED_WORKFLOWS = ["calendar_query", "code_execution"]
ALLOWED_TOOLS = ["search_web", "create_task"]


def route_with_rules(user_message: str) -> RouteDecision:
    text = (user_message or "").strip().lower()
    normalized = (
        text.replace("　", " ")
        .replace("：", ":")
        .replace("，", ",")
        .replace("。", ".")
        .replace("？", "?")
    )

    tool_create_task_keywords = [
        "建立任務",
        "新增任務",
        "建立一個任務",
        "加一個任務",
        "代辦",
        "待辦",
        "提醒我",
        "幫我記得",
        "create task",
        "add task",
        "todo",
    ]
    tool_search_web_keywords = [
        "查網路",
        "上網查",
        "搜尋網路",
        "查一下網路",
        "幫我查資料",
        "查資料",
        "search web",
        "google",
    ]
    workflow_calendar_keywords = [
        "查行事曆",
        "看行程",
        "會議安排",
        "查日曆",
        "排程",
        "時間安排",
        "今天有會議嗎",
        "calendar",
        "schedule",
    ]
    workflow_code_keywords = [
        "執行程式碼",
        "執行 python",
        "執行一段 python",
        "python 程式",
        "python代碼",
        "python 程式碼",
        "跑程式",
        "跑一段程式",
        "code execution",
        "run code",
        "execute code",
    ]

    if any(keyword in normalized for keyword in tool_create_task_keywords):
        return RouteDecision(
            action_type="tool",
            target="create_task",
            reason="規則命中：任務建立相關關鍵字",
        )
    if any(keyword in normalized for keyword in tool_search_web_keywords):
        return RouteDecision(
            action_type="tool",
            target="search_web",
            reason="規則命中：網路搜尋相關關鍵字",
        )
    if any(keyword in normalized for keyword in workflow_calendar_keywords):
        return RouteDecision(
            action_type="workflow",
            target="calendar_query",
            reason="規則命中：行事曆查詢流程關鍵字",
        )
    if (
        ("執行" in normalized or "跑" in normalized or "run" in normalized or "execute" in normalized)
        and ("python" in normalized or "程式碼" in normalized or "代碼" in normalized or "code" in normalized)
    ):
        return RouteDecision(
            action_type="workflow",
            target="code_execution",
            reason="規則命中：程式執行意圖（動詞 + code/python）",
        )
    if any(keyword in normalized for keyword in workflow_code_keywords):
        return RouteDecision(
            action_type="workflow",
            target="code_execution",
            reason="規則命中：程式執行流程關鍵字",
        )

    return RouteDecision(
        action_type="llm",
        target="none",
        reason="未命中規則，改走一般 LLM 回答",
    )


def _build_router_prompt() -> str:
    return (
        "You are a strict intent router. Output JSON only.\\n"
        "Fields: action_type, target, reason.\\n"
        "action_type must be one of: tool, workflow, llm.\\n"
        f"If action_type=workflow, target must be one of: {', '.join(ALLOWED_WORKFLOWS)}.\\n"
        f"If action_type=tool, target must be one of: {', '.join(ALLOWED_TOOLS)}.\\n"
        "If action_type=llm, target must be 'none'.\\n"
        "Routing priority examples:\\n"
        "- Calendar/schedule query -> workflow/calendar_query\\n"
        "- Any request to run/execute code (especially Python) -> workflow/code_execution\\n"
        "- Task creation or web search -> tool target\\n"
        "Do NOT answer the user question; only route it.\\n"
        "Do NOT put a target name into action_type.\\n"
        "reason must be concise and user-facing."
    )


def _normalize_decision(decision: RouteDecision) -> RouteDecision:
    if decision.action_type == "workflow" and decision.target not in ALLOWED_WORKFLOWS:
        return RouteDecision(action_type="llm", target="none", reason="workflow target invalid, fallback to llm")
    if decision.action_type == "tool" and decision.target not in ALLOWED_TOOLS:
        return RouteDecision(action_type="llm", target="none", reason="tool target invalid, fallback to llm")
    if decision.action_type == "llm":
        return RouteDecision(action_type="llm", target="none", reason=decision.reason)
    return decision


def _coerce_decision_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    action_type = str(payload.get("action_type", "")).strip().lower()
    target = str(payload.get("target", "")).strip().lower()
    reason = str(payload.get("reason", "")).strip() or "router decision"

    if action_type in {"tool", "workflow", "llm"}:
        normalized_target = target or "none"
        if action_type == "llm":
            normalized_target = "none"
        return {
            "action_type": action_type,
            "target": normalized_target,
            "reason": reason,
        }

    # Common model mistake: put target into action_type.
    if action_type in ALLOWED_WORKFLOWS:
        return {
            "action_type": "workflow",
            "target": action_type,
            "reason": f"{reason} (auto-corrected from action_type)",
        }
    if action_type in ALLOWED_TOOLS:
        return {
            "action_type": "tool",
            "target": action_type,
            "reason": f"{reason} (auto-corrected from action_type)",
        }

    # Secondary fallback: infer from target if action_type is missing/invalid.
    if target in ALLOWED_WORKFLOWS:
        return {
            "action_type": "workflow",
            "target": target,
            "reason": f"{reason} (auto-inferred from target)",
        }
    if target in ALLOWED_TOOLS:
        return {
            "action_type": "tool",
            "target": target,
            "reason": f"{reason} (auto-inferred from target)",
        }

    return {
        "action_type": "llm",
        "target": "none",
        "reason": f"invalid route payload, fallback to llm: action_type={action_type or 'empty'}, target={target or 'empty'}",
    }


def _parse_route_payload(raw: str) -> RouteDecision:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("router output is not a JSON object")
    normalized = _coerce_decision_payload(data)
    decision = RouteDecision(**normalized)
    return _normalize_decision(decision)


def route_with_prompt_only(
    client: OpenAI,
    model: str,
    user_message: str,
) -> Tuple[RouteDecision, str]:
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": _build_router_prompt()},
            {"role": "user", "content": user_message},
        ],
    )
    raw = response.choices[0].message.content or ""

    try:
        return _parse_route_payload(raw), raw
    except Exception as exc:  # noqa: BLE001
        fallback = RouteDecision(action_type="llm", target="none", reason=f"prompt_only parse failed: {exc}")
        return fallback, raw


def route_with_pydantic(client: OpenAI, model: str, user_message: str) -> Tuple[RouteDecision, str]:
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _build_router_prompt()},
            {"role": "user", "content": user_message},
        ],
    )
    raw = response.choices[0].message.content or ""

    try:
        return _parse_route_payload(raw), raw
    except Exception:
        retry_response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _build_router_prompt() + " Return strict JSON object only."},
                {"role": "user", "content": user_message},
            ],
        )
        retry_raw = retry_response.choices[0].message.content or ""
        try:
            return _parse_route_payload(retry_raw), retry_raw
        except Exception as exc:  # noqa: BLE001
            fallback = RouteDecision(action_type="llm", target="none", reason=f"pydantic parse failed: {exc}")
            return fallback, retry_raw


def route_intent(
    client: OpenAI,
    model: str,
    mode: str,
    user_message: str,
) -> Tuple[RouteDecision, str]:
    if mode == "prompt_only":
        return route_with_prompt_only(
            client=client,
            model=model,
            user_message=user_message,
        )
    return route_with_pydantic(client, model, user_message)
