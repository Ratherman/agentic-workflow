import argparse
import atexit
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode


PROJECT_ROOT = Path(__file__).resolve().parent
UI_INDEX_RELATIVE = Path("shared/ui/index.html")
UI_PORT = 8080
BACKEND_PORT = 9000

SECTION_DIRS = {
    0: "section_0_basic_llm",
    1: "section_1_patterns",
    2: "section_2_tool_calling",
    3: "section_3_workflow_integration",
    4: "section_4_code_execution",
    5: "section_5_security",
    6: "section_6_production_ready",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run shared UI and optionally boot section backend.",
    )
    parser.add_argument("--fresh", action="store_true", help="Shortcut for --section 0")
    parser.add_argument(
        "--section",
        type=int,
        choices=range(0, 7),
        default=None,
        help="Section to unlock in UI (0~6)",
    )
    return parser.parse_args()


def choose_section(args: argparse.Namespace) -> int:
    if args.fresh:
        return 0
    if args.section is not None:
        return args.section
    return 0


def start_ui_server(ui_port: int) -> ThreadingHTTPServer:
    handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(PROJECT_ROOT), **k)
    server = ThreadingHTTPServer(("127.0.0.1", ui_port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def section_backend_path(section: int) -> Path:
    return PROJECT_ROOT / SECTION_DIRS[section] / "app.py"


def _start_backend_log_pump(proc: subprocess.Popen, section: int) -> None:
    if proc.stdout is None:
        return

    def _pump() -> None:
        try:
            for line in proc.stdout:
                text = line.rstrip()
                if text:
                    print(f"[section-{section}] {text}")
        except Exception:
            return

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()


def start_section_backend(section: int, backend_port: int) -> Optional[subprocess.Popen]:
    app_path = section_backend_path(section)
    if not app_path.exists():
        return None

    section_dir = app_path.parent
    cmd = [sys.executable, str(app_path), "--port", str(backend_port)]
    print(f"[manager] Trying backend: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        cwd=str(section_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    _start_backend_log_pump(proc, section)

    time.sleep(1.2)
    if proc.poll() is not None:
        output = proc.stdout.read() if proc.stdout else ""
        print("[manager] Backend exited early. Falling back to UI-only mode.")
        if output:
            print("[manager] Backend output:")
            print(output.strip())
        return None

    return proc


def build_ui_url(ui_port: int, section: int, backend_port: int, backend_enabled: bool) -> str:
    query = {"max_section": str(section)}
    if backend_enabled:
        query["backend_url"] = f"http://127.0.0.1:{backend_port}"
    return f"http://127.0.0.1:{ui_port}/{UI_INDEX_RELATIVE.as_posix()}?{urlencode(query)}"


def main() -> None:
    args = parse_args()
    section = choose_section(args)

    ui_server = start_ui_server(UI_PORT)
    atexit.register(ui_server.shutdown)

    backend_proc = None
    if not args.fresh:
        backend_proc = start_section_backend(section, BACKEND_PORT)
    if backend_proc:
        atexit.register(lambda: backend_proc.terminate() if backend_proc.poll() is None else None)

    url = build_ui_url(
        ui_port=UI_PORT,
        section=section,
        backend_port=BACKEND_PORT,
        backend_enabled=backend_proc is not None,
    )

    print(f"[manager] Section = {section}")
    print(f"[manager] UI server running at http://127.0.0.1:{UI_PORT}")
    if backend_proc is None:
        print("[manager] Backend = not started (UI mock thinking mode)")
    else:
        print(f"[manager] Backend = http://127.0.0.1:{BACKEND_PORT}")
    print(f"[manager] Open: {url}")

    webbrowser.open(url)

    try:
        while True:
            time.sleep(0.5)
            if backend_proc is not None and backend_proc.poll() is not None:
                return_code = backend_proc.returncode
                print(f"[manager] Backend stopped unexpectedly (code={return_code}).")
                print("[manager] Attempting auto-restart...")
                backend_proc = start_section_backend(section, BACKEND_PORT)
                if backend_proc is None:
                    print("[manager] Restart failed. UI remains available in mock mode.")
                    break
                print(f"[manager] Backend restarted at http://127.0.0.1:{BACKEND_PORT}")
    except KeyboardInterrupt:
        pass
    finally:
        if backend_proc is not None and backend_proc.poll() is None:
            backend_proc.terminate()
        ui_server.shutdown()


if __name__ == "__main__":
    main()
