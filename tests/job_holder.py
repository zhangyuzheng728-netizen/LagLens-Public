"""Helper for verify_job_cleanup.py.

Creates a kill-on-close job, starts PresentMon inside it, reports the
PIDs, then sleeps.  Killing this process simulates a LagLens crash: the
job handle closes and PresentMon must be terminated by Windows.
"""

import json
import os
import subprocess
import sys
import time

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import capture_core  # noqa: E402
from win32_support import ProcessJob  # noqa: E402


def main():

    report_path = Path(sys.argv[1])
    exe = Path(sys.argv[2])
    csv_path = Path(sys.argv[3])

    result = {
        "holder_pid": os.getpid(),
        "job_available": False,
        "job_error": "",
        "presentmon_pid": None,
        "assigned": False,
    }

    job = ProcessJob()
    result["job_available"] = job.available
    result["job_error"] = job.error

    if job.available:

        command = [
            str(exe),
            "--session_name",
            capture_core.SESSION,
            "--stop_existing_session",
            "--process_name",
            "dwm.exe",
            "--output_file",
            str(csv_path),
            "--no_console_stats",
            "--v2_metrics",
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=capture_core.NO_WINDOW,
        )

        result["presentmon_pid"] = process.pid
        result["assigned"] = job.assign(process)

    report_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    # Hold the job handle open until the parent kills this process.
    time.sleep(120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
