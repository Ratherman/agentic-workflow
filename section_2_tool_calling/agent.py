import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from section_0_basic_llm.llm import run_chat
from section_1_patterns.schemas import RouteDecision
from section_2_tool_calling.tools import create_task, search_web

WORKFLOW_TARGETS = ["calendar_query"]
TOOL_TARGETS = ["create_task", "search_web"]

TOOL_REGISTRY = {
    "create_task": create_task.run,
    "search_web": search_web.run,
}


def _to_llm_mode(config: Dict[str, Any]) -> str:
    workflow = config.get("workflow", {}) if isinstance(config, dict) else {}
    mode = workflow.get("mode", "llm")
    return mode if mode in {"llm", "rule"} else "llm"


def _to_router_mode(config: Dict[str, Any]) -> str:
    workflow = config.get("workflow", {}) if isinstance(config, dict) else {}
    mode = workflow.get("router_mode", "pydantic")
    return mode if mode in {"prompt_only", "pydantic"} else "pydantic"


def _to_tool_enabled(config: Dict[str, Any]) -> bool:
    tool_cfg = config.get("tool", {}) if isinstance(config, dict) else {}
    return bool(tool_cfg.get("enabled", False))


def _to_tool_mode(config: Dict[str, Any]) -> str:
    tool_cfg = config.get("tool", {}) if isinstance(config, dict) else {}
    mode = tool_cfg.get("mode", "auto")
    return mode if mode in {"auto", "manual"} else "auto"


def _to_available_tools(config: Dict[str, Any]) -> List[str]:
    # Section 2 teaching scope is fixed to two tools only.
    return TOOL_TARGETS.copy()


def _is_confirmation_message(text: str) -> Optional[bool]:
    normalized = text.strip().lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    return None


def _rule_route(user_message: str) -> RouteDecision:
    text = (user_message or "").lower()

    if any(k in text for k in ["建立任務", "新增任務", "待辦", "代辦", "提醒我", "create task"]):
        return RouteDecision(action_type="tool", target="create_task", reason="規則命中：任務建立關鍵字")
    if any(k in text for k in ["查網路", "搜尋網路", "上網查", "search web", "google", "tavily"]):
        return RouteDecision(action_type="tool", target="search_web", reason="規則命中：網路搜尋關鍵字")

    return RouteDecision(action_type="llm", target="none", reason="未命中規則，改走一般 LLM 回答")


def _looks_like_task_intent(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(
        k in text
        for k in [
            "建立任務",
            "新增任務",
            "加一個任務",
            "task panel",
            "待辦",
            "代辦",
            "todo",
            "create task",
        ]
    )


def _looks_like_web_search_intent(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(
        k in text
        for k in [
            "搜尋",
            "查網路",
            "上網查",
            "search",
            "search web",
            "google",
            "tavily",
        ]
    )


def _build_router_prompt() -> str:
    return (
        "You are a strict router for a teaching agent system. Output JSON only.\n"
        "Fields: action_type, target, reason.\n"
        "action_type must be one of: tool, workflow, llm.\n"
        f"If action_type=tool, target must be one of: {', '.join(TOOL_TARGETS)}.\n"
        f"If action_type=workflow, target must be one of: {', '.join(WORKFLOW_TARGETS)}.\n"
        "If action_type=llm, target must be 'none'.\n"
        "Do not put target name into action_type."
    )


def _coerce_decision(payload: Dict[str, Any]) -> RouteDecision:
    action_type = str(payload.get("action_type", "")).strip().lower()
    target = str(payload.get("target", "")).strip().lower()
    reason = str(payload.get("reason", "")).strip() or "router decision"

    if action_type in {"tool", "workflow", "llm"}:
        if action_type == "llm":
            return RouteDecision(action_type="llm", target="none", reason=reason)
        if action_type == "tool" and target in TOOL_TARGETS:
            return RouteDecision(action_type="tool", target=target, reason=reason)
        if action_type == "workflow" and target in WORKFLOW_TARGETS:
            return RouteDecision(action_type="workflow", target=target, reason=reason)

    if action_type in TOOL_TARGETS:
        return RouteDecision(action_type="tool", target=action_type, reason=f"{reason} (auto-corrected)")
    if action_type in WORKFLOW_TARGETS:
        return RouteDecision(action_type="workflow", target=action_type, reason=f"{reason} (auto-corrected)")
    if target in TOOL_TARGETS:
        return RouteDecision(action_type="tool", target=target, reason=f"{reason} (auto-inferred)")
    if target in WORKFLOW_TARGETS:
        return RouteDecision(action_type="workflow", target=target, reason=f"{reason} (auto-inferred)")

    return RouteDecision(action_type="llm", target="none", reason="invalid payload, fallback to llm")


def _route_with_llm(client: OpenAI, model: str, structured_mode: str, user_message: str) -> Tuple[RouteDecision, str]:
    if structured_mode == "prompt_only":
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
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("router output is not object")
            return _coerce_decision(payload), raw
        except Exception as exc:  # noqa: BLE001
            # Fallback to strict JSON mode before giving up.
            retry = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _build_router_prompt() + " Return strict JSON object only."},
                    {"role": "user", "content": user_message},
                ],
            )
            retry_raw = retry.choices[0].message.content or ""
            try:
                payload = json.loads(retry_raw)
                if not isinstance(payload, dict):
                    raise ValueError("router output is not object")
                decision = _coerce_decision(payload)
                if decision.action_type == "llm":
                    decision = RouteDecision(
                        action_type="llm",
                        target="none",
                        reason=f"prompt_only parse failed -> pydantic fallback: {decision.reason}",
                    )
                return decision, retry_raw
            except Exception:
                return RouteDecision(action_type="llm", target="none", reason=f"prompt_only parse failed: {exc}"), raw

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
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("router output is not object")
        return _coerce_decision(payload), raw
    except Exception:
        retry = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _build_router_prompt() + " Return strict JSON object only."},
                {"role": "user", "content": user_message},
            ],
        )
        retry_raw = retry.choices[0].message.content or ""
        try:
            payload = json.loads(retry_raw)
            if not isinstance(payload, dict):
                raise ValueError("router output is not object")
            return _coerce_decision(payload), retry_raw
        except Exception as exc:  # noqa: BLE001
            return RouteDecision(action_type="llm", target="none", reason=f"pydantic parse failed: {exc}"), retry_raw


