import json
import os
import urllib.error
import urllib.request
from typing import Dict, List


TAVILY_ENDPOINT = "https://api.tavily.com/search"


def _extract_query(user_message: str) -> str:
    text = (user_message or "").strip()
    if not text:
        return "最新 AI agent 趨勢"

    for sep in [":", "："]:
        if sep in text:
            right = text.split(sep, 1)[1].strip()
            if right:
                return right

    prefixes = ["幫我查", "請幫我查", "幫我搜尋", "請幫我搜尋", "search", "搜尋", "查網路", "上網查"]
    query = text
    for prefix in prefixes:
        if query.startswith(prefix):
            query = query[len(prefix):].strip(" ，。")
            break
    return query or text


def _request_tavily(api_key: str, query: str) -> Dict:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": 3,
        "search_depth": "basic",
        "include_answer": False,
        "include_images": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def run(user_message: str) -> Dict:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    query = _extract_query(user_message)

    if not api_key:
        return {
            "ok": False,
            "tool": "search_web",
            "query": query,
            "results": [],
            "message": "缺少 TAVILY_API_KEY，請在 .env 設定後重試。",
        }

    try:
        response = _request_tavily(api_key=api_key, query=query)
        results: List[Dict] = []
        for item in (response.get("results") or [])[:3]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                }
            )

        return {
            "ok": True,
            "tool": "search_web",
            "query": query,
            "results": results,
            "message": f"已取得 {len(results)} 筆 Tavily 搜尋結果。",
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "tool": "search_web",
            "query": query,
            "results": [],
            "message": f"Tavily HTTP 錯誤：{exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "tool": "search_web",
            "query": query,
            "results": [],
            "message": f"Tavily 呼叫失敗：{exc}",
        }
