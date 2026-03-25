import base64
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRICING_PATH = PROJECT_ROOT / "section_6_production_ready" / "pricing.json"


def _load_pricing_raw() -> Dict[str, Any]:
    try:
        raw = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def load_pricing_table() -> Dict[str, Dict[str, float]]:
    raw = _load_pricing_raw()
    out: Dict[str, Dict[str, float]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        if "input_per_million_usd" in value and "output_per_million_usd" in value:
            out[str(key)] = value
    return out


def load_usd_to_twd_rate() -> float:
    raw = _load_pricing_raw()
    try:
        rate = float(raw.get("usd_to_twd", 32.0))
        return rate if rate > 0 else 32.0
    except Exception:
        return 32.0


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_image_tokens(image_data_url: str) -> int:
    if not image_data_url or "," not in image_data_url:
        return 0
    try:
        b64 = image_data_url.split(",", 1)[1]
        size_bytes = int(len(b64) * 3 / 4)
        # rough estimate for vision input
        return max(1, math.ceil(size_bytes / 750))
    except Exception:
        return 0


def estimate_file_tokens(uploaded_file: Optional[Dict[str, Any]]) -> int:
    if not isinstance(uploaded_file, dict):
        return 0
    size = int(uploaded_file.get("size_bytes") or 0)
    if size <= 0:
        return 0
    # rough estimate for tabular/text file content tokenization
    return max(1, math.ceil(size / 12))


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int, pricing: Dict[str, Dict[str, float]]) -> float:
    row = pricing.get(model, {}) if isinstance(pricing, dict) else {}
    in_rate = float(row.get("input_per_million_usd", 0.0) or 0.0)
    out_rate = float(row.get("output_per_million_usd", 0.0) or 0.0)
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def build_usage_metrics(
    *,
    model: str,
    user_text: str,
    assistant_text: str,
    image_data_url: str,
    uploaded_file: Optional[Dict[str, Any]],
    pricing: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    input_text_tokens = estimate_text_tokens(user_text)
    input_image_tokens = estimate_image_tokens(image_data_url)
    input_file_tokens = estimate_file_tokens(uploaded_file)
    input_total = input_text_tokens + input_image_tokens + input_file_tokens

    output_tokens = estimate_text_tokens(assistant_text)
    total_tokens = input_total + output_tokens
    cost_usd = compute_cost_usd(model=model, input_tokens=input_total, output_tokens=output_tokens, pricing=pricing)
    usd_to_twd = load_usd_to_twd_rate()
    cost_twd = cost_usd * usd_to_twd

    return {
        "model": model,
        "input_tokens": {
            "text": input_text_tokens,
            "image": input_image_tokens,
            "file": input_file_tokens,
            "total": input_total,
        },
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": round(cost_usd, 8),
        "cost_twd": round(cost_twd, 6),
        "usd_to_twd": usd_to_twd,
        "estimated": True,
    }
