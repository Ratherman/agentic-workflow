import re
from typing import Any, Dict, List, Optional

from section_5_security.agent import handle_section5_chat
from section_6_production_ready.observability.costing import build_usage_metrics, load_pricing_table

_MULTI_CTX_KEY = "_multi_ctx"


def _to_multi_demand_enabled(config: Dict[str, Any]) -> bool:
    prod_cfg = config.get("production", {}) if isinstance(config, dict) else {}
    return bool(prod_cfg.get("multi_demand", False))


def _to_cost_management_enabled(config: Dict[str, Any]) -> bool:
    prod_cfg = config.get("production", {}) if isinstance(config, dict) else {}
    return bool(prod_cfg.get("cost_management", False))


def _detect_multi_demands(user_message: str) -> List[str]:
    text = (user_message or "").strip()
    if not text:
        return []

    numbered = [
        m.group(1).strip()
        for m in re.finditer(r"(?:^|\n)\s*\d+[\.)、]\s*(.+)", text)
        if m.group(1).strip()
    ]
    if len(numbered) >= 2:
        return numbered

    # Split by common multi-demand connectors.
    parts = re.split(r"(?:；|;|\n|並且|然後|另外|同時)", text)
    parts = [p.strip(" ，,。") for p in parts if p.strip(" ，,。")]
    return parts if len(parts) >= 2 else [text]


