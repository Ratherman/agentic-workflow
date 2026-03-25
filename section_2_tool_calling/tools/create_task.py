import re
from typing import Dict

from shared.task_store import create_task


def _extract_title(user_message: str) -> str:
    text = (user_message or "").strip()
    if not text:
        return "未命名任務"

    # Prefer text after ':' or '：'
    for sep in [":", "："]:
        if sep in text:
            right = text.split(sep, 1)[1].strip()
            if right:
                return right

    # Remove common command prefixes for cleaner title.
    cleaned = re.sub(r"^(幫我|請|麻煩)?(建立|新增|加一個)?(任務|代辦|待辦)\s*", "", text)
    cleaned = cleaned.strip(" ，。")
    return cleaned or text


def run(user_message: str) -> Dict:
    title = _extract_title(user_message)
    task = create_task(title=title, source="tool")
    return {
        "ok": True,
        "tool": "create_task",
        "task": task,
        "message": f"已建立任務：{task['title']}",
    }
