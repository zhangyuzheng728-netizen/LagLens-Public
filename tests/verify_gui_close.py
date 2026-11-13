"""Real GUI close test for LagLens (requires Administrator).

Starts a dwm.exe capture through the real GUI, closes the window and
verifies that:

* close() returns immediately instead of blocking the GUI thread
* the window eventually closes
* no PresentMon process using the LagLensCapture session is left behind

The Qt platform is "offscreen" so the test does not disturb the desktop;
the Qt event loop, QThread and signal handling are the production ones.

Result JSON: captures/verify_gui_close.json
"""

import json
import os
import sys
import time
import traceback

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import capture_core  # noqa: E402
import main as laglens  # noqa: E402
from win32_support import ProcessJob  # noqa: E402


def leftover_presentmon():

    leftovers = []

    for process in psutil.process_iter(
        ["name", "cmdline"]
    ):

        try:

            name = process.info["name"] or ""
            command = " ".join(
                process.info["cmdline"] or []
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):

            continue

        if (
            "presentmon" in name.lower()
            and capture_core.SESSION.lower()
            in command.lower()
        ):

            leftovers.append(
                {
                    "pid": process.pid,
                    "name": name,
                    "command": command[:300],
                }
            )

    return leftovers


def run():

    result = {
        "elevated": capture_core.is_elevated(),
        "session": capture_core.SESSION,
        "cleanup_returncode": None,
        "frames_seen": False,
        "batches_before_close": 0,
        "first_batch_seconds": None,
        "status_before_close": "",
        "close_call_seconds": None,
        "visible_after_close_call": None,
        "closed": False,
        "close_total_seconds": None,
        "last_csv": None,
        "job_available": False,
        "job_error": "",
        "job_log": [],
        "leftover_presentmon": [],
        "error": None,
    }

    if not result["elevated"]:

        result["error"] = "not elevated"
        return result

    # Phase 1 startup cleanup must only touch our own session.
    result["cleanup_returncode"] = (
        capture_core.cleanup_stale_session(
            str(laglens.DEFAULT_PRESENTMON)
        )
    )

    laglens.configure_logging()

    job = ProcessJob()

    result["job_available"] = job.available
    result["job_error"] = job.error

    import pynvml

    pynvml.nvmlInit()
    gpu = pynvml.nvmlDeviceGetHandleByIndex(0)

    app = QApplication(sys.argv)

    window = laglens.LagLens(gpu, job)

    window.show()
    window.auto_analyze.setChecked(False)
    window.process_combo.setCurrentText("dwm.exe")

    started_capture = time.monotonic()
    batches = []

    window.start_capture()

    if window.worker is not None:

        window.worker.batch.connect(
            lambda data: batches.append(
                (
                    round(
                        time.monotonic()
                        - started_capture,
                        2,
                    ),
                    data[1],
                )
            )
        )

    # Wait up to 10 s for the first live batch, then give the live
    # view two more seconds to update.
    deadline = started_capture + 10.0

    while (
        not batches
        and time.monotonic() < deadline
    ):

        app.processEvents()
        time.sleep(0.02)

    result["first_batch_seconds"] = (
        batches[0][0] if batches else None
    )

    deadline = time.monotonic() + 2.0

    while time.monotonic() < deadline:

        app.processEvents()
        time.sleep(0.02)

    result["batches_before_close"] = len(batches)
    result["frames_seen"] = window.frames_received
    result["status_before_close"] = (
        window.frame_status.text()
    )

    started = time.perf_counter()
    window.close()
    result["close_call_seconds"] = round(
        time.perf_counter() - started,
        3,
    )
    result["visible_after_close_call"] = (
        window.isVisible()
    )

    deadline = time.monotonic() + 25.0

    while window.isVisible() and time.monotonic() < deadline:

        app.processEvents()
        time.sleep(0.02)

    result["closed"] = not window.isVisible()
    result["close_total_seconds"] = round(
        time.perf_counter() - started,
        3,
    )
    result["last_csv"] = window.last_csv

    job.close()

    # Give the OS a moment to reap the child process.
    time.sleep(1.0)

    result["leftover_presentmon"] = (
        leftover_presentmon()
    )

    log_path = ROOT / "captures" / "laglens.log"

    if log_path.is_file():

        result["job_log"] = [
            line
            for line in log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
            if "job" in line.lower()
        ][-3:]

    try:

        pynvml.nvmlShutdown()

    except pynvml.NVMLError:

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

    out = ROOT / "captures" / "verify_gui_close.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2))

    ok = (
        result.get("error") is None
        and result.get("closed")
        and not result.get("leftover_presentmon")
        and result.get("close_call_seconds", 99) < 1.0
    )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
