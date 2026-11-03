"""Password protection using Windows DPAPI (per-user, no extra dependencies).

The saved FTP password can only be decrypted by the same Windows user account on
the same machine, which fits the "run with existing user privileges" requirement
without ever writing a plain-text password to disk.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free(blob: _DATA_BLOB) -> None:
    try:
        ctypes.windll.kernel32.LocalFree(blob.pbData)
    except Exception:
        pass


def protect(text: str) -> str:
    """Encrypt a string for the current Windows user. Returns base64 or ''."""
    if not text:
        return ""
    try:
        data_in = _blob(text.encode("utf-8"))
        data_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(data_in), "FtpSync", None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
        if not ok:
            return ""
        try:
            return "dpapi:" + base64.b64encode(_blob_bytes(data_out)).decode("ascii")
        finally:
            _free(data_out)
    except Exception:
        return ""


def unprotect(token: str) -> str:
    """Decrypt a value produced by :func:`protect` (or a legacy plain value)."""
    if not token:
        return ""
    if not token.startswith("dpapi:"):
        return token  # legacy / plain text
    try:
        raw = base64.b64decode(token[6:])
        data_in = _blob(raw)
        data_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
        if not ok:
            return ""
        try:
            return _blob_bytes(data_out).decode("utf-8")
        finally:
            _free(data_out)
    except Exception:
        return ""
