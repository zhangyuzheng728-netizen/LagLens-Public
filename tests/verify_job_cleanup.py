"""Real Windows test: kill the job holder, verify PresentMon dies.

Requires Administrator (PresentMon needs ETW access).

The parent starts tests/job_holder.py, which creates a kill-on-close job
and launches PresentMon inside it.  The parent then kills the holder
(simulating a LagLens crash) and checks that:

  * PresentMon is terminated by the OS
  * the LagLensCapture ETW session is cleaned up (immediately or by
    the same startup cleanup LagLens performs)

Result JSON: captures/verify_job_cleanup.json
"""

import json
import subprocess
import sys
import time
import traceback

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402

import capture_core  # noqa: E402


def session_listed(name):

    try:

        result = subprocess.run(
            ["logman", "query", "-ets"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )

    except (
        OSError,
        subprocess.TimeoutExpired,
    ):

        return None

    output = (
        (result.stdout or "")
        + (result.stderr or "")
    ).lower()

    return name.lower() in output


def run():

    result = {
        "elevated": capture_core.is_elevated(),
        "cleanup_before_returncode": None,
        "holder_started": False,
        "holder_pid": None,
        "presentmon_pid": None,
        "assigned": False,
        "presentmon_alive_before_kill": None,
        "holder_killed": False,
        "presentmon_gone": False,
        "presentmon_gone_seconds": None,
        "session_after_kill": None,
        "cleanup_returncode": None,
        "session_after_cleanup": None,
        "error": None,
    }

    if not result["elevated"]:

        result["error"] = "not elevated"
        return result

    presentmon = (
        ROOT
        / "vendor"
        / "presentmon"
        / "PresentMon-2.6.0-x64.exe"
    )

    if not presentmon.is_file():

        result["error"] = (
            f"PresentMon not found: {presentmon}"
        )
        return result

    result["cleanup_before_returncode"] = (
        capture_core.cleanup_stale_session(
            str(presentmon)
        )
    )

    report_path = (
        ROOT / "captures" / "job_holder.json"
    )
    csv_path = (
        ROOT / "captures" / "job_holder_probe.csv"
    )
    report_path.unlink(missing_ok=True)

    holder = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tests" / "job_holder.py"),
            str(report_path),
            str(presentmon),
            str(csv_path),
        ],
        cwd=str(ROOT),
    )

    result["holder_started"] = True

    deadline = time.monotonic() + 20

    while (
        not report_path.exists()
        and time.monotonic() < deadline
    ):

        time.sleep(0.2)

    if not report_path.exists():

        result["error"] = "holder did not report"
        holder.kill()
        return result

    report = json.loads(
        report_path.read_text(encoding="utf-8")
    )

    result["holder_pid"] = report.get("holder_pid")
    result["presentmon_pid"] = report.get(
        "presentmon_pid"
    )
    result["assigned"] = report.get("assigned")

    if report.get("job_available") is False:

        result["error"] = (
            "job object unavailable: "
            + str(report.get("job_error"))
        )
        holder.kill()
        return result

    # PresentMon has started; make sure it is alive.
    presentmon_process = None

    if result["presentmon_pid"]:

        try:

            presentmon_process = psutil.Process(
                result["presentmon_pid"]
            )

        except psutil.NoSuchProcess:

            presentmon_process = None

    result["presentmon_alive_before_kill"] = bool(
        presentmon_process
        and presentmon_process.is_running()
    )

    # Simulate a LagLens crash: kill the holder without cleanup.
    holder.kill()
    result["holder_killed"] = True

    try:

        holder.wait(timeout=5)

    except subprocess.TimeoutExpired:  # pragma: no cover

        pass

    started = time.monotonic()
    gone = False

    deadline = started + 10

    while time.monotonic() < deadline:

        if result["presentmon_pid"]:

            gone = not psutil.pid_exists(
                result["presentmon_pid"]
            )

        if gone:

            break

        time.sleep(0.1)

    result["presentmon_gone"] = gone
    result["presentmon_gone_seconds"] = round(
        time.monotonic() - started,
        2,
    )

    time.sleep(1.0)

    result["session_after_kill"] = session_listed(
        capture_core.SESSION
    )

    if result["session_after_kill"]:

        result["cleanup_returncode"] = (
            capture_core.cleanup_stale_session(
                str(presentmon)
            )
        )

        time.sleep(0.5)

        result["session_after_cleanup"] = session_listed(
            capture_core.SESSION
        )

    else:

        result["session_after_cleanup"] = False

    csv_path.unlink(missing_ok=True)

    return result


def main():

    try:

        result = run()

    except Exception as error:  # noqa: BLE001

        result = {
            "error": repr(error),
            "traceback": traceback.format_exc(),
        }

    out = ROOT / "captures" / "verify_job_cleanup.json"
    out.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2))

    ok = (
        result.get("error") is None
        and result.get("assigned")
        and result.get("presentmon_alive_before_kill")
        and result.get("presentmon_gone")
        and result.get("session_after_cleanup") is False
    )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
