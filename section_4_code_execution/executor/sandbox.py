import base64
import io
import os
import re
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


SAFE_FORBIDDEN_TOKENS = [
    "import os",
    "from os",
    "import sys",
    "from sys",
    "import subprocess",
    "from subprocess",
    "import socket",
    "from socket",
    "import requests",
    "from requests",
    "import httpx",
    "from httpx",
    "import urllib",
    "from urllib",
    "__import__",
    "open(",
    "eval(",
    "exec(",
    "compile(",
    "input(",
    "system(",
    "popen(",
]


@dataclass
class ExecutionResult:
    ok: bool
    stdout: str
    result_text: str
    image_data_url: str = ""
    error: str = ""
    export_relative_path: str = ""


def _validate_library_permissions(code: str, libraries: List[str]) -> Optional[str]:
    lowered = code.lower()
    allow_pandas = "pandas" in libraries
    allow_numpy = "numpy" in libraries
    allow_matplotlib = "matplotlib" in libraries

    if ("import pandas" in lowered or "from pandas" in lowered) and not allow_pandas:
        return "pandas 尚未在環境允許清單中。"
    if ("import numpy" in lowered or "from numpy" in lowered or " np." in lowered) and not allow_numpy:
        return "numpy 尚未在環境允許清單中。"
    if ("import matplotlib" in lowered or "from matplotlib" in lowered or "plt." in lowered) and not allow_matplotlib:
        return "matplotlib 尚未在環境允許清單中。"
    return None


def _validate_safe_mode(code: str) -> Optional[str]:
    lowered = code.lower()
    for token in SAFE_FORBIDDEN_TOKENS:
        if token in lowered:
            return f"Safe policy blocked token: `{token}`"
    return None


def _extract_matplotlib_image() -> str:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        return ""

    fig_nums = plt.get_fignums()
    if not fig_nums:
        return ""

    fig = plt.figure(fig_nums[-1])
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)
    encoded = base64.b64encode(buffer.read()).decode("utf-8")
    plt.close("all")
    return f"data:image/png;base64,{encoded}"


def _maybe_export_dataframe(local_vars: dict, export_dir: Optional[str]) -> str:
    if not export_dir:
        return ""

    df = local_vars.get("RESULT_DF")
    if df is None:
        return ""

    # We don't require pandas import check here; if it's DataFrame-like and has to_excel, use it.
    if not hasattr(df, "to_excel"):
        return ""

    filename = str(local_vars.get("RESULT_FILENAME", "")).strip() or "cleaned_output.xlsx"
    if not filename.lower().endswith(".xlsx"):
        filename = f"{filename}.xlsx"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    if not filename:
        filename = "cleaned_output.xlsx"

    target_dir = Path(export_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{int(time.time())}_{filename}"
    out_path = target_dir / out_name

    df.to_excel(out_path, index=False, engine="openpyxl")  # type: ignore[attr-defined]
    return f"/section_4_code_execution/data/exports/{out_name}"


def execute_python_code(
    code: str,
    mode: str = "safe",
    libraries: Optional[List[str]] = None,
    export_dir: Optional[str] = None,
    uploaded_file_path: Optional[str] = None,
) -> ExecutionResult:
    code = (code or "").strip()
    libraries = libraries or []

    if not code:
        return ExecutionResult(ok=False, stdout="", result_text="", error="沒有可執行的程式碼。")
    if len(code) > 12000:
        return ExecutionResult(ok=False, stdout="", result_text="", error="程式碼過長，請精簡後再試。")

    lib_err = _validate_library_permissions(code, libraries)
    if lib_err:
        return ExecutionResult(ok=False, stdout="", result_text="", error=lib_err)

    if mode == "safe":
        safe_err = _validate_safe_mode(code)
        if safe_err:
            return ExecutionResult(ok=False, stdout="", result_text="", error=safe_err)

    local_vars = {}
    stdout_capture = io.StringIO()

    try:
        # Force headless plotting backend to avoid Tk/thread crashes
        # in ThreadingHTTPServer worker threads on Windows.
        os.environ["MPLBACKEND"] = "Agg"
        if ("matplotlib" in code.lower()) or ("plt." in code.lower()):
            try:
                import matplotlib  # type: ignore
                matplotlib.use("Agg", force=True)  # type: ignore[attr-defined]
            except Exception:
                pass

        compiled = compile(code, "<generated_code>", "exec")
        globals_dict = {
            "__name__": "__main__",
            "UPLOADED_FILE_PATH": str(uploaded_file_path or ""),
        }
        with redirect_stdout(stdout_capture):
            exec(compiled, globals_dict, local_vars)
    except Exception as exc:  # noqa: BLE001
        return ExecutionResult(
            ok=False,
            stdout=stdout_capture.getvalue().strip(),
            result_text="",
            error=f"{type(exc).__name__}: {exc}",
        )

    stdout_text = stdout_capture.getvalue().strip()
    result_text = str(local_vars.get("RESULT_TEXT", "")).strip() or stdout_text or "程式執行完成。"
    image_data_url = _extract_matplotlib_image()
    export_relative_path = _maybe_export_dataframe(local_vars, export_dir)

    return ExecutionResult(
        ok=True,
        stdout=stdout_text,
        result_text=result_text,
        image_data_url=image_data_url,
        export_relative_path=export_relative_path,
    )