def _llm_tool_intent_fallback(client: OpenAI, model: str, user_message: str) -> Optional[RouteDecision]:
    prompt = (
        "You are a strict intent classifier. Return JSON only with fields: "
        "use_tool(boolean), target(string), reason(string). "
        "Allowed targets: create_task, search_web, none. "
        "Rules: "
        "- If user asks to add/create a task or todo -> create_task. "
        "- If user asks to search web/internet/news -> search_web. "
        "- Otherwise target=none."
    )
    try:
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
        if not isinstance(payload, dict):
            return None
        target = str(payload.get("target", "none")).strip().lower()
        use_tool = bool(payload.get("use_tool", False))
        reason = str(payload.get("reason", "")).strip() or "llm fallback classifier"
        if use_tool and target in TOOL_TARGETS:
            return RouteDecision(action_type="tool", target=target, reason=reason)
        return None
    except Exception:
        return None


def _run_tool(target: str, user_message: str) -> Dict[str, Any]:
    fn = TOOL_REGISTRY.get(target)
    if not fn:
        return {"ok": False, "tool": target, "message": f"未知工具：{target}"}
    return fn(user_message=user_message)


def _summarize_search_results_with_llm(query: str, results: List[Dict[str, Any]], llm_cfg: Dict[str, Any]) -> str:
    if not results:
        return "目前沒有可摘要的搜尋結果。"

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return "未偵測到 OPENAI_API_KEY，改用原始搜尋結果顯示。"

    model = llm_cfg.get("model", "gpt-4o") if isinstance(llm_cfg, dict) else "gpt-4o"
    snippets = []
    for idx, item in enumerate(results[:3], start=1):
        snippets.append(
            f"[{idx}] title: {item.get('title', '')}\n"
            f"url: {item.get('url', '')}\n"
            f"content: {item.get('content', '')}"
        )

    prompt = (
        "你是研究助理。請根據以下搜尋結果，使用繁體中文輸出重點摘要。\n"
        "要求：\n"
        "1) 先給 3-5 點重點（簡潔）\n"
        "2) 再給一段 2-3 句結論\n"
        "3) 不要編造結果外資訊\n"
        "4) 不要自行輸出連結清單（連結由系統附上）\n\n"
        f"查詢：{query}\n\n"
        "搜尋結果：\n"
        + "\n\n".join(snippets)
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "你是嚴謹、簡潔的繁體中文研究助理。"},
                {"role": "user", "content": prompt},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            cleaned_lines: List[str] = []
            for line in text.splitlines():
                low = line.strip().lower()
                if "reference" in low:
                    continue
                if "http://" in low or "https://" in low:
                    continue
                cleaned_lines.append(line)
            text = "\n".join(cleaned_lines).strip()
            text = re.sub(r"\n{3,}", "\n\n", text)
        return text or "搜尋結果摘要產生失敗，請直接查看下方參考連結。"
    except Exception:
        return "摘要模型暫時不可用，請直接查看下方參考連結。"


