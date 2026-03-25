import json
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
TASKS_PATH = DATA_DIR / "tasks.json"


def _ensure_tasks_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TASKS_PATH.exists():
        TASKS_PATH.write_text("[]", encoding="utf-8")


def load_tasks() -> List[Dict]:
    _ensure_tasks_file()
    raw = TASKS_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
    if not isinstance(data, list):
        data = []
    return data


def save_tasks(tasks: List[Dict]) -> None:
    _ensure_tasks_file()
    TASKS_PATH.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_task(title: str, source: str = "manual") -> Dict:
    tasks = load_tasks()
    task = {
        "id": str(uuid4()),
        "title": title.strip(),
        "status": "pending",
        "source": source,
    }
    tasks.append(task)
    save_tasks(tasks)
    return task


def toggle_task(task_id: str) -> Optional[Dict]:
    tasks = load_tasks()
    target = None
    for task in tasks:
        if task.get("id") == task_id:
            status = task.get("status", "pending")
            task["status"] = "done" if status != "done" else "pending"
            target = task
            break
    save_tasks(tasks)
    return target
