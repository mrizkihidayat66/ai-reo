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


def _resolve_session_binary(session_id: str, filepath: str) -> Path:
    """Resolve a binary path within a session's workspace, with fallback to legacy binary/ dir."""
    sessions_root = Path(settings.tools.sessions_dir).resolve()
    # New layout: workspace/
    candidate = (sessions_root / session_id / "workspace" / filepath).resolve()
    if not str(candidate).startswith(str(sessions_root)):
        raise ValueError("Path traversal blocked.")
    if candidate.exists():
        return candidate
    # Legacy layout: binary/
    legacy = (sessions_root / session_id / "binary" / filepath).resolve()
    if legacy.exists():
        return legacy
    # Return the new-layout path even if it doesn't exist (so callers see the right BINARY_NOT_FOUND message)
    return candidate


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
        return (
            "Write a TEMPORARY file into THIS session's working directory. "
            "Only use this for temporary intermediate files (e.g. decompressed output, extracted data). "
            "The file is stored under sessions/<session_id>/<filepath> — it is session-local and "
            "does NOT persist across sessions. "
            "For reusable YARA rules, Python helpers, or analysis scripts, ALWAYS use scripts_write instead."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename within this session's working directory (e.g. 'output.txt' or 'extracted/payload.bin')"
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
            # Always scope writes to this session's subdirectory (security + correctness)
            scoped = f"{session_id}/{kwargs['filepath']}"
            path = _get_safe_path(scoped)
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
        binary_path = _resolve_session_binary(session_id, filepath)

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
        binary_path = _resolve_session_binary(session_id, filepath)

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


class EntropyAnalysisTool(BaseTool):
    """Compute Shannon entropy for the whole file and per 256-byte blocks."""

    @property
    def name(self) -> str:
        return "entropy_analysis"

    @property
    def description(self) -> str:
        return (
            "Compute Shannon entropy for a binary file overall and in 256-byte blocks. "
            "High entropy (>7.0) suggests compression or encryption; packed sections show "
            "sharp spikes. No Docker required."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename inside the session binary directory",
                },
                "block_size": {
                    "type": "integer",
                    "description": "Bytes per entropy block (default 256)",
                    "default": 256,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        import math

        filepath = kwargs["filepath"]
        block_size = max(64, int(kwargs.get("block_size", 256)))
        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = _resolve_session_binary(session_id, filepath)

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'."}

        try:
            data = binary_path.read_bytes()
        except Exception as e:
            return {"error": str(e)}

        def shannon(buf: bytes) -> float:
            if not buf:
                return 0.0
            freq = [0] * 256
            for b in buf:
                freq[b] += 1
            n = len(buf)
            return -sum((c / n) * math.log2(c / n) for c in freq if c)

        overall = round(shannon(data), 4)
        blocks = []
        for i in range(0, len(data), block_size):
            chunk = data[i: i + block_size]
            blocks.append({"offset": i, "entropy": round(shannon(chunk), 3)})

        high_blocks = [b for b in blocks if b["entropy"] > 7.0]
        return {
            "filepath": filepath,
            "overall_entropy": overall,
            "interpretation": (
                "likely packed/encrypted" if overall > 7.0
                else "possibly compressed" if overall > 6.0
                else "normal executable"
            ),
            "block_size": block_size,
            "high_entropy_blocks": high_blocks[:20],
            "total_high_entropy_blocks": len(high_blocks),
        }


class HexDumpTool(BaseTool):
    """Return a hex+ASCII dump of an arbitrary offset and length."""

    @property
    def name(self) -> str:
        return "hex_dump"

    @property
    def description(self) -> str:
        return (
            "Return a formatted hex+ASCII dump of a binary region. "
            "Useful for inspecting headers, strings, or suspicious byte sequences. No Docker required."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename inside the session binary directory",
                },
                "offset": {
                    "type": "integer",
                    "description": "File offset to start reading from (default 0)",
                    "default": 0,
                },
                "length": {
                    "type": "integer",
                    "description": "Number of bytes to read (default 256, max 4096)",
                    "default": 256,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        offset = max(0, int(kwargs.get("offset", 0)))
        length = min(4096, max(1, int(kwargs.get("length", 256))))

        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = _resolve_session_binary(session_id, filepath)

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'."}

        try:
            with open(binary_path, "rb") as f:
                f.seek(offset)
                data = f.read(length)
        except Exception as e:
            return {"error": str(e)}

        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i: i + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
            lines.append(f"{offset + i:08x}  {hex_part:<47}  |{ascii_part}|")

        return {
            "filepath": filepath,
            "offset": offset,
            "length": len(data),
            "hex_dump": "\n".join(lines),
        }


class FileTypeTool(BaseTool):
    """Identify file format from magic bytes — no Docker, no libmagic dependency."""

    @property
    def name(self) -> str:
        return "file_type"

    @property
    def description(self) -> str:
        return (
            "Identify the format of a binary file from its magic bytes and internal structure. "
            "Returns a detailed label (PE32/PE64, ELF, Mach-O, ZIP, PDF, …). No Docker required."
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
        filepath = kwargs["filepath"]
        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = _resolve_session_binary(session_id, filepath)

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'."}

        try:
            with open(binary_path, "rb") as f:
                header = f.read(64)
            size = binary_path.stat().st_size
        except Exception as e:
            return {"error": str(e)}

        file_type = "Unknown"
        details: dict[str, Any] = {}

        if header[:2] == b"MZ":
            # Parse PE offset
            try:
                pe_offset = int.from_bytes(header[0x3C:0x40], "little")
                with open(binary_path, "rb") as f:
                    f.seek(pe_offset)
                    sig = f.read(4)
                if sig == b"PE\x00\x00":
                    with open(binary_path, "rb") as f:
                        f.seek(pe_offset + 4 + 16)
                        magic = int.from_bytes(f.read(2), "little")
                    arch = {0x10B: "PE32", 0x20B: "PE64 (PE32+)"}.get(magic, "PE (unknown arch)")
                    file_type = arch
                    details["pe_offset"] = hex(pe_offset)
                else:
                    file_type = "MZ executable (no PE signature)"
            except Exception:
                file_type = "MZ executable"
        elif header[:4] == b"\x7fELF":
            bits = {1: "32-bit", 2: "64-bit"}.get(header[4], "?-bit")
            endian = {1: "little-endian", 2: "big-endian"}.get(header[5], "?-endian")
            etype = int.from_bytes(header[16:18], "little" if header[5] == 1 else "big")
            etype_label = {1: "relocatable", 2: "executable", 3: "shared object", 4: "core"}.get(etype, f"type={etype}")
            file_type = f"ELF {bits} {endian} {etype_label}"
        elif header[:4] in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe"):
            file_type = "Mach-O 32-bit"
        elif header[:4] in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
            file_type = "Mach-O 64-bit"
        elif header[:4] == b"\xca\xfe\xba\xbe":
            file_type = "Mach-O Universal Binary (FAT)"
        elif header[:2] == b"PK":
            file_type = "ZIP archive (or JAR/APK/DOCX/XLSX)"
        elif header[:4] == b"%PDF":
            file_type = "PDF document"
        elif header[:7] == b"!<arch>":
            file_type = "Unix .a static library"
        elif header[:2] == b"\x1f\x8b":
            file_type = "gzip compressed data"
        elif header[:6] in (b"\xfd7zXZ\x00",):
            file_type = "XZ compressed data"
        elif header[:4] == b"7z\xbc\xaf":
            file_type = "7-Zip archive"
        elif header[:4] == b"Rar!":
            file_type = "RAR archive"
        elif header[:4] == b"\xd0\xcf\x11\xe0":
            file_type = "Microsoft OLE2 Compound Document (Office/MSI)"
        elif header[:4] == b"\x4d\x5a\x90\x00":
            file_type = "MS-DOS/PE executable (MZ)"

        return {
            "filepath": filepath,
            "file_type": file_type,
            "size_bytes": size,
            "magic_hex": header[:8].hex(),
            "details": details,
        }


def _get_scripts_path(filename: str) -> Path:
    """Resolve a path safely within the persistent scripts directory."""
    base = Path(settings.tools.scripts_dir).expanduser().resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path traversal detected: {filename}")
    # Block nested subdirectories for simplicity
    if target.parent != base:
        raise ValueError(f"Subdirectories not allowed in scripts dir: {filename}")
    return target


class SharedWriteTool(BaseTool):
    """Write a reusable script to the persistent shared scripts directory."""

    @property
    def name(self) -> str:
        return "scripts_write"

    @property
    def description(self) -> str:
        return (
            "Save a reusable script (Python, YARA, bash, etc.) to the persistent shared scripts "
            "directory. Scripts saved here persist across sessions and can be re-used with "
            "scripts_list + fs_read. Use this instead of fs_write when the artifact has value "
            "beyond the current session."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Script filename, e.g. 'detect_upx.yar' or 'parse_imports.py'",
                },
                "content": {
                    "type": "string",
                    "description": "The full text content of the script to save",
                },
            },
            "required": ["filename", "content"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        try:
            path = _get_scripts_path(kwargs["filename"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(kwargs["content"], encoding="utf-8")
            return {"status": "saved", "filename": kwargs["filename"], "bytes": len(kwargs["content"])}
        except Exception as e:
            return {"error": str(e)}


class SharedListTool(BaseTool):
    """List all scripts in the persistent shared scripts directory."""

    @property
    def name(self) -> str:
        return "scripts_list"

    @property
    def description(self) -> str:
        return (
            "List all scripts saved in the shared persistent scripts directory. "
            "Returns filename, size, and last-modified timestamp for each file."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        import datetime
        try:
            base = Path(settings.tools.scripts_dir).expanduser().resolve()
            base.mkdir(parents=True, exist_ok=True)
            scripts = []
            for f in sorted(base.iterdir()):
                if f.is_file():
                    stat = f.stat()
                    scripts.append({
                        "filename": f.name,
                        "size_bytes": stat.st_size,
                        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
            return {"count": len(scripts), "scripts": scripts}
        except Exception as e:
            return {"error": str(e)}


class BintropTool(BaseTool):
    """Entropy-based packer probability using bintropy. No Docker needed."""

    @property
    def name(self) -> str:
        return "bintropy"

    @property
    def description(self) -> str:
        return (
            "Compute Shannon entropy statistics for a binary using bintropy. "
            "Returns per-section entropy and an overall packer probability score. "
            "High entropy (>7.0) strongly suggests packing or encryption. No Docker required."
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
        filepath = kwargs["filepath"]
        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = _resolve_session_binary(session_id, filepath)

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'."}

        try:
            import bintropy
            results = bintropy.bintropy(str(binary_path), mode="full")
            return {
                "filepath": filepath,
                "average_entropy": results.get("average_entropy"),
                "highest_entropy": results.get("highest_entropy"),
                "packed_probability": results.get("packed_probability"),
                "sections": results.get("sections", []),
            }
        except ImportError:
            # bintropy not installed: fall back to manual computation
            data = binary_path.read_bytes()
            import math
            from collections import Counter
            counts = Counter(data)
            total = len(data)
            entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
            likely_packed = entropy > 6.8
            return {
                "filepath": filepath,
                "average_entropy": round(entropy, 4),
                "likely_packed": likely_packed,
                "note": "bintropy not installed; computed whole-file Shannon entropy as fallback",
            }
        except Exception as e:
            return {"error": str(e)}


class PEFileTool(BaseTool):
    """Structured PE header, imports, exports, and sections via pefile. No Docker needed."""

    @property
    def name(self) -> str:
        return "pefile"

    @property
    def description(self) -> str:
        return (
            "Parse a Windows PE binary with pefile. Returns machine type, linker version, "
            "imported DLLs and functions, exported symbols, section names/entropy/flags, "
            "and DOS/NT header fields. No Docker required."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative filename inside the session binary directory",
                },
                "mode": {
                    "type": "string",
                    "enum": ["summary", "imports", "exports", "sections", "full"],
                    "default": "summary",
                    "description": "What to return: summary (default), imports, exports, sections, or full.",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        mode = kwargs.get("mode", "summary")
        sessions_root = Path(settings.tools.sessions_dir).resolve()
        binary_path = _resolve_session_binary(session_id, filepath)

        if not str(binary_path).startswith(str(sessions_root)):
            return {"error": "SECURITY_VIOLATION", "message": "Path traversal blocked."}
        if not binary_path.exists():
            return {"error": "BINARY_NOT_FOUND", "message": f"No binary at '{filepath}'."}

        try:
            import pefile
        except ImportError:
            return {"error": "pefile not installed", "hint": "Run: pip install pefile"}

        try:
            import math
            from collections import Counter

            pe = pefile.PE(str(binary_path))

            def _section_entropy(data: bytes) -> float:
                if not data:
                    return 0.0
                counts = Counter(data)
                total = len(data)
                return -sum((c / total) * math.log2(c / total) for c in counts.values())

            sections = []
            for s in pe.sections:
                name = s.Name.rstrip(b"\x00").decode("ascii", errors="replace")
                data = s.get_data()
                sections.append({
                    "name": name,
                    "virtual_address": hex(s.VirtualAddress),
                    "virtual_size": s.Misc_VirtualSize,
                    "raw_size": s.SizeOfRawData,
                    "entropy": round(_section_entropy(data), 4),
                    "characteristics": hex(s.Characteristics),
                })

            imports: list[dict] = []
            if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
                for entry in pe.DIRECTORY_ENTRY_IMPORT:
                    dll = entry.dll.decode("ascii", errors="replace")
                    funcs = []
                    for imp in entry.imports:
                        name_str = imp.name.decode("ascii", errors="replace") if imp.name else f"ord_{imp.ordinal}"
                        funcs.append(name_str)
                    imports.append({"dll": dll, "functions": funcs})

            exports: list[str] = []
            if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
                for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                    if exp.name:
                        exports.append(exp.name.decode("ascii", errors="replace"))

            machine_map = {
                0x14C: "i386", 0x8664: "x86_64", 0x1C0: "ARM", 0xAA64: "ARM64",
            }
            machine = machine_map.get(pe.FILE_HEADER.Machine, hex(pe.FILE_HEADER.Machine))

            summary = {
                "machine": machine,
                "timestamp": pe.FILE_HEADER.TimeDateStamp,
                "entry_point": hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint),
                "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
                "subsystem": pe.OPTIONAL_HEADER.Subsystem,
                "dll_characteristics": hex(pe.OPTIONAL_HEADER.DllCharacteristics),
                "section_count": len(sections),
                "import_dll_count": len(imports),
                "export_count": len(exports),
            }

            pe.close()

            if mode == "summary":
                return summary
            elif mode == "imports":
                return {"imports": imports}
            elif mode == "exports":
                return {"exports": exports}
            elif mode == "sections":
                return {"sections": sections}
            else:  # full
                return {**summary, "sections": sections, "imports": imports, "exports": exports}

        except pefile.PEFormatError as e:
            return {"error": "NOT_A_PE", "message": str(e)}
        except Exception as e:
            return {"error": str(e)}
