import json
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CONVERSATIONS_PATH = DATA_DIR / "conversations.json"


def _ensure_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONVERSATIONS_PATH.exists():
        CONVERSATIONS_PATH.write_text(
            json.dumps({"conversations": [], "currentConversationId": None}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_conversations_state() -> Dict:
    _ensure_file()
    raw = CONVERSATIONS_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"conversations": [], "currentConversationId": None}

    if not isinstance(data, dict):
        data = {"conversations": [], "currentConversationId": None}

    conversations = data.get("conversations")
    if not isinstance(conversations, list):
        conversations = []

    current_id = data.get("currentConversationId")
    if current_id is not None and not isinstance(current_id, str):
        current_id = None

    return {
        "conversations": conversations,
        "currentConversationId": current_id,
    }


def save_conversations_state(state: Dict) -> None:
    _ensure_file()
    payload = {
        "conversations": state.get("conversations", []),
        "currentConversationId": state.get("currentConversationId"),
    }
    CONVERSATIONS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
