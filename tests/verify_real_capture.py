"""Real ETW capture check for LagLens (requires Administrator).

Drives the production CaptureWorker end to end:

    Start -> PresentMon (--output_file) -> live CSV tail -> Stop -> CSV

It validates the result with capture_core.validate_capture() and
frame_viewer.load_frames(), i.e. exactly what the GUI does.

Usage (from an elevated prompt):

    .venv\\Scripts\\python.exe tests\\verify_real_capture.py
    .venv\\Scripts\\python.exe tests\\verify_real_capture.py dwm.exe 10

Arguments:

    1: target process name   (default: dwm.exe)
    2: capture seconds       (default: 10)
    3: PresentMon executable (default: main.DEFAULT_PRESENTMON)
    4: result JSON path      (default: captures/verify_real_capture.json)

Set LAGLENS_VERIFY_FORCE=1 to run without elevation (diagnostics only).

Exit code 0 means a valid CSV with at least one frame was produced.
"""

import json
import os
import sys
import time
import traceback

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

import capture_core  # noqa: E402
import main as laglens  # noqa: E402
from frame_viewer import load_frames  # noqa: E402


def run(
    target="dwm.exe",
    seconds=10.0,
    executable=None,
    result_path=None,
    low_overhead=False,
):
    executable = Path(
        executable or laglens.DEFAULT_PRESENTMON
    )
    result_path = Path(
        result_path
        or (ROOT / "captures" / "verify_real_capture.json")
    )

    csv_path = (
        ROOT
        / "captures"
        / capture_core.safe_capture_name(target)
    )

    result = {
        "elevated": capture_core.is_elevated(),
        "target": target,
        "seconds": seconds,
        "low_overhead": low_overhead,
        "executable": str(executable),
        "csv": str(csv_path),
        "log": str(csv_path.with_suffix(".log")),
        "csv_created": False,
        "samples": [],
        "finished": False,
        "capture_result": None,
        "valid_frames": 0,
        "rows": 0,
        "analysis_frames": 0,
        "warnings": [],
        "summary": "",
        "log_text": "",
        "error": None,
    }

    if (
        not result["elevated"]
        and os.environ.get("LAGLENS_VERIFY_FORCE") != "1"
    ):
        result["error"] = (
            "not elevated; PresentMon cannot create an ETW session"
        )
        return result

    if not executable.is_file():
        result["error"] = (
            f"PresentMon executable not found: {executable}"
        )
        return result

    app = QCoreApplication.instance() or QCoreApplication([])

    worker = laglens.CaptureWorker(
        executable,
        target,
        csv_path,
        low_overhead=low_overhead,
    )

    completed = []
    worker.completed.connect(completed.append)

    started = time.monotonic()
    worker.start()

    # Sample the growing CSV: this also shows whether PresentMon
    # flushes rows while recording (needed by the live chart).
    end = started + seconds

    while time.monotonic() < end:

        time.sleep(0.5)

        try:
            size = csv_path.stat().st_size
        except OSError:
            size = 0

        result["samples"].append(
            [
                round(time.monotonic() - started, 1),
                size,
            ]
        )

    stop_started = time.monotonic()
    worker.stop()
    result["finished"] = bool(worker.wait(60000))
    result["stop_seconds"] = round(
        time.monotonic() - stop_started,
        2,
    )

    app.processEvents()

    if completed:

        captured = completed[0]

        result["capture_result"] = {
            "exit_code": captured.exit_code,
            "rows": captured.rows,
            "valid_frames": captured.valid_frames,
            "forced_stop": captured.forced_stop,
            "error": captured.error,
        }

    info = capture_core.validate_capture(csv_path)

    result["csv_created"] = info.exists
    result["rows"] = info.rows
    result["valid_frames"] = info.valid_frames

    if csv_path.is_file():
        result["csv_bytes"] = csv_path.stat().st_size

    log_text = capture_core.read_capture_log(
        csv_path.with_suffix(".log")
    )

    result["log_text"] = log_text[-4000:]
    result["warnings"] = capture_core.etw_warnings(log_text)
    result["summary"] = capture_core.summarize_log(log_text)

    if info.valid_frames > 0:

        try:
            frames = load_frames(csv_path)
            result["analysis_frames"] = len(frames)

        except Exception as error:  # noqa: BLE001 - reported, not raised
            result["analysis_error"] = repr(error)

    return result


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "dwm.exe"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    executable = sys.argv[3] if len(sys.argv) > 3 else None
    result_path = sys.argv[4] if len(sys.argv) > 4 else None

    low_overhead = os.environ.get(
        "LAGLENS_VERIFY_LOW_OVERHEAD"
    ) == "1"

    try:

        result = run(
            target,
            seconds,
            executable,
            result_path,
            low_overhead,
        )

    except Exception as error:  # noqa: BLE001 - report to the caller

        result = {
            "error": repr(error),
            "traceback": traceback.format_exc(),
        }

    result_path = Path(
        result_path
        or (ROOT / "captures" / "verify_real_capture.json")
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    ok = (
        result.get("valid_frames", 0) > 0
        and not result.get("error")
    )

    print(json.dumps(result, indent=2))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
