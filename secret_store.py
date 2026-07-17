from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class SecretStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


_DESCRIPTION = "Uma Legacy Linker uma.moe API key"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return (
        _DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
        ),
        buffer,
    )


def _windows_crypt(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise SecretStoreError("Windows DPAPI is unavailable on this platform.")

    input_blob, input_buffer = _blob(data)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData

    if protect:
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        result = function(
            ctypes.byref(input_blob),
            _DESCRIPTION,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    else:
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        result = function(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )

    # Keep the input buffer alive until the Windows call has completed.
    del input_buffer
    if not result:
        raise SecretStoreError(f"Windows DPAPI error {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)


def protect_secret(secret: str) -> str:
    encrypted = _windows_crypt(secret.encode("utf-8"), protect=True)
    return base64.b64encode(encrypted).decode("ascii")


def unprotect_secret(payload: str) -> str:
    try:
        encrypted = base64.b64decode(payload.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise SecretStoreError("Invalid protected secret payload.") from exc
    try:
        return _windows_crypt(encrypted, protect=False).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretStoreError("Invalid protected secret text.") from exc


def load_api_key(path: str | Path) -> str:
    try:
        payload = Path(path).read_text(encoding="ascii").strip()
        return unprotect_secret(payload) if payload else ""
    except (OSError, SecretStoreError):
        return ""


def save_api_key(path: str | Path, secret: str) -> None:
    destination = Path(path)
    if not secret:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        return

    if destination.is_file() and load_api_key(destination) == secret:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_text(protect_secret(secret), encoding="ascii")
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