def _attach_usage_if_enabled(
    *,
    enabled: bool,
    model: str,
    user_text: str,
    assistant_text: str,
    image_data_url: str,
    uploaded_file: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not enabled:
        return {}
    pricing = load_pricing_table()
    usage = build_usage_metrics(
        model=model,
        user_text=user_text,
        assistant_text=assistant_text,
        image_data_url=image_data_url,
        uploaded_file=uploaded_file,
        pricing=pricing,
    )
    return {"usage": usage}


def handle_section6_chat(
    user_message: str,
    config: Dict[str, Any],
    history: List[Dict[str, Any]],
    image_data_url: Optional[str] = None,
    uploaded_file: Optional[Dict[str, Any]] = None,
    router_context: Optional[Dict[str, Any]] = None,
    export_dir: Optional[str] = None,
) -> Dict[str, Any]:
    llm_cfg = config.get("llm", {}) if isinstance(config, dict) else {}
    model = str(llm_cfg.get("model", "gpt-4o"))

    multi_enabled = _to_multi_demand_enabled(config)
    cost_enabled = _to_cost_management_enabled(config)

    # If currently in a pending stage, continue it first.
    if router_context:
        multi_ctx = router_context.get(_MULTI_CTX_KEY) if isinstance(router_context, dict) else None
        inner_context = dict(router_context) if isinstance(router_context, dict) else {}
        if _MULTI_CTX_KEY in inner_context:
            inner_context.pop(_MULTI_CTX_KEY, None)

        result = handle_section5_chat(
            user_message=user_message,
            config=config,
            history=history,
            image_data_url=image_data_url,
            uploaded_file=uploaded_file,
            router_context=inner_context or None,
            export_dir=export_dir,
        )

        # Continue remaining multi-demands after current pending step is resolved.
        if isinstance(multi_ctx, dict) and not result.get("pending_route"):
            remaining_demands = [str(x).strip() for x in (multi_ctx.get("remaining_demands") or []) if str(x).strip()]
            done_bubbles = [str(x) for x in (multi_ctx.get("done_bubbles") or []) if str(x).strip()]
            current_index = int(multi_ctx.get("current_index") or 1)
            done_bubbles.append(
                f"[子任務 {current_index} 已完成]\n"
                f"{str(result.get('reply', '')).strip() or '(no reply)'}"
            )

            pending_route = None
            aggregate_output_text = "\n".join(done_bubbles)
            idx = current_index + 1
            final_bubbles = list(done_bubbles)

            for demand in remaining_demands:
                step_result = handle_section5_chat(
                    user_message=demand,
                    config=config,
                    history=history,
                    image_data_url=None,
                    uploaded_file=None,
                    router_context=None,
                    export_dir=export_dir,
                )
                step_reply = str(step_result.get("reply", "")).strip() or "(no reply)"
                if step_result.get("pending_route"):
                    pending_bubble = f"[子任務 {idx} 待確認]\n{step_reply}"
                    final_bubbles = done_bubbles + [pending_bubble]
                    pending_inner = dict(step_result.get("pending_route") or {})
                    pending_inner[_MULTI_CTX_KEY] = {
                        "remaining_demands": remaining_demands[1:],
                        "done_bubbles": done_bubbles,
                        "current_index": idx,
                    }
                    pending_route = pending_inner
                    aggregate_output_text += "\n" + pending_bubble
                    break

                done_bubble = f"[子任務 {idx} 已完成]\n{step_reply}"
                done_bubbles.append(done_bubble)
                final_bubbles = list(done_bubbles)
                aggregate_output_text += "\n" + done_bubble

                remaining_demands = remaining_demands[1:]
                idx += 1

            result = {
                "reply": "[Multi-Demand] 已接續處理剩餘需求：\n\n" + "\n\n".join(final_bubbles),
                "multi_replies": final_bubbles,
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "multi-demand continued",
                    "mode": "production",
                },
                "pending_route": pending_route,
            }

        result.update(
            _attach_usage_if_enabled(
                enabled=cost_enabled,
                model=model,
                user_text=user_message,
                assistant_text=str(result.get("reply", "")),
                image_data_url=image_data_url or "",
                uploaded_file=uploaded_file,
            )
        )
        return result

    demands = _detect_multi_demands(user_message)

    if not multi_enabled or len(demands) <= 1:
        result = handle_section5_chat(
            user_message=user_message,
            config=config,
            history=history,
            image_data_url=image_data_url,
            uploaded_file=uploaded_file,
            router_context=router_context,
            export_dir=export_dir,
        )
        result.update(
            _attach_usage_if_enabled(
                enabled=cost_enabled,
                model=model,
                user_text=user_message,
                assistant_text=str(result.get("reply", "")),
                image_data_url=image_data_url or "",
                uploaded_file=uploaded_file,
            )
        )
        return result

    merged_replies: List[str] = []
    pending_route = None
    aggregate_input_text = user_message
    aggregate_output_text = ""
    bubbles: List[str] = []

    for idx, demand in enumerate(demands, start=1):
        step_result = handle_section5_chat(
            user_message=demand,
            config=config,
            history=history,
            image_data_url=image_data_url if idx == 1 else None,
            uploaded_file=uploaded_file if idx == 1 else None,
            router_context=None,
            export_dir=export_dir,
        )
        step_reply = str(step_result.get("reply", "")).strip() or "(no reply)"
        aggregate_output_text += "\n" + step_reply

        # If any step needs confirmation/continuation, stop there.
        if step_result.get("pending_route"):
            pending_bubble = f"[子任務 {idx} 待確認]\n{step_reply}"
            bubbles.append(pending_bubble)
            pending_inner = dict(step_result.get("pending_route") or {})
            pending_inner[_MULTI_CTX_KEY] = {
                "remaining_demands": demands[idx:],
                "done_bubbles": [b for b in bubbles if "待確認" not in b],
                "current_index": idx,
            }
            pending_route = pending_inner
            break
        bubbles.append(f"[子任務 {idx} 已完成]\n{step_reply}")

    final_reply = "[Multi-Demand] 已解析多個需求並依序處理：\n\n" + "\n\n".join(bubbles)
    result: Dict[str, Any] = {
        "reply": final_reply,
        "multi_replies": bubbles,
        "router": {
            "action_type": "llm",
            "target": "none",
            "reason": "multi-demand orchestrated",
            "mode": "production",
        },
        "pending_route": pending_route,
    }

    result.update(
        _attach_usage_if_enabled(
            enabled=cost_enabled,
            model=model,
            user_text=aggregate_input_text,
            assistant_text=aggregate_output_text,
            image_data_url=image_data_url or "",
            uploaded_file=uploaded_file,
        )
    )
    return result
