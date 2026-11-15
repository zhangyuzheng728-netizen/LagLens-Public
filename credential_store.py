"""Windows Credential Manager storage for the DeepSeek API key.

The key is never written to INI, logs, reports, exports or the package.
Only a generic credential under the current Windows user is used.
"""

from __future__ import annotations

import ctypes
import os

from ctypes import wintypes


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
CREDENTIAL_TARGET = "LagLens/DeepSeekApiKey"


class CredentialError(Exception):
    """Credential Manager operation failed."""

    def __init__(self, code, detail=""):
        self.code = int(code or 0)
        self.detail = detail
        super().__init__(f"credential error {self.code}")


class _Credential(ctypes.Structure):

    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIAL = ctypes.POINTER(_Credential)

if os.name == "nt":

    _advapi32 = ctypes.WinDLL(
        "advapi32",
        use_last_error=True,
    )
    _advapi32.CredWriteW.argtypes = [
        _PCREDENTIAL,
        wintypes.DWORD,
    ]
    _advapi32.CredWriteW.restype = wintypes.BOOL
    _advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_PCREDENTIAL),
    ]
    _advapi32.CredReadW.restype = wintypes.BOOL
    _advapi32.CredDeleteW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _advapi32.CredDeleteW.restype = wintypes.BOOL
    _advapi32.CredFree.argtypes = [_PCREDENTIAL]
    _advapi32.CredFree.restype = None

else:  # pragma: no cover - LagLens is Windows-only

    _advapi32 = None


def _require_windows():
    if _advapi32 is None:
        raise CredentialError(0, "Windows Credential Manager unavailable")


def save_secret(secret, target=CREDENTIAL_TARGET):
    _require_windows()
    secret = str(secret or "")

    if not secret:
        raise CredentialError(0, "empty secret")

    blob = secret.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob)
    credential = _Credential()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(
        buffer,
        ctypes.POINTER(ctypes.c_ubyte),
    )
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = os.environ.get("USERNAME", "")

    if not _advapi32.CredWriteW(
        ctypes.byref(credential),
        0,
    ):
        raise CredentialError(
            ctypes.get_last_error(),
            "CredWriteW",
        )


def read_secret(target=CREDENTIAL_TARGET):
    _require_windows()
    pointer = _PCREDENTIAL()

    if not _advapi32.CredReadW(
        target,
        CRED_TYPE_GENERIC,
        0,
        ctypes.byref(pointer),
    ):
        code = ctypes.get_last_error()

        if code == ERROR_NOT_FOUND:
            return None

        raise CredentialError(code, "CredReadW")

    try:
        credential = pointer.contents
        size = int(credential.CredentialBlobSize)

        if size <= 0:
            return ""

        raw = ctypes.string_at(
            credential.CredentialBlob,
            size,
        )
        return raw.decode("utf-16-le", "replace")

    finally:
        _advapi32.CredFree(pointer)


def delete_secret(target=CREDENTIAL_TARGET):
    _require_windows()

    if _advapi32.CredDeleteW(
        target,
        CRED_TYPE_GENERIC,
        0,
    ):
        return True

    code = ctypes.get_last_error()

    if code == ERROR_NOT_FOUND:
        return False

    raise CredentialError(code, "CredDeleteW")


def has_secret(target=CREDENTIAL_TARGET):
    try:
        return bool(read_secret(target))
    except CredentialError:
        return False
