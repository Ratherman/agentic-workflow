import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from section_0_basic_llm.llm import generate_chat_title
from section_1_workflow_patterns.agent import handle_section1_chat
from shared.conversation_store import load_conversations_state, save_conversations_state
from shared.task_store import load_tasks, create_task, toggle_task


class ChatRequest(BaseModel):
    message: str
    config: Dict[str, Any]
    history: list = []
    image_data_url: Optional[str] = None
    router_context: Optional[Dict[str, Any]] = None


class TitleRequest(BaseModel):
    message: str
    config: Dict[str, Any]


class TaskCreateRequest(BaseModel):
    title: str
    source: str = "manual"


class TaskToggleRequest(BaseModel):
    task_id: str


class ConversationsSyncRequest(BaseModel):
    conversations: list
    currentConversationId: Optional[str] = None


class Section1Handler(BaseHTTPRequestHandler):
    server_version = "Section1HTTP/0.1"

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._set_headers(200)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._set_headers(200)
            self.wfile.write(json.dumps({"ok": True, "section": 1}).encode("utf-8"))
            return
        if self.path == "/tasks":
            self._set_headers(200)
            self.wfile.write(json.dumps({"tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
            return
        if self.path == "/conversations":
            self._set_headers(200)
            self.wfile.write(json.dumps(load_conversations_state(), ensure_ascii=False).encode("utf-8"))
            return

        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))

    def do_POST(self) -> None:
        if self.path not in {"/chat", "/title", "/tasks", "/tasks/toggle", "/conversations/sync"}:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            payload = json.loads(body)

            if self.path == "/title":
                request = TitleRequest.model_validate(payload)
                llm_cfg = request.config.get("llm", {})
                title = generate_chat_title(seed_message=request.message, llm_config=llm_cfg)
                self._set_headers(200)
                self.wfile.write(json.dumps({"title": title}, ensure_ascii=False).encode("utf-8"))
                return

            if self.path == "/tasks":
                request = TaskCreateRequest.model_validate(payload)
                if not request.title.strip():
                    raise RuntimeError("Task title cannot be empty.")
                task = create_task(title=request.title, source=request.source)
                self._set_headers(200)
                self.wfile.write(json.dumps({"task": task, "tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
                return

            if self.path == "/tasks/toggle":
                request = TaskToggleRequest.model_validate(payload)
                task = toggle_task(task_id=request.task_id)
                if task is None:
                    self._set_headers(404)
                    self.wfile.write(json.dumps({"error": "task not found"}).encode("utf-8"))
                    return
                self._set_headers(200)
                self.wfile.write(json.dumps({"task": task, "tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
                return

            if self.path == "/conversations/sync":
                request = ConversationsSyncRequest.model_validate(payload)
                save_conversations_state(
                    {
                        "conversations": request.conversations,
                        "currentConversationId": request.currentConversationId,
                    }
                )
                self._set_headers(200)
                self.wfile.write(json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"))
                return

            request = ChatRequest.model_validate(payload)
            result = handle_section1_chat(
                user_message=request.message,
                config=request.config,
                history=request.history,
                image_data_url=request.image_data_url,
                router_context=request.router_context,
            )
            self._set_headers(200)
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        except ValidationError as exc:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "invalid request", "detail": str(exc)}).encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": "chat failed", "detail": str(exc)}).encode("utf-8"))



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9000)
    return parser.parse_args()



def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

    args = parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Section1Handler)
    print(f"Section 1 backend running at http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
