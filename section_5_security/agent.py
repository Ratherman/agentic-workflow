from typing import Any, Dict, List, Optional

from section_4_code_execution.agent import handle_section4_chat
from section_5_security.security.guardrail import run_nemo_guardrail_check
from section_5_security.security.moderation import check_openai_moderation


def _to_moderation_enabled(config: Dict[str, Any]) -> bool:
    sec_cfg = config.get("security", {}) if isinstance(config, dict) else {}
    return bool(sec_cfg.get("moderation", False))


def _to_guardrails_enabled(config: Dict[str, Any]) -> bool:
    sec_cfg = config.get("security", {}) if isinstance(config, dict) else {}
    return bool(sec_cfg.get("guardrails", False))


def _build_moderation_block_reply(direction: str, categories: List[str], includes_image: bool = False) -> str:
    cats = ", ".join(categories) if categories else "policy"
    media = "text+image" if includes_image else "text"
    if direction == "input":
        return (
            "[Security Blocked] OpenAI Moderation\n"
            f"- stage: input\n"
            f"- media: {media}\n"
            f"- categories: {cats}\n\n"
            "此請求已在執行前被安全策略攔截。"
        )
    return (
        "[Security Blocked] OpenAI Moderation\n"
        f"- stage: output\n"
        "- media: text\n"
        f"- categories: {cats}\n\n"
        "模型輸出觸發安全政策，已改為安全回覆。"
    )


def handle_section5_chat(
    user_message: str,
    config: Dict[str, Any],
    history: List[Dict[str, Any]],
    image_data_url: Optional[str] = None,
    uploaded_file: Optional[Dict[str, Any]] = None,
    router_context: Optional[Dict[str, Any]] = None,
    export_dir: Optional[str] = None,
) -> Dict[str, Any]:
    moderation_enabled = _to_moderation_enabled(config)
    guardrails_enabled = _to_guardrails_enabled(config)

    # 1) Input moderation (text + input image)
    input_mod = check_openai_moderation(
        enabled=moderation_enabled,
        text=user_message,
        image_data_url=image_data_url or "",
    )
    if input_mod.enabled and input_mod.available and input_mod.flagged:
        return {
            "reply": _build_moderation_block_reply(
                "input",
                input_mod.categories,
                includes_image=bool(image_data_url),
            ),
            "router": {
                "action_type": "llm",
                "target": "none",
                "reason": "blocked by moderation(input)",
                "mode": "security",
            },
            "pending_route": None,
        }

    # 2) Guardrails
    guard = run_nemo_guardrail_check(user_message, guardrails_enabled)
    if guard.enabled and guard.blocked:
        rules = ", ".join(guard.matched_rules) if guard.matched_rules else "policy"
        return {
            "reply": (
                "[Security Blocked] NeMo Guardrails\n"
                f"- provider: {guard.provider}\n"
                f"- reason: {guard.reason}\n"
                f"- rules: {rules}\n\n"
                f"{guard.safe_reply}"
            ),
            "router": {
                "action_type": "llm",
                "target": "none",
                "reason": "blocked by guardrails",
                "mode": "security",
            },
            "pending_route": None,
        }

    # 3) Normal section 4 flow
    result = handle_section4_chat(
        user_message=user_message,
        config=config,
        history=history,
        image_data_url=image_data_url,
        uploaded_file=uploaded_file,
        router_context=router_context,
        export_dir=export_dir,
    )

    # 4) Output moderation (text)
    assistant_reply = str(result.get("reply", ""))
    output_mod = check_openai_moderation(
        enabled=moderation_enabled,
        text=assistant_reply,
        image_data_url="",
    )
    if output_mod.enabled and output_mod.available and output_mod.flagged:
        return {
            "reply": _build_moderation_block_reply("output", output_mod.categories),
            "router": {
                "action_type": "llm",
                "target": "none",
                "reason": "blocked by moderation(output)",
                "mode": "security",
            },
            "pending_route": None,
        }

    return result
