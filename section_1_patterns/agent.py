import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from section_0_basic_llm.llm import run_chat
from section_1_patterns.router_llm import route_intent, route_with_rules


def _to_llm_mode(config: Dict[str, Any]) -> str:
    workflow = config.get("workflow", {}) if isinstance(config, dict) else {}
    mode = workflow.get("mode", "llm")
    return mode if mode in {"llm", "rule"} else "llm"


def _to_router_mode(config: Dict[str, Any]) -> str:
    workflow = config.get("workflow", {}) if isinstance(config, dict) else {}
    mode = workflow.get("router_mode", "pydantic")
    return mode if mode in {"prompt_only", "pydantic"} else "pydantic"


def _to_skill_enabled(config: Dict[str, Any]) -> bool:
    skill_cfg = config.get("skills", {}) if isinstance(config, dict) else {}
    return bool(skill_cfg.get("enabled", False))


def _is_confirmation_message(text: str) -> Optional[bool]:
    normalized = text.strip().lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    return None


def _looks_like_code_execution_intent(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if "python" in normalized:
        return True
    action_words = ["執行", "跑", "run", "execute"]
    code_words = ["python", "程式碼", "代碼", "code"]
    return any(w in normalized for w in action_words) and any(w in normalized for w in code_words)


def handle_section1_chat(
    user_message: str,
    config: Dict[str, Any],
    history: List[Dict[str, Any]],
    image_data_url: Optional[str] = None,
    router_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    llm_cfg = config.get("llm", {}) if isinstance(config, dict) else {}
    model = llm_cfg.get("model", "gpt-4o")
    skill_enabled = _to_skill_enabled(config)

    # If user is replying to router confirmation, handle first.
    if router_context and router_context.get("action_type") in {"tool", "workflow", "skill"}:
        confirm = _is_confirmation_message(user_message)
        if confirm is True:
            action_type = router_context["action_type"]
            target = router_context["target"]
            if action_type == "tool":
                return {
                    "reply": f"你選擇 Yes。Tool `{target}` 將於 Section 2 實作。",
                    "router": {
                        "action_type": action_type,
                        "target": target,
                        "reason": router_context.get("reason", ""),
                        "mode": router_context.get("mode", "pydantic"),
                    },
                    "pending_route": None,
                }
            if action_type == "skill":
                if target == "invoice_ocr" and not skill_enabled:
                    return {
                        "reply": (
                            "你選擇 Yes。Skill `invoice_ocr` 將於 Section 3 正式使用。\n"
                            "目前尚未開啟 `Enable Skills`，請先到右側 Control Panel 開啟後再測試，"
                            "並記得同時上傳發票圖片。"
                        ),
                        "router": {
                            "action_type": action_type,
                            "target": target,
                            "reason": router_context.get("reason", ""),
                            "mode": router_context.get("mode", "pydantic"),
                        },
                        "pending_route": None,
                    }
                return {
                    "reply": (
                        "你選擇 Yes。Skill `invoice_ocr` 將於 Section 3 正式使用。\n"
                        "請在同一則訊息中描述要辨識發票，並附上發票圖片。"
                    ),
                    "router": {
                        "action_type": action_type,
                        "target": target,
                        "reason": router_context.get("reason", ""),
                        "mode": router_context.get("mode", "pydantic"),
                    },
                    "pending_route": None,
                }
            if target == "code_execution":
                return {
                    "reply": f"你選擇 Yes。Pattern `{target}` 將於 Section 4 實作。",
                    "router": {
                        "action_type": action_type,
                        "target": target,
                        "reason": router_context.get("reason", ""),
                        "mode": router_context.get("mode", "pydantic"),
                    },
                    "pending_route": None,
                }
            return {
                "reply": f"你選擇 Yes。Workflow `{target}` 將於 Section 3 實作。",
                "router": {
                    "action_type": action_type,
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
                    "mode": router_context.get("mode", "pydantic"),
                },
                "pending_route": None,
            }
        return {
            "reply": "請使用聊天室中的 Yes 或 No 按鈕確認是否執行。",
            "router": {
                "action_type": router_context.get("action_type", "llm"),
                "target": router_context.get("target", "none"),
                "reason": router_context.get("reason", ""),
                "mode": router_context.get("mode", "pydantic"),
            },
            "pending_route": router_context,
        }

    llm_mode = _to_llm_mode(config)
    if llm_mode == "rule":
        decision = route_with_rules(user_message)
        raw_output = json.dumps(decision.model_dump(), ensure_ascii=False)
        mode = "rule"
    else:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        mode = _to_router_mode(config)
        decision, raw_output = route_intent(
            client=client,
            model=model,
            mode=mode,
            user_message=user_message,
        )

    # Safety override for both rule-based and llm-based routing:
    # if user clearly asks to execute code, force route to code_execution workflow.
    if _looks_like_code_execution_intent(user_message) and not (
        decision.action_type == "workflow" and decision.target == "code_execution"
    ):
        decision = decision.model_copy(
            update={
                "action_type": "workflow",
                "target": "code_execution",
                "reason": "code execution intent override: user asked to run code",
            }
        )

    if decision.action_type == "workflow" and decision.target == "code_execution":
        header = "[Router → CODE]"
    elif decision.action_type == "skill":
        header = "[Router → SKILL]"
    else:
        header = (
            f"[Router → {decision.action_type.upper()}]"
            if decision.action_type != "llm"
            else "[Router → LLM]"
        )
    target_part = f" {decision.target}" if decision.action_type != "llm" else ""

    reason_line = f"Reason: {decision.reason}"

    if decision.action_type in {"tool", "workflow", "skill"}:
        reply = (
            f"{header}{target_part}\n"
            f"{reason_line}\n\n"
            "是否要執行這個動作？（Yes / No）"
        )
        return {
            "reply": reply,
            "router": {
                "action_type": decision.action_type,
                "target": decision.target,
                "reason": decision.reason,
                "mode": mode,
                "raw": raw_output,
            },
            "pending_route": {
                "action_type": decision.action_type,
                "target": decision.target,
                "reason": decision.reason,
                "mode": mode,
            },
        }

    fallback = run_chat(
        user_message=user_message,
        llm_config=llm_cfg,
        history=history,
        image_data_url=image_data_url,
    )
    reply = f"{header}\n{reason_line}\n\n{fallback.reply}"

    return {
        "reply": reply,
        "router": {
            "action_type": "llm",
            "target": "none",
            "reason": decision.reason,
            "mode": mode,
            "raw": raw_output,
        },
        "pending_route": None,
    }
