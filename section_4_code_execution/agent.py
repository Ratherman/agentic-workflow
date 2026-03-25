import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from section_3_workflow_integration.agent import handle_section3_chat
from section_4_code_execution.executor.sandbox import execute_python_code


def _to_code_enabled(config: Dict[str, Any]) -> bool:
    code_cfg = config.get("code_execution", {}) if isinstance(config, dict) else {}
    return bool(code_cfg.get("enabled", False))


def _to_auto_run(config: Dict[str, Any]) -> bool:
    code_cfg = config.get("code_execution", {}) if isinstance(config, dict) else {}
    return bool(code_cfg.get("auto_run", False))


def _to_libraries(config: Dict[str, Any]) -> List[str]:
    code_cfg = config.get("code_execution", {}) if isinstance(config, dict) else {}
    libs = code_cfg.get("libraries", [])
    if not isinstance(libs, list):
        return []
    return [str(item).strip().lower() for item in libs if str(item).strip()]


def _is_yes_no(text: str) -> Optional[bool]:
    t = (text or "").strip().lower()
    if t == "yes":
        return True
    if t == "no":
        return False
    return None


def _looks_like_code_execution_intent(text: str) -> bool:
    lowered = (text or "").lower()
    keywords = [
        "python",
        "code",
        "matplotlib",
        "numpy",
        "pandas",
        "plot",
        "chart",
        "pie",
        "line",
        "excel",
        "xlsx",
        "csv",
        "程式碼",
        "代碼",
        "執行",
        "計算",
        "繪圖",
        "繪製",
        "圓餅圖",
        "折線圖",
        "長條圖",
        "圖表",
        "缺值",
        "中位數",
        "補值",
    ]
    return any(k in lowered for k in keywords)


def _normalize_uploaded_file(uploaded_file: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not isinstance(uploaded_file, dict):
        return None
    path = str(uploaded_file.get("path", "")).strip()
    name = str(uploaded_file.get("name", "")).strip() or str(uploaded_file.get("stored_name", "")).strip()
    relative_path = str(uploaded_file.get("relative_path", "")).strip()
    if not path and not relative_path:
        return None
    return {"path": path, "name": name, "relative_path": relative_path}


def _has_export_intent(user_message: str) -> bool:
    text = (user_message or "").lower()
    keywords = ["export", "download", "下載", "輸出", "匯出", "xlsx", "csv", "讓我可以下載", "可下載"]
    return any(k in text for k in keywords)


def _has_data_cleaning_intent(user_message: str) -> bool:
    text = (user_message or "").lower()
    keywords = [
        "missing",
        "null",
        "na",
        "median",
        "quantity",
        "unit_price",
        "缺值",
        "遺漏值",
        "中位數",
        "補",
        "補值",
    ]
    return any(k in text for k in keywords)


def _should_force_direct_plan(user_message: str, uploaded_file: Optional[Dict[str, str]]) -> bool:
    if not uploaded_file:
        return False
    # User already gave enough info for typical pandas cleaning + export flow.
    return _has_export_intent(user_message) and _has_data_cleaning_intent(user_message)


def _build_codegen_prompt(
    user_message: str,
    libraries: List[str],
    uploaded_file: Optional[Dict[str, str]],
    force_direct: bool,
) -> str:
    file_context = ""
    if uploaded_file:
        preferred_path = uploaded_file.get("path") or uploaded_file.get("relative_path")
        preferred_path = str(preferred_path or "").replace("\\", "/")
        file_context = (
            "Uploaded file is available.\n"
            f"- file_name: {uploaded_file.get('name', '')}\n"
            f"- file_path: {preferred_path}\n"
            "A runtime variable UPLOADED_FILE_PATH is also provided by executor.\n"
            "For data analysis request, read this file directly with pandas.\n"
            "If user asks to output cleaned data, assign the final dataframe to RESULT_DF.\n"
            "Set RESULT_FILENAME for exported file name (xlsx).\n"
            "Use forward slashes in any file path string.\n"
            "Do not generate backslash Windows path escapes like \\U or \\n in string literals.\n"
        )

    direct_rule = ""
    if force_direct:
        direct_rule = (
            "Direct-execution override:\n"
            "- User already provided enough info.\n"
            "- Do NOT ask clarification.\n"
            "- Set needs_clarification=false and generate executable code now.\n"
            "- If export format not explicitly constrained, default to xlsx and set RESULT_FILENAME='cleaned_output.xlsx'.\n"
        )

    return (
        "You are a Python code generation planner for an educational agent.\n"
        "Return JSON only with fields:\n"
        "- needs_clarification (boolean)\n"
        "- question (string)\n"
        "- code (string)\n"
        "- summary (string)\n\n"
        "Rules:\n"
        "1) If user intent can be executed safely, set needs_clarification=false and generate code.\n"
        "2) If chart/data requirements are truly ambiguous, set needs_clarification=true and ask one concise Traditional Chinese question.\n"
        "3) If needs_clarification=true, keep code as empty string.\n"
        "4) If generating code: code must be raw Python (no markdown), executable by exec().\n"
        "5) Always set RESULT_TEXT in code when needs_clarification=false.\n"
        "6) If chart is requested, use matplotlib and do not call plt.show().\n"
        "7) Do not use file write/network/system commands except DataFrame export via RESULT_DF/RESULT_FILENAME.\n"
        "8) Solve the exact user request; do not replace with generic template text.\n"
        "9) For pandas missing-value imputation, always cast target numeric columns with pd.to_numeric(errors='coerce') before median().\n"
        "10) Prefer `df[col] = df[col].fillna(...)` instead of inplace=True.\n"
        "11) If file upload exists, use UPLOADED_FILE_PATH first; avoid hardcoded local paths.\n"
        f"Allowed libs: {', '.join(libraries) if libraries else 'none'}.\n"
        f"{file_context}"
        f"{direct_rule}"
        f"User request: {user_message}"
    )


def _generate_plan_with_llm(
    user_message: str,
    llm_cfg: Dict[str, Any],
    libraries: List[str],
    uploaded_file: Optional[Dict[str, str]],
    force_direct: bool = False,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "needs_clarification": True,
            "question": "尚未設定 OPENAI_API_KEY，請先在 .env 設定後再試。",
            "code": "",
            "summary": "missing api key",
        }

    model = llm_cfg.get("model", "gpt-4o") if isinstance(llm_cfg, dict) else "gpt-4o"
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": _build_codegen_prompt(
                    user_message=user_message,
                    libraries=libraries,
                    uploaded_file=uploaded_file,
                    force_direct=force_direct,
                ),
            },
            {"role": "user", "content": user_message},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    return {
        "needs_clarification": bool(payload.get("needs_clarification", False)),
        "question": str(payload.get("question", "")).strip(),
        "code": str(payload.get("code", "")).strip(),
        "summary": str(payload.get("summary", "")).strip() or "Code generated.",
    }


