from __future__ import annotations

import base64
import ctypes
import os
import tempfile
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
_DPAPI_PREFIX = "dpapi-v1:"
_PLAIN_PREFIX = "plain-v1:"


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


def _uses_windows_dpapi() -> bool:
    return os.name == "nt"


def _encode_plain_secret(secret: str) -> str:
    return base64.b64encode(secret.encode("utf-8")).decode("ascii")


def _decode_plain_secret(payload: str) -> str:
    try:
        encoded = payload.encode("ascii")
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise SecretStoreError("Invalid plaintext secret payload.") from exc


def _serialize_secret(secret: str) -> str:
    if _uses_windows_dpapi():
        return _DPAPI_PREFIX + protect_secret(secret)
    return _PLAIN_PREFIX + _encode_plain_secret(secret)


def _current_backend_prefix() -> str:
    return _DPAPI_PREFIX if _uses_windows_dpapi() else _PLAIN_PREFIX


def _deserialize_secret(payload: str) -> str:
    if payload.startswith(_DPAPI_PREFIX):
        return unprotect_secret(payload[len(_DPAPI_PREFIX) :])
    if payload.startswith(_PLAIN_PREFIX):
        return _decode_plain_secret(payload[len(_PLAIN_PREFIX) :])
    if _uses_windows_dpapi():
        # Versions before the versioned format stored the raw DPAPI Base64 payload.
        return unprotect_secret(payload)
    raise SecretStoreError("Unknown secret payload format.")


def _secure_posix_permissions(path: Path, mode: int) -> None:
    if not _uses_windows_dpapi():
        path.chmod(mode)


def load_api_key(path: str | Path) -> str:
    try:
        payload = Path(path).read_text(encoding="ascii").strip()
        return _deserialize_secret(payload) if payload else ""
    except (OSError, SecretStoreError, UnicodeError):
        return ""


def resolve_api_key(path: str | Path, *, remembered: bool) -> str:
    environment_key = os.environ.get("UMA_MOE_API_KEY", "")
    if environment_key:
        return environment_key
    return load_api_key(path) if remembered else ""


def save_api_key(path: str | Path, secret: str) -> None:
    destination = Path(path)
    if not secret:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        return

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _secure_posix_permissions(destination.parent, 0o700)
    if destination.is_file() and load_api_key(destination) == secret:
        try:
            current_payload = destination.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            current_payload = ""
        if current_payload.startswith(_current_backend_prefix()):
            _secure_posix_permissions(destination, 0o600)
            return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        # mkstemp already creates a user-private file.  Apply the explicit
        # POSIX mode through the path as well so the plaintext backend remains
        # testable on Windows, where os.fchmod is not available.
        _secure_posix_permissions(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii", newline="") as handle:
            descriptor = -1
            handle.write(_serialize_secret(secret))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _secure_posix_permissions(destination, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
