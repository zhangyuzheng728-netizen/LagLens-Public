"""Real test for "Stop when target exits" (Requires Administrator).

Starts a Qt Quick presenter with pythonw.exe, captures it through the
real LagLens window with the option enabled, then waits without ever
calling stop().  LagLens must detect the target exit and stop the
capture itself.

PresentMon 2.6's own --terminate_on_proc_exit was tested with both
--process_name and --process_id and did not terminate the capture, so
this feature is implemented in the application.

Result JSON: captures/verify_stop_on_exit.json
"""

import json
import os
import subprocess
import sys
import time
import traceback

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pynvml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import capture_core  # noqa: E402
import main as laglens  # noqa: E402
from win32_support import ProcessJob  # noqa: E402


def run(seconds=7.0):

    result = {
        "elevated": capture_core.is_elevated(),
        "presenter_seconds": seconds,
        "presenter_pid": None,
        "finished": False,
        "manual_stop": False,
        "auto_stop_seconds": None,
        "target_seen": False,
        "presenter_exit": None,
        "last_csv": None,
        "rows": 0,
        "valid_frames": 0,
        "error": None,
    }

    if not result["elevated"]:

        result["error"] = "not elevated"
        return result

    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"

    if not pythonw.is_file():

        result["error"] = f"pythonw.exe not found: {pythonw}"
        return result

    child_env = os.environ.copy()
    child_env.pop("QT_QPA_PLATFORM", None)

    presenter = subprocess.Popen(
        [
            str(pythonw),
            str(ROOT / "tests" / "fake_presenter.py"),
            str(seconds),
        ],
        cwd=str(ROOT),
        env=child_env,
    )

    result["presenter_pid"] = presenter.pid

    time.sleep(1.5)

    laglens.configure_logging()

    job = ProcessJob()

    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)

    app = QApplication(sys.argv)

    window = laglens.LagLens(gpu, job)
    window.show()
    window.auto_analyze.setChecked(False)
    window.process_combo.setCurrentText("pythonw.exe")
    window.stop_on_exit.setChecked(True)

    window.start_capture()

    started = time.monotonic()
    deadline = started + seconds + 25

    while (
        window.worker is not None
        and window.worker.isRunning()
        and time.monotonic() < deadline
    ):

        app.processEvents()
        time.sleep(0.05)

    running = (
        window.worker is not None
        and window.worker.isRunning()
    )

    result["finished"] = not running

    if running:

        result["manual_stop"] = True
        window.stop_capture()

        deadline = time.monotonic() + 20

        while (
            window.worker is not None
            and window.worker.isRunning()
            and time.monotonic() < deadline
        ):

            app.processEvents()
            time.sleep(0.05)

    app.processEvents()

    result["auto_stop_seconds"] = round(
        time.monotonic() - started,
        2,
    )
    result["target_seen"] = window._target_seen
    result["presenter_exit"] = presenter.poll()
    result["last_csv"] = window.last_csv

    if window.last_csv:

        info = capture_core.validate_capture(
            window.last_csv
        )

        result["rows"] = info.rows
        result["valid_frames"] = info.valid_frames

        if info.error:

            result["error"] = info.error

    window.close()
    app.processEvents()

    job.close()

    pynvml.nvmlShutdown()

    if presenter.poll() is None:

        presenter.kill()

    try:
        presenter.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover
        pass

    return result


def main():

    try:

        result = run()

    except Exception as error:  # noqa: BLE001

        result = {
            "error": repr(error),
            "traceback": traceback.format_exc(),
        }

    out = ROOT / "captures" / "verify_stop_on_exit.json"
    out.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2))

    ok = (
        result.get("error") is None
        and result.get("finished")
        and not result.get("manual_stop")
        and result.get("target_seen")
        and result.get("presenter_exit") == 0
        and result.get("valid_frames", 0) > 0
    )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