def _format_tool_reply(tool_result: Dict[str, Any], llm_cfg: Optional[Dict[str, Any]] = None) -> str:
    tool = tool_result.get("tool", "unknown")
    message = tool_result.get("message", "工具執行完成。")

    if tool == "create_task":
        task = tool_result.get("task", {})
        return (
            f"[Tool Executed] create_task\n"
            f"{message}\n"
            f"Task ID: {task.get('id', 'n/a')}"
        )

    if tool == "search_web":
        query = tool_result.get("query", "")
        results = tool_result.get("results", [])
        if not results:
            return f"[Tool Executed] search_web\n{message}"
        summary = _summarize_search_results_with_llm(query=query, results=results, llm_cfg=llm_cfg or {})
        refs = []
        for idx, item in enumerate(results[:3], start=1):
            title = item.get("title", "(no title)")
            url = item.get("url", "")
            if url:
                refs.append(f"{idx}. [{title}]({url})")
            else:
                refs.append(f"{idx}. {title}")
        return (
            "### [Tool Executed] search_web\n\n"
            f"- **查詢**：{query}\n"
            f"- **結果數量**：{len(results)}\n"
            f"- **狀態**：{message}\n\n"
            "#### 摘要\n\n"
            f"{summary}\n\n"
            "#### References\n\n"
            + "\n".join(refs)
        )

    return f"[Tool Executed] {tool}\n{message}"