def _plan_with_optional_retry(
    user_message: str,
    llm_cfg: Dict[str, Any],
    libraries: List[str],
    uploaded_file: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    force_direct = _should_force_direct_plan(user_message, uploaded_file)
    plan = _generate_plan_with_llm(
        user_message=user_message,
        llm_cfg=llm_cfg,
        libraries=libraries,
        uploaded_file=uploaded_file,
        force_direct=False,
    )

    if force_direct and plan.get("needs_clarification"):
        retry_plan = _generate_plan_with_llm(
            user_message=user_message,
            llm_cfg=llm_cfg,
            libraries=libraries,
            uploaded_file=uploaded_file,
            force_direct=True,
        )
        if retry_plan.get("code"):
            return {
                **retry_plan,
                "needs_clarification": False,
            }
    return plan


def _format_execution_reply(code: str, summary: str, result: Any) -> str:
    if not result.ok:
        return (
            "[Code Execution]\n"
            f"Summary: {summary}\n\n"
            "```python\n"
            f"{code}\n"
            "```\n\n"
            f"Execution failed: {result.error}"
        )

    parts = [
        "[Code Execution]",
        f"Summary: {summary}",
        "",
        "```python",
        code,
        "```",
        "",
        f"Result: {result.result_text}",
    ]
    if result.image_data_url:
        parts.extend(["", f"![execution chart]({result.image_data_url})"])
    if result.export_relative_path:
        parts.extend(["", f"[下載匯出檔案]({result.export_relative_path})"])
    return "\n".join(parts)


def _sanitize_generated_code(code: str) -> str:
    text = (code or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _execute_generated_code(
    code: str,
    summary: str,
    libraries: List[str],
    export_dir: Optional[str],
    uploaded_file: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    code = _sanitize_generated_code(code)
    uploaded_file_path = ""
    if isinstance(uploaded_file, dict):
        uploaded_file_path = str(uploaded_file.get("path") or uploaded_file.get("relative_path") or "")
    result = execute_python_code(
        code=code,
        mode="safe",
        libraries=libraries,
        export_dir=export_dir,
        uploaded_file_path=uploaded_file_path,
    )
    return {
        "reply": _format_execution_reply(code, summary, result),
        "router": {
            "action_type": "code",
            "target": "code_execution",
            "reason": "code executed",
            "mode": "manual",
        },
        "pending_route": None,
    }


def _manual_confirm_reply(code: str, reason: str) -> str:
    return (
        "[Router -> CODE] code_execution\n"
        f"Reason: {reason}\n\n"
        "偵測到可執行程式碼，是否執行？（Yes / No）\n"
        "```python\n"
        f"{code}\n"
        "```"
    )


def handle_section4_chat(
    user_message: str,
    config: Dict[str, Any],
    history: List[Dict[str, Any]],
    image_data_url: Optional[str] = None,
    uploaded_file: Optional[Dict[str, Any]] = None,
    router_context: Optional[Dict[str, Any]] = None,
    export_dir: Optional[str] = None,
) -> Dict[str, Any]:
    llm_cfg = config.get("llm", {}) if isinstance(config, dict) else {}
    code_enabled = _to_code_enabled(config)
    auto_run = _to_auto_run(config)
    libraries = _to_libraries(config)
    normalized_file = _normalize_uploaded_file(uploaded_file)

    if router_context and router_context.get("stage") == "confirm_code_execute":
        confirm = _is_yes_no(user_message)
        if confirm is None:
            return {
                "reply": "目前正在等待執行確認，請直接點擊 Yes / No 按鈕。",
                "router": {
                    "action_type": "code",
                    "target": "code_execution",
                    "reason": "awaiting yes/no",
                    "mode": "manual",
                },
                "pending_route": router_context,
            }
        if confirm is False:
            return {
                "reply": "你選擇不執行此步驟。",
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "user rejected code execution",
                    "mode": "manual",
                },
                "pending_route": None,
            }
        code = _sanitize_generated_code(str(router_context.get("code", "")).strip())
        summary = str(router_context.get("summary", "Code generated.")).strip()
        pending_file = _normalize_uploaded_file(router_context.get("uploaded_file")) or normalized_file
        return _execute_generated_code(code, summary, libraries, export_dir, pending_file)

    if router_context and router_context.get("stage") == "collect_code_requirements":
        original = str(router_context.get("original_request", "")).strip()
        merged_request = f"{original}\n補充資訊：{user_message}"
        carry_file = _normalize_uploaded_file(router_context.get("uploaded_file")) or normalized_file
        plan = _plan_with_optional_retry(merged_request, llm_cfg, libraries, carry_file)
        if plan.get("needs_clarification"):
            return {
                "reply": (
                    "[Router -> CODE] code_execution\n"
                    "Reason: 執行前需要補充資訊。\n\n"
                    f"{plan.get('question') or '請補充資料欄位、目標圖表或輸出格式。'}"
                ),
                "router": {
                    "action_type": "code",
                    "target": "code_execution",
                    "reason": "collecting more requirements",
                    "mode": "manual",
                },
                "pending_route": {
                    "stage": "collect_code_requirements",
                    "original_request": merged_request,
                    "uploaded_file": carry_file,
                },
            }

        code = _sanitize_generated_code(str(plan.get("code", "")).strip())
        summary = str(plan.get("summary", "")).strip() or "Code generated."
        if not code:
            return {
                "reply": "目前無法產生可執行程式碼，請換個描述再試一次。",
                "router": {
                    "action_type": "llm",
                    "target": "none",
                    "reason": "empty code from planner",
                    "mode": "manual",
                },
                "pending_route": None,
            }

        if not auto_run:
            return {
                "reply": _manual_confirm_reply(code, "已完成需求理解。"),
                "router": {
                    "action_type": "code",
                    "target": "code_execution",
                    "reason": "code generated after clarification",
                    "mode": "manual",
                },
                "pending_route": {
                    "stage": "confirm_code_execute",
                    "action_type": "code",
                    "target": "code_execution",
                    "mode": "manual",
                    "code": code,
                    "summary": summary,
                    "uploaded_file": carry_file,
                },
            }
        return _execute_generated_code(code, summary, libraries, export_dir, carry_file)

    if not code_enabled:
        return handle_section3_chat(
            user_message=user_message,
            config=config,
            history=history,
            image_data_url=image_data_url,
            router_context=router_context,
        )

    if not _looks_like_code_execution_intent(user_message):
        return handle_section3_chat(
            user_message=user_message,
            config=config,
            history=history,
            image_data_url=image_data_url,
            router_context=router_context,
        )

    plan = _plan_with_optional_retry(user_message, llm_cfg, libraries, normalized_file)
    if plan.get("needs_clarification"):
        return {
            "reply": (
                "[Router -> CODE] code_execution\n"
                "Reason: 執行前需要補充資訊。\n\n"
                f"{plan.get('question') or '請補充資料欄位、目標圖表或輸出格式。'}"
            ),
            "router": {
                "action_type": "code",
                "target": "code_execution",
                "reason": "collecting requirements",
                "mode": "manual",
            },
            "pending_route": {
                "stage": "collect_code_requirements",
                "original_request": user_message,
                "uploaded_file": normalized_file,
            },
        }

    code = _sanitize_generated_code(str(plan.get("code", "")).strip())
    summary = str(plan.get("summary", "")).strip() or "Code generated."
    if not code:
        return {
            "reply": "LLM 沒有回傳可執行程式碼，請換個描述再試一次。",
            "router": {
                "action_type": "llm",
                "target": "none",
                "reason": "empty code from planner",
                "mode": "manual",
            },
            "pending_route": None,
        }

    if not auto_run:
        return {
            "reply": _manual_confirm_reply(code, "code execution intent detected."),
            "router": {
                "action_type": "code",
                "target": "code_execution",
                "reason": "code generated, waiting confirmation",
                "mode": "manual",
            },
            "pending_route": {
                "stage": "confirm_code_execute",
                "action_type": "code",
                "target": "code_execution",
                "mode": "manual",
                "code": code,
                "summary": summary,
                "uploaded_file": normalized_file,
            },
        }

    return _execute_generated_code(code, summary, libraries, export_dir, normalized_file)
