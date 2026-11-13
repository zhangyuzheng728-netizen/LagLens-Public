"""Windows-only helpers used by LagLens.

Kept free of Qt so they can be unit-tested directly.
"""

from __future__ import annotations

import os


ERROR_ALREADY_EXISTS = 183

DEFAULT_MUTEX_NAME = r"Local\LagLens.SingleInstance"

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


def _job_structs():
    """Build the Job Object ctypes structures lazily."""

    import ctypes

    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):

        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):

        _fields_ = [
            (
                "PerProcessUserTimeLimit",
                ctypes.c_longlong,
            ),
            (
                "PerJobUserTimeLimit",
                ctypes.c_longlong,
            ),
            ("LimitFlags", wintypes.DWORD),
            (
                "MinimumWorkingSetSize",
                ctypes.c_size_t,
            ),
            (
                "MaximumWorkingSetSize",
                ctypes.c_size_t,
            ),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(
        ctypes.Structure
    ):

        _fields_ = [
            (
                "BasicLimitInformation",
                JOBOBJECT_BASIC_LIMIT_INFORMATION,
            ),
            ("IoInfo", IO_COUNTERS),
            (
                "ProcessMemoryLimit",
                ctypes.c_size_t,
            ),
            ("JobMemoryLimit", ctypes.c_size_t),
            (
                "PeakProcessMemoryUsed",
                ctypes.c_size_t,
            ),
            (
                "PeakJobMemoryUsed",
                ctypes.c_size_t,
            ),
        ]

    return JOBOBJECT_EXTENDED_LIMIT_INFORMATION


class ProcessJob:
    """Job object that kills its children when the handle closes.

    Used to guarantee that PresentMon cannot outlive LagLens, even if
    LagLens crashes.  Only processes explicitly assigned are affected;
    other PresentMon instances and games are never touched.

    Creation failures degrade to a no-op; ``error`` records the reason
    so the caller can log it.
    """

    def __init__(self):

        self._handle = None
        self._kernel32 = None
        self.error = ""

        if os.name != "nt":

            self.error = "not Windows"
            return

        try:

            import ctypes

            from ctypes import wintypes

            kernel32 = ctypes.WinDLL(
                "kernel32",
                use_last_error=True,
            )

            kernel32.CreateJobObjectW.restype = (
                wintypes.HANDLE
            )
            kernel32.CreateJobObjectW.argtypes = [
                wintypes.LPVOID,
                wintypes.LPCWSTR,
            ]

            kernel32.SetInformationJobObject.restype = (
                wintypes.BOOL
            )
            kernel32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]

            kernel32.AssignProcessToJobObject.restype = (
                wintypes.BOOL
            )
            kernel32.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]

            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]

            kernel32.CloseHandle.argtypes = [
                wintypes.HANDLE
            ]

            handle = kernel32.CreateJobObjectW(
                None,
                None,
            )

            if not handle:

                raise OSError(
                    ctypes.get_last_error(),
                    "CreateJobObjectW failed",
                )

            info = _job_structs()()

            info.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )

            if not kernel32.SetInformationJobObject(
                handle,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):

                code = ctypes.get_last_error()

                kernel32.CloseHandle(handle)

                raise OSError(
                    code,
                    "SetInformationJobObject failed",
                )

            self._handle = handle
            self._kernel32 = kernel32

        except (AttributeError, OSError, ValueError) as error:

            self._handle = None
            self._kernel32 = None
            self.error = str(error)

    @property
    def available(self):

        return self._handle is not None

    def assign(self, process):
        """Assign a Popen child to the job.

        Returns False when the job is unavailable or the process already
        exited (a small race after Popen is unavoidable without
        CREATE_SUSPENDED; PresentMon exits immediately on errors such as
        access denied).
        """

        if self._handle is None or self._kernel32 is None:

            return False

        pid = getattr(process, "pid", None)

        if not pid:

            return False

        handle = None

        try:

            handle = self._kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_TERMINATE,
                False,
                int(pid),
            )

            if not handle:

                return False

            return bool(
                self._kernel32.AssignProcessToJobObject(
                    self._handle,
                    handle,
                )
            )

        except (AttributeError, OSError, ValueError):

            return False

        finally:

            if handle:

                try:

                    self._kernel32.CloseHandle(handle)

                except OSError:

                    pass

    def close(self):
        """Close the handle; the OS terminates assigned children."""

        handle = self._handle
        self._handle = None

        if handle is None or self._kernel32 is None:

            return

        try:

            self._kernel32.CloseHandle(handle)

        except OSError:

            pass


class SingleInstanceGuard:
    """Named-mutex guard that detects another running LagLens.

    LagLens holds the mutex for its whole lifetime.  A new instance
    uses ``already_running`` to decide whether startup cleanup of the
    LagLens ETW session is safe: if another instance exists, it may be
    capturing right now, so the session must not be touched.
    """

    def __init__(self, name: str = DEFAULT_MUTEX_NAME):

        self.name = name
        self.already_running = False
        self._handle = None

        if os.name != "nt":

            return

        try:

            import ctypes

            from ctypes import wintypes

            kernel32 = ctypes.WinDLL(
                "kernel32",
                use_last_error=True,
            )

            kernel32.CreateMutexW.argtypes = [
                wintypes.LPVOID,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]

            kernel32.CreateMutexW.restype = (
                wintypes.HANDLE
            )

            handle = kernel32.CreateMutexW(
                None,
                False,
                name,
            )

            if not handle:

                return

            self._handle = handle

            self.already_running = (
                ctypes.get_last_error()
                == ERROR_ALREADY_EXISTS
            )

        except (AttributeError, OSError, ValueError):

            # Never break startup because the guard could not be
            # created; without it we simply skip cleanup.
            self._handle = None

    def close(self):
        """Release the mutex handle (safe to call repeatedly)."""

        handle = self._handle
        self._handle = None

        if handle is None or os.name != "nt":

            return

        try:

            import ctypes

            from ctypes import wintypes

            kernel32 = ctypes.WinDLL(
                "kernel32",
                use_last_error=True,
            )

            kernel32.CloseHandle.argtypes = [
                wintypes.HANDLE
            ]

            kernel32.CloseHandle(handle)

        except (AttributeError, OSError, ValueError):

            pass