def handle_section2_chat(
    user_message: str,
    config: Dict[str, Any],
    history: List[Dict[str, Any]],
    image_data_url: Optional[str] = None,
    router_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    llm_cfg = config.get("llm", {}) if isinstance(config, dict) else {}
    model = llm_cfg.get("model", "gpt-4o")

    tool_enabled = _to_tool_enabled(config)
    tool_mode = _to_tool_mode(config)
    available_tools = _to_available_tools(config)

    if router_context and router_context.get("action_type") in {"tool", "workflow"}:
        confirm = _is_confirmation_message(user_message)
        if confirm is True:
            action_type = router_context.get("action_type")
            target = router_context.get("target", "none")

            if action_type == "tool":
                source_message = str(router_context.get("user_message") or user_message)
                result = _run_tool(target=target, user_message=source_message)
                reply = _format_tool_reply(result, llm_cfg=llm_cfg)
                return {
                    "reply": reply,
                    "router": {
                        "action_type": "tool",
                        "target": target,
                        "reason": router_context.get("reason", ""),
                        "mode": router_context.get("mode", tool_mode),
                    },
                    "pending_route": None,
                }

            return {
                "reply": f"你選擇 Yes。Workflow `{target}` 將於 Section 3 實作。",
                "router": {
                    "action_type": "workflow",
                    "target": target,
                    "reason": router_context.get("reason", ""),
                    "mode": router_context.get("mode", "pydantic"),
                },
                "pending_route": None,
            }

        if confirm is False:
            return {
                "reply": "你選擇不執行此步驟，已取消本次動作。",
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "user rejected action, cancelled",
                    "mode": router_context.get("mode", "auto"),
                },
                "pending_route": None,
            }

        return {
            "reply": "請使用聊天室中的 Yes 或 No 按鈕確認是否執行。",
            "router": {
                "action_type": router_context.get("action_type", "llm"),
                "target": router_context.get("target", "none"),
                "reason": router_context.get("reason", ""),
                "mode": router_context.get("mode", tool_mode),
            },
            "pending_route": router_context,
        }

    llm_mode = _to_llm_mode(config)
    if llm_mode == "rule":
        # In rule-based mode we intentionally allow fast keyword routing.
        if tool_enabled and _looks_like_task_intent(user_message):
            decision = RouteDecision(
                action_type="tool",
                target="create_task",
                reason="quick intent: user explicitly asked to create task",
            )
            raw_output = json.dumps(decision.model_dump(), ensure_ascii=False)
            route_mode = "shortcut"
        elif tool_enabled and _looks_like_web_search_intent(user_message):
            decision = RouteDecision(
                action_type="tool",
                target="search_web",
                reason="quick intent: user explicitly asked for web search",
            )
            raw_output = json.dumps(decision.model_dump(), ensure_ascii=False)
            route_mode = "shortcut"
        else:
            decision = _rule_route(user_message)
            raw_output = json.dumps(decision.model_dump(), ensure_ascii=False)
            route_mode = "rule"
    else:
        # In llm-based mode, always use LLM router (no shortcut/heuristic override).
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        structured_mode = _to_router_mode(config)
        decision, raw_output = _route_with_llm(
            client=client,
            model=model,
            structured_mode=structured_mode,
            user_message=user_message,
        )
        route_mode = structured_mode
        if tool_enabled and decision.action_type != "tool":
            llm_fallback_decision = _llm_tool_intent_fallback(
                client=client,
                model=model,
                user_message=user_message,
            )
            if llm_fallback_decision:
                decision = llm_fallback_decision

    # Fail-safe override:
    # If LLM router parsing fails and falls back to llm, but intent is very clear,
    # we still route to tool to avoid UX regression in teaching demos.
    if (
        tool_enabled
        and decision.action_type == "llm"
        and "parse failed" in (decision.reason or "").lower()
    ):
        if _looks_like_task_intent(user_message):
            decision = RouteDecision(
                action_type="tool",
                target="create_task",
                reason="router parse failed; fallback override to create_task",
            )
        elif _looks_like_web_search_intent(user_message):
            decision = RouteDecision(
                action_type="tool",
                target="search_web",
                reason="router parse failed; fallback override to search_web",
            )

    # Section 2 UX guardrail:
    # if user clearly asks to create a task, do not drift to workflow routing.
    if llm_mode == "rule" and _looks_like_task_intent(user_message) and decision.action_type != "tool":
        decision = RouteDecision(
            action_type="tool",
            target="create_task",
            reason="task intent override: user explicitly asked to create task",
        )

    header = f"[Router → {decision.action_type.upper()}]" if decision.action_type != "llm" else "[Router → LLM]"
    target_part = f" {decision.target}" if decision.action_type != "llm" else ""
    reason_line = f"Reason: {decision.reason}"

    if decision.action_type == "tool":
        if not tool_enabled:
            fallback = run_chat(
                user_message=user_message,
                llm_config=llm_cfg,
                history=history,
                image_data_url=image_data_url,
            )
            return {
                "reply": (
                    f"{header}{target_part}\n{reason_line}\n\n"
                    "Tool Calling 尚未啟用（Enable Tool Calling = off），改由 LLM 回答：\n\n"
                    f"{fallback.reply}"
                ),
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "tool disabled, fallback to llm",
                    "mode": route_mode,
                    "raw": raw_output,
                },
                "pending_route": None,
            }

        if decision.target not in available_tools:
            fallback = run_chat(
                user_message=user_message,
                llm_config=llm_cfg,
                history=history,
                image_data_url=image_data_url,
            )
            return {
                "reply": (
                    f"{header}{target_part}\n{reason_line}\n\n"
                    f"工具 `{decision.target}` 不在可用清單中，改由 LLM 回答：\n\n{fallback.reply}"
                ),
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "tool not allowed, fallback to llm",
                    "mode": route_mode,
                    "raw": raw_output,
                },
                "pending_route": None,
            }

        if tool_mode == "manual":
            reply = (
                f"{header}{target_part}\n"
                f"{reason_line}\n\n"
                "偵測到可執行工具，是否執行？（Yes / No）"
            )
            return {
                "reply": reply,
                "router": {
                    "action_type": "tool",
                    "target": decision.target,
                    "reason": decision.reason,
                    "mode": "manual",
                    "raw": raw_output,
                },
                "pending_route": {
                    "action_type": "tool",
                    "target": decision.target,
                    "reason": decision.reason,
                    "mode": "manual",
                    "user_message": user_message,
                },
            }

        result = _run_tool(target=decision.target, user_message=user_message)
        reply = (
            f"{header}{target_part}\n"
            f"{reason_line}\n\n"
            f"{_format_tool_reply(result, llm_cfg=llm_cfg)}"
        )
        return {
            "reply": reply,
            "router": {
                "action_type": "tool",
                "target": decision.target,
                "reason": decision.reason,
                "mode": "auto",
                "raw": raw_output,
            },
            "pending_route": None,
        }

    if decision.action_type == "workflow":
        reply = (
            f"{header}{target_part}\n"
            f"{reason_line}\n\n"
            "是否要執行這個 workflow？（Yes / No）"
        )
        return {
            "reply": reply,
            "router": {
                "action_type": "workflow",
                "target": decision.target,
                "reason": decision.reason,
                "mode": route_mode,
                "raw": raw_output,
            },
            "pending_route": {
                "action_type": "workflow",
                "target": decision.target,
                "reason": decision.reason,
                "mode": route_mode,
            },
        }

    fallback = run_chat(
        user_message=user_message,
        llm_config=llm_cfg,
        history=history,
        image_data_url=image_data_url,
    )
    return {
        "reply": f"{header}\n{reason_line}\n\n{fallback.reply}",
        "router": {
            "action_type": "llm",
            "target": "none",
            "reason": decision.reason,
            "mode": route_mode,
            "raw": raw_output,
        },
        "pending_route": None,
    }

