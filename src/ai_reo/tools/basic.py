"""Basic utility tools (File system readers/writers, command execution)."""

import os
from pathlib import Path
from typing import Any, Dict

from ai_reo.config import settings
from ai_reo.tools.interface import BaseTool


def _get_safe_path(requested_path: str) -> Path:
    """Strictly resolve a path making sure it doesn't escape the binary staging directory."""
    base = Path(settings.tools.sessions_dir).resolve()
    # Explicitly ensure the trailing slash behavior to anchor root properly
    target = (base / requested_path).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path traversal detected. Agent tried to escape sandbox via: {requested_path}")
    return target


class FsReadTool(BaseTool):
    @property
    def name(self) -> str:
        return "fs_read"

    @property
    def description(self) -> str:
        return "Read the textual content of a file from the sandboxed binary staging directory."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename or path within the staging directory"
                }
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        try:
            path = _get_safe_path(kwargs["filepath"])
            if not path.is_file():
                return {"error": f"File not found: {kwargs['filepath']}"}
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return {"error": str(e)}


class FsWriteTool(BaseTool):
    @property
    def name(self) -> str:
        return "fs_write"

    @property
    def description(self) -> str:
        return "Write text content to a file in the sandboxed staging directory. Useful for YARA rules or python scripts."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The raw string content to write"
                }
            },
            "required": ["filepath", "content"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        try:
            path = _get_safe_path(kwargs["filepath"])
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(kwargs["content"])
            return {"status": "success", "filepath": str(path.relative_to(Path(settings.tools.sessions_dir).resolve()))}
        except Exception as e:
            return {"error": str(e)}


class StringsExtractTool(BaseTool):
    """Extract printable ASCII/UTF-16 strings from a binary file. No Docker needed."""

    @property
    def name(self) -> str:
        return "strings_extract"

    @property
    def description(self) -> str:
        return (
            "Extract printable ASCII and UTF-16 strings from a binary file. "
            "Works without Docker. Use this as the first step when Docker tools are unavailable. "
            "Args: filepath (relative path inside session binary dir), min_length (int, default 4)."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename inside the session binary directory",
                },
                "min_length": {
                    "type": "integer",
                    "description": "Minimum string length to include (default 4)",
                    "default": 4,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        min_len = int(kwargs.get("min_length", 4))

        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = (sessions_root / session_id / "binary" / filepath).resolve()

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'. Upload a binary first."}

        strings_found: list[str] = []
        try:
            data = binary_path.read_bytes()
        except Exception as e:
            return {"error": str(e)}

        # ASCII strings
        current: list[str] = []
        for byte in data:
            if 0x20 <= byte <= 0x7E:
                current.append(chr(byte))
            else:
                if len(current) >= min_len:
                    strings_found.append("".join(current))
                current = []
        if len(current) >= min_len:
            strings_found.append("".join(current))

        # UTF-16LE strings
        try:
            i = 0
            current_utf: list[str] = []
            while i + 1 < len(data):
                char_code = data[i] | (data[i + 1] << 8)
                if 0x20 <= char_code <= 0x7E:
                    current_utf.append(chr(char_code))
                else:
                    if len(current_utf) >= min_len:
                        s = "".join(current_utf)
                        if s not in strings_found:
                            strings_found.append(s)
                    current_utf = []
                i += 2
        except Exception:
            pass

        unique = list(dict.fromkeys(strings_found))
        return {
            "total": len(unique),
            "strings": unique[:300],
            "truncated": len(unique) > 300,
            "note": f"Extracted {len(unique)} unique printable strings (showing first 300)",
        }


class BinaryInfoTool(BaseTool):
    """Get basic information about a binary file: size, SHA256, magic bytes. No Docker needed."""

    @property
    def name(self) -> str:
        return "binary_info"

    @property
    def description(self) -> str:
        return (
            "Get basic information about a binary file: size, SHA256 hash, magic bytes, "
            "and a best-guess at the file type from the header. No Docker required."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename inside the session binary directory",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        import hashlib

        filepath = kwargs["filepath"]
        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = (sessions_root / session_id / "binary" / filepath).resolve()

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'. Upload a binary first."}

        try:
            data = binary_path.read_bytes()
        except Exception as e:
            return {"error": str(e)}

        sha256 = hashlib.sha256(data).hexdigest()
        magic = data[:16].hex()
        size = len(data)

        # Basic format detection
        fmt = "unknown"
        if data[:2] == b"MZ":
            fmt = "PE (Windows Executable)"
        elif data[:4] == b"\x7fELF":
            arch_byte = data[4] if len(data) > 4 else 0
            fmt = f"ELF ({'64-bit' if arch_byte == 2 else '32-bit'} Linux/Unix)"
        elif data[:4] in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
            fmt = "Mach-O (macOS/iOS)"
        elif data[:2] == b"PK":
            fmt = "ZIP / JAR / APK archive"
        elif data[:7] == b"!<arch>":
            fmt = "Unix .a static library"

        return {
            "filepath": filepath,
            "size_bytes": size,
            "size_kb": round(size / 1024, 2),
            "sha256": sha256,
            "magic_hex": magic,
            "format": fmt,
        }
