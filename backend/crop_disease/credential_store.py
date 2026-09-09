from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


CRYPTPROTECT_UI_FORBIDDEN = 0x1
DEFAULT_CREDENTIAL_PATH = Path(".local") / "deepseek_api_key.bin"


class CredentialStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _require_windows() -> None:
    if os.name != "nt":
        raise CredentialStoreError("本机密钥加密目前仅支持 Windows。")


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    )
    return blob, buffer


def _protect(data: bytes) -> bytes:
    _require_windows()
    source, source_buffer = _blob_from_bytes(data)
    destination = _DataBlob()
    success = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source),
        "Crop Disease DeepSeek API Key",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(destination),
    )
    del source_buffer
    if not success:
        raise CredentialStoreError("无法使用 Windows 账户加密 DeepSeek 密钥。")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def _unprotect(data: bytes) -> bytes:
    _require_windows()
    source, source_buffer = _blob_from_bytes(data)
    destination = _DataBlob()
    success = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(destination),
    )
    del source_buffer
    if not success:
        raise CredentialStoreError("无法解密已保存的 DeepSeek 密钥，请重新设置。")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def save_api_key(api_key: str, path: Path) -> None:
    key = api_key.strip()
    if not key:
        raise CredentialStoreError("不能保存空的 DeepSeek 密钥。")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_protect(key.encode("utf-8")))
    temporary.replace(path)


def load_api_key(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return _unprotect(path.read_bytes()).decode("utf-8").strip() or None
    except (OSError, UnicodeDecodeError) as error:
        raise CredentialStoreError("读取已保存的 DeepSeek 密钥失败，请重新设置。") from error


def delete_api_key(path: Path) -> None:
    path.unlink(missing_ok=True)
