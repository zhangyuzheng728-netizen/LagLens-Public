"""P2-5 phase 1/2: Windows-specific helpers."""

import os
import subprocess
import sys
import time
import unittest

import win32_support


def unique_name():

    return (
        "Local\\LagLensTest."
        f"{os.getpid()}.{time.time_ns()}"
    )


@unittest.skipUnless(os.name == "nt", "Windows only")
class SingleInstanceGuardTests(unittest.TestCase):

    def test_second_guard_detects_a_running_instance(self):

        name = unique_name()

        first = win32_support.SingleInstanceGuard(name)
        second = win32_support.SingleInstanceGuard(name)

        try:

            self.assertFalse(first.already_running)
            self.assertTrue(second.already_running)

        finally:

            second.close()
            first.close()

    def test_close_is_idempotent_and_releases_the_name(self):

        name = unique_name()

        first = win32_support.SingleInstanceGuard(name)
        first.close()
        first.close()

        second = win32_support.SingleInstanceGuard(name)

        try:

            self.assertFalse(second.already_running)

        finally:

            second.close()


@unittest.skipUnless(os.name == "nt", "Windows only")
class ProcessJobTests(unittest.TestCase):

    def _sleep_child(self):

        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
            ],
        )

    def _wait_for_exit(self, process, timeout=5.0):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            if process.poll() is not None:

                return True

            time.sleep(0.05)

        return process.poll() is not None

    def test_kill_on_close_terminates_assigned_child(self):

        job = win32_support.ProcessJob()

        if not job.available:

            self.skipTest(
                f"job object unavailable: {job.error}"
            )

        child = self._sleep_child()

        try:

            self.assertTrue(job.assign(child))
            self.assertIsNone(child.poll())

            job.close()

            self.assertTrue(
                self._wait_for_exit(child),
                "assigned child survived job close",
            )

        finally:

            if child.poll() is None:

                child.kill()
                child.wait(timeout=5)

            job.close()

    def test_unassigned_child_is_not_affected(self):

        job = win32_support.ProcessJob()

        if not job.available:

            self.skipTest(
                f"job object unavailable: {job.error}"
            )

        assigned = self._sleep_child()
        other = self._sleep_child()

        try:

            self.assertTrue(job.assign(assigned))

            job.close()

            self.assertTrue(
                self._wait_for_exit(assigned),
                "assigned child survived job close",
            )

            # A child that was never assigned must keep running.
            self.assertIsNone(other.poll())

        finally:

            if assigned.poll() is None:

                assigned.kill()

            other.kill()

            for child in (assigned, other):

                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    pass

            job.close()

    def test_assign_after_close_returns_false(self):

        job = win32_support.ProcessJob()

        if not job.available:

            self.skipTest(
                f"job object unavailable: {job.error}"
            )

        job.close()

        child = self._sleep_child()

        try:

            self.assertFalse(job.assign(child))

        finally:

            child.kill()
            child.wait(timeout=5)

    def test_assign_rejects_a_dead_process(self):

        job = win32_support.ProcessJob()

        if not job.available:

            self.skipTest(
                f"job object unavailable: {job.error}"
            )

        child = self._sleep_child()
        child.kill()
        child.wait(timeout=5)

        try:

            self.assertFalse(job.assign(child))

        finally:

            job.close()


if __name__ == "__main__":
    unittest.main()
