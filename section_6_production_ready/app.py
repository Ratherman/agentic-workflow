import argparse
import base64
import importlib.util
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from section_0_basic_llm.llm import generate_chat_title
from section_6_production_ready.orchestrator import handle_section6_chat
from section_6_production_ready.observability.costing import load_pricing_table
from shared.conversation_store import load_conversations_state, save_conversations_state
from shared.task_store import create_task, load_tasks, toggle_task, update_task, delete_task

EXPORTS_DIR = PROJECT_ROOT / "section_4_code_execution" / "data" / "exports"
UPLOADS_DIR = PROJECT_ROOT / "section_4_code_execution" / "data" / "uploads"


class ChatRequest(BaseModel):
    message: str
    config: Dict[str, Any]
    history: list = []
    image_data_url: Optional[str] = None
    uploaded_file: Optional[Dict[str, Any]] = None
    router_context: Optional[Dict[str, Any]] = None


class TitleRequest(BaseModel):
    message: str
    config: Dict[str, Any]


class TaskCreateRequest(BaseModel):
    title: str
    source: str = "manual"


class TaskToggleRequest(BaseModel):
    task_id: str


class TaskUpdateRequest(BaseModel):
    task_id: str
    title: str


class TaskDeleteRequest(BaseModel):
    task_id: str


class ConversationsSyncRequest(BaseModel):
    conversations: list
    currentConversationId: Optional[str] = None


class FileUploadRequest(BaseModel):
    filename: str
    data_base64: str


class Section6Handler(BaseHTTPRequestHandler):
    server_version = "Section6HTTP/0.1"

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
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self._set_headers(200)
            supported_libraries = []
            for lib in ["pandas", "numpy", "matplotlib"]:
                if importlib.util.find_spec(lib) is not None:
                    supported_libraries.append(lib)
            self.wfile.write(
                json.dumps(
                    {
                        "ok": True,
                        "section": 6,
                        "supported_libraries": supported_libraries,
                        "pricing_models": sorted(load_pricing_table().keys()),
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return
        if path == "/tasks":
            self._set_headers(200)
            self.wfile.write(json.dumps({"tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
            return
        if path == "/conversations":
            self._set_headers(200)
            self.wfile.write(json.dumps(load_conversations_state(), ensure_ascii=False).encode("utf-8"))
            return

        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path not in {
            "/chat", "/title", "/tasks", "/tasks/toggle", "/tasks/update", "/tasks/edit",
            "/tasks/delete", "/tasks/remove", "/conversations/sync", "/files"
        }:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            payload = json.loads(body)

            if path == "/title":
                request = TitleRequest.model_validate(payload)
                llm_cfg = request.config.get("llm", {})
                title = generate_chat_title(seed_message=request.message, llm_config=llm_cfg)
                self._set_headers(200)
                self.wfile.write(json.dumps({"title": title}, ensure_ascii=False).encode("utf-8"))
                return

            if path == "/tasks":
                request = TaskCreateRequest.model_validate(payload)
                if not request.title.strip():
                    raise RuntimeError("Task title cannot be empty.")
                task = create_task(title=request.title, source=request.source)
                self._set_headers(200)
                self.wfile.write(json.dumps({"task": task, "tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
                return

            if path == "/tasks/toggle":
                request = TaskToggleRequest.model_validate(payload)
                task = toggle_task(task_id=request.task_id)
                if task is None:
                    self._set_headers(404)
                    self.wfile.write(json.dumps({"error": "task not found"}).encode("utf-8"))
                    return
                self._set_headers(200)
                self.wfile.write(json.dumps({"task": task, "tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
                return

            if path in {"/tasks/update", "/tasks/edit"}:
                request = TaskUpdateRequest.model_validate(payload)
                if not request.title.strip():
                    raise RuntimeError("Task title cannot be empty.")
                task = update_task(task_id=request.task_id, title=request.title)
                if task is None:
                    self._set_headers(404)
                    self.wfile.write(json.dumps({"error": "task not found"}).encode("utf-8"))
                    return
                self._set_headers(200)
                self.wfile.write(json.dumps({"task": task, "tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
                return

            if path in {"/tasks/delete", "/tasks/remove"}:
                request = TaskDeleteRequest.model_validate(payload)
                task = delete_task(task_id=request.task_id)
                if task is None:
                    self._set_headers(404)
                    self.wfile.write(json.dumps({"error": "task not found"}).encode("utf-8"))
                    return
                self._set_headers(200)
                self.wfile.write(json.dumps({"task": task, "tasks": load_tasks()}, ensure_ascii=False).encode("utf-8"))
                return

            if path == "/conversations/sync":
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

            if path == "/files":
                req = FileUploadRequest.model_validate(payload)
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", req.filename).strip("._")
                if not safe_name:
                    raise RuntimeError("invalid filename")
                ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
                if ext not in {"csv", "xlsx"}:
                    raise RuntimeError("only csv/xlsx is supported")

                raw = base64.b64decode(req.data_base64, validate=False)
                UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                out_name = f"{int(time.time())}_{safe_name}"
                out_path = UPLOADS_DIR / out_name
                out_path.write_bytes(raw)

                self._set_headers(200)
                self.wfile.write(
                    json.dumps(
                        {
                            "file": {
                                "name": safe_name,
                                "stored_name": out_name,
                                "path": out_path.as_posix(),
                                "relative_path": str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                                "size_bytes": int(len(raw)),
                            }
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

            request_obj = ChatRequest.model_validate(payload)
            result = handle_section6_chat(
                user_message=request_obj.message,
                config=request_obj.config,
                history=request_obj.history,
                image_data_url=request_obj.image_data_url,
                uploaded_file=request_obj.uploaded_file,
                router_context=request_obj.router_context,
                export_dir=str(EXPORTS_DIR),
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
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Section6Handler)
    print(f"Section 6 backend running at http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
