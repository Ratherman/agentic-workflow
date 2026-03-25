import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from openai import OpenAI


@dataclass
class ModerationCheckResult:
    enabled: bool
    available: bool
    flagged: bool
    categories: List[str]
    reason: str = ""


def _extract_flagged_categories(payload: Dict) -> List[str]:
    categories = payload.get("categories", {}) if isinstance(payload, dict) else {}
    if not isinstance(categories, dict):
        return []
    return [key for key, value in categories.items() if bool(value)]


def _build_input_payload(text: str, image_data_url: str) -> object:
    parts = []
    if text:
        parts.append({"type": "input_text", "text": text})
    if image_data_url:
        parts.append({"type": "input_image", "image_url": image_data_url})
    if not parts:
        return text
    if len(parts) == 1 and parts[0]["type"] == "input_text":
        return text
    return parts


def check_openai_moderation(
    *,
    enabled: bool,
    text: str = "",
    image_data_url: str = "",
) -> ModerationCheckResult:
    if not enabled:
        return ModerationCheckResult(
            enabled=False,
            available=False,
            flagged=False,
            categories=[],
            reason="moderation disabled",
        )

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ModerationCheckResult(
            enabled=True,
            available=False,
            flagged=False,
            categories=[],
            reason="OPENAI_API_KEY not found",
        )

    try:
        client = OpenAI(api_key=api_key)
        payload = _build_input_payload(text.strip(), image_data_url.strip())
        response = client.moderations.create(
            model="omni-moderation-latest",
            input=payload,
        )
        item = response.results[0]
        raw = item.model_dump() if hasattr(item, "model_dump") else {}
        categories = _extract_flagged_categories(raw)
        return ModerationCheckResult(
            enabled=True,
            available=True,
            flagged=bool(item.flagged),
            categories=categories,
            reason="ok",
        )
    except Exception as exc:  # noqa: BLE001
        return ModerationCheckResult(
            enabled=True,
            available=False,
            flagged=False,
            categories=[],
            reason=f"moderation error: {exc}",
        )
