"""Extensible tool integrations wrapping powerful external Reverse Engineering binaries.

All RE tools extend ``DockerBasedTool`` to gain:
  - Image readiness checking and auto-pull capability
  - Binary path pre-resolution with security validation
  - Clean error responses when Docker or the binary is unavailable
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from ai_reo.config import settings
from ai_reo.tools.docker_exec import docker_executor
from ai_reo.tools.interface import DockerBasedTool

logger = logging.getLogger(__name__)


def _resolve_binary_path(session_id: str, filepath: str) -> Dict[str, Any] | Path:
    """Resolve and validate a binary path within the session sandbox.

    Returns:
        Path object if valid, or a dict with an error response.
    """
    sessions_root = Path(settings.tools.sessions_dir).resolve()
    # Support both new workspace/ layout and old binary/ layout for backward compat
    binary_path = (sessions_root / session_id / "workspace" / filepath).resolve()
    if not binary_path.exists():
        legacy = (sessions_root / session_id / "binary" / filepath).resolve()
        if legacy.exists():
            binary_path = legacy

    # Security: prevent path traversal
    if not str(binary_path).startswith(str(sessions_root)):
        return {"error": "SECURITY_VIOLATION", "message": "Path traversal attempt blocked."}

    if not binary_path.exists():
        return {
            "error": "BINARY_NOT_FOUND",
            "message": (
                f"No binary at '{filepath}'. "
                f"Please upload a binary to this session first."
            ),
        }

    return binary_path


class Radare2Tool(DockerBasedTool):
    """radare2 reversing tool utilizing the official Docker image."""

    @property
    def name(self) -> str:
        return "radare2"

    @property
    def docker_image(self) -> str:
        return "radare/radare2"

    @property
    def description(self) -> str:
        return (
            "Execute advanced Radare2 analysis commands on a binary. "
            "Append 'j' to commands (like aflj, pdfj) to get JSON output. "
            "Useful for function discovery, control flow graphs, and disassembly."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "command": {
                    "type": "string",
                    "description": "Radare2 command string (e.g. 'aaa; aflj', 'i', 'pdfj @main')",
                },
            },
            "required": ["filepath", "command"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        cmd = kwargs["command"]

        # Pre-check: binary exists
        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        # Pre-check: Docker image available
        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": (
                    f"Docker image '{self.docker_image}' is not available locally. "
                    f"Please visit the Tools page to set up this tool first."
                ),
            }

        # -q0 disables prompts, -c executes the command string
        full_cmd = f'r2 -q0 -c "{cmd}" /mnt/staging/{session_id}/workspace/{filepath}'
        res = docker_executor.execute(self.docker_image, full_cmd)

        output = res["output"].strip()

        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}

        # Parse r2 JSON output for LLM consumption if valid
        if output.startswith("{") or output.startswith("["):
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                pass

        return {"output": output}


class ObjdumpTool(DockerBasedTool):
    """Objdump GNU binutils wrapper tool using a lightweight custom image."""

    @property
    def name(self) -> str:
        return "objdump"

    @property
    def docker_image(self) -> str:
        # Local image built from docker/Dockerfile.objdump during tool setup.
        return "ai-reo/objdump:latest"

    @property
    def description(self) -> str:
        return "Run GNU objdump to parse ELF/PE headers and quickly disassemble sections."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "options": {
                    "type": "string",
                    "description": "objdump parameters string (e.g. '-d -M intel' for disassembly)",
                },
            },
            "required": ["filepath", "options"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        # Pre-check: binary exists
        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        # Pre-check: tool ready
        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        full_cmd = f"objdump {kwargs['options']} /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, full_cmd)

        return {"exit_code": res["exit_code"], "output": res["output"]}


class ReadelfTool(DockerBasedTool):
    """ELF-focused metadata extractor using GNU readelf."""

    @property
    def name(self) -> str:
        return "readelf"

    @property
    def docker_image(self) -> str:
        return "ai-reo/objdump:latest"

    @property
    def description(self) -> str:
        return "Run GNU readelf for rich ELF metadata (headers, sections, symbols, dynamic entries)."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "options": {
                    "type": "string",
                    "description": "readelf parameters string (e.g. '-h -S -s -d')",
                    "default": "-h -S -s -d",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        options = kwargs.get("options", "-h -S -s -d")

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        full_cmd = f"readelf {options} /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, full_cmd)
        return {"exit_code": res["exit_code"], "output": res["output"]}


class NmTool(DockerBasedTool):
    """Symbol table extractor using GNU nm."""

    @property
    def name(self) -> str:
        return "nm"

    @property
    def docker_image(self) -> str:
        return "ai-reo/objdump:latest"

    @property
    def description(self) -> str:
        return "Run GNU nm to enumerate symbols and linkage metadata from binaries/libraries."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "options": {
                    "type": "string",
                    "description": "nm parameters string (e.g. '-n -C')",
                    "default": "-n -C",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        options = kwargs.get("options", "-n -C")

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        full_cmd = f"nm {options} /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, full_cmd)
        return {"exit_code": res["exit_code"], "output": res["output"]}


class AngrTool(DockerBasedTool):
    """angr-based symbolic and structural analysis helper."""

    @property
    def name(self) -> str:
        return "angr"

    @property
    def docker_image(self) -> str:
        return "ai-reo/angr:latest"

    @property
    def description(self) -> str:
        return (
            "Run angr to extract binary metadata and a quick control-flow/function overview. "
            "Useful for agentic reasoning about program structure before deeper reversing."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        analysis_script = (
            "import json, angr; "
            f"proj = angr.Project('/mnt/staging/{session_id}/workspace/{filepath}', auto_load_libs=False); "
            "cfg = proj.analyses.CFGFast(normalize=True); "
            "funcs = list(cfg.functions.values()); "
            "imports = sorted(list(getattr(proj.loader.main_object, 'imports', {}).keys()))[:100]; "
            "print(json.dumps({"
            "'arch': proj.arch.name, "
            "'entry': hex(proj.entry), "
            "'loader': type(proj.loader.main_object).__name__, "
            "'function_count': len(funcs), "
            "'sample_functions': [{'name': f.name, 'addr': hex(f.addr)} for f in funcs[:50]], "
            "'imports': imports"
            "}))"
        )
        full_cmd = f"python -c \"{analysis_script}\""
        res = docker_executor.execute(self.docker_image, full_cmd, timeout=300)

        output = res["output"].strip()
        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"output": output}


class UpxTool(DockerBasedTool):
    """UPX inspection and unpack helper."""

    @property
    def name(self) -> str:
        return "upx"

    @property
    def docker_image(self) -> str:
        return "ai-reo/upx:latest"

    @property
    def description(self) -> str:
        return (
            "Inspect or unpack UPX-packed binaries. Use mode='test' to detect packing, "
            "or mode='decompress' to unpack into a new file inside the session staging area."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "mode": {
                    "type": "string",
                    "enum": ["test", "decompress"],
                    "default": "test",
                    "description": "Whether to only test for UPX packing or decompress the file.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Relative output path to write decompressed binary to when mode='decompress'.",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        mode = kwargs.get("mode", "test")

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        if mode == "decompress":
            output_path = kwargs.get("output_path") or f"{filepath}.unpacked"
            full_cmd = f"cp /mnt/staging/{session_id}/workspace/{filepath} /mnt/staging/{output_path} && upx -d /mnt/staging/{output_path}"
            res = docker_executor.execute(self.docker_image, full_cmd, timeout=180)
            return {
                "exit_code": res["exit_code"],
                "output": res["output"],
                "output_path": output_path,
            }

        full_cmd = f"upx -t /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, full_cmd, timeout=120)
        return {"exit_code": res["exit_code"], "output": res["output"]}


class CapaTool(DockerBasedTool):
    """Mandiant FLARE capa — detects capabilities in executables mapped to ATT&CK and MBC."""

    @property
    def name(self) -> str:
        return "capa"

    @property
    def docker_image(self) -> str:
        return "ai-reo/capa:latest"

    @property
    def description(self) -> str:
        return (
            "Run Mandiant FLARE capa to identify high-level capabilities in PE/ELF/shellcode "
            "and map them to MITRE ATT&CK and Malware Behavior Catalogue (MBC) techniques. "
            "Ideal first step for malware triage."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        full_cmd = f"capa --json -r /opt/capa-rules /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, full_cmd, timeout=300)

        output = res["output"].strip()
        if res["exit_code"] not in (0, 1):  # capa exits 1 when no capabilities found
            return {"error": output, "exit_code": res["exit_code"]}

        # Try to return parsed JSON for richer agent reasoning
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    # Summarise for token efficiency
                    capabilities = list(data.get("rules", {}).keys())
                    attack = {
                        domain: list(techniques.keys())
                        for domain, techniques in data.get("attack", {}).items()
                    }
                    return {
                        "capabilities": capabilities,
                        "attack_techniques": attack,
                        "meta": data.get("meta", {}),
                        "raw": data,
                    }
                except json.JSONDecodeError:
                    pass

        return {"exit_code": res["exit_code"], "output": output}


class YaraTool(DockerBasedTool):
    """YARA rule engine for binary pattern matching and family classification."""

    @property
    def name(self) -> str:
        return "yara"

    @property
    def docker_image(self) -> str:
        return "ai-reo/yara:latest"

    @property
    def description(self) -> str:
        return (
            "Scan a binary with custom YARA rules to detect patterns, strings, or known malware families. "
            "Provide YARA rule text in the 'rules' parameter."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "rules": {
                    "type": "string",
                    "description": "YARA rule text to compile and run against the binary",
                },
            },
            "required": ["filepath", "rules"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        rules_text = kwargs["rules"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        # Write rules to a temp file inside the shared staging dir so the container can read them
        staging_dir = Path(settings.tools.sessions_dir).expanduser().resolve()
        rules_file = staging_dir / f"yara_rules_{session_id}.yar"
        try:
            rules_file.write_text(rules_text, encoding="utf-8")
            full_cmd = f"yara /mnt/staging/yara_rules_{session_id}.yar /mnt/staging/{session_id}/workspace/{filepath}"
            res = docker_executor.execute(self.docker_image, full_cmd, timeout=60)
            return {"exit_code": res["exit_code"], "output": res["output"]}
        finally:
            rules_file.unlink(missing_ok=True)


class GhidraHeadlessTool(DockerBasedTool):
    """Ghidra headless analyzer wrapper for robust scripted decompilation."""

    @property
    def name(self) -> str:
        return "ghidra_headless"

    @property
    def docker_image(self) -> str:
        return "blacktop/ghidra"

    @property
    def description(self) -> str:
        return (
            "Run Ghidra headless analyzer with a post-analysis script. "
            "Provides automated pseudo-C decompilation of functions. "
            "Higher latency than radare2; use when decompiled source is needed."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary",
                },
                "script_name": {
                    "type": "string",
                    "description": "Ghidra script name in the staging folder (e.g. 'DecompileToJson.py')",
                },
            },
            "required": ["filepath", "script_name"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        script = kwargs["script_name"]

        # Pre-check: binary exists
        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        # Pre-check: tool ready
        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        cmd = (
            f"analyzeHeadless /tmp tmp_project "
            f"-import /mnt/staging/{session_id}/workspace/{filepath} "
            f"-postScript /mnt/staging/{script} "
            f"-deleteProject"
        )
        # Decompilation can take minutes
        res = docker_executor.execute(self.docker_image, cmd, timeout=300)

        return {"exit_code": res["exit_code"], "output": res["output"]}


class DieTool(DockerBasedTool):
    """Detect-It-Easy (DIE) packer/compiler/protector identification tool."""

    @property
    def name(self) -> str:
        return "die"

    @property
    def docker_image(self) -> str:
        return "ai-reo/die:latest"

    @property
    def description(self) -> str:
        return (
            "Run Detect-It-Easy to identify packers, compilers, protectors, and obfuscators "
            "used in a binary. Returns structured JSON with detected signatures and confidence."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        cmd = f"diec --json /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=60)

        output = res["output"].strip()
        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"output": output}


class LiefTool(DockerBasedTool):
    """LIEF-based binary parser for deep PE/ELF/Mach-O structural analysis."""

    @property
    def name(self) -> str:
        return "lief"

    @property
    def docker_image(self) -> str:
        return "ai-reo/lief:latest"

    @property
    def description(self) -> str:
        return (
            "Parse a PE, ELF, or Mach-O binary with LIEF. Returns sections, imports, exports, "
            "TLS callbacks, resources, checksums, and signature information as structured JSON."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "sections_only": {
                    "type": "boolean",
                    "description": "Return only section info (smaller output). Default false.",
                    "default": False,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        sections_only = bool(kwargs.get("sections_only", False))

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        flag = "--sections-only" if sections_only else "--full"
        cmd = f"python3 /app/lief_parse.py {flag} /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=60)

        output = res["output"].strip()
        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"output": output}


class FlossTool(DockerBasedTool):
    """FLOSS — FireEye Labs Obfuscated String Solver for deobfuscated string extraction."""

    @property
    def name(self) -> str:
        return "floss"

    @property
    def docker_image(self) -> str:
        # Local image built from docker/floss/Dockerfile during tool setup.
        return "ai-reo/floss:latest"

    @property
    def description(self) -> str:
        return (
            "Run FLOSS (Mandiant) to extract statically-defined, stack-based, and decoded strings "
            "from a binary — including strings hidden by encoding or obfuscation. "
            "More powerful than plain strings extraction for packed/obfuscated malware."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        cmd = f"floss --json /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=300)

        output = res["output"].strip()
        if res["exit_code"] not in (0, 1):
            return {"error": output, "exit_code": res["exit_code"]}

        try:
            data = json.loads(output)
            return {
                "static_strings": data.get("strings", {}).get("static_strings", [])[:200],
                "stack_strings": data.get("strings", {}).get("stack_strings", [])[:100],
                "decoded_strings": data.get("strings", {}).get("decoded_strings", [])[:100],
                "meta": data.get("metadata", {}),
            }
        except (json.JSONDecodeError, KeyError):
            return {"output": output[:4000]}


class BinwalkTool(DockerBasedTool):
    """Binwalk firmware and archive analysis with entropy + extraction."""

    @property
    def name(self) -> str:
        return "binwalk"

    @property
    def docker_image(self) -> str:
        # Local image built from docker/binwalk/Dockerfile during tool setup.
        return "ai-reo/binwalk:latest"

    @property
    def description(self) -> str:
        return (
            "Run Binwalk to scan a binary for embedded files, compressed archives, and firmware "
            "signatures, plus generate an entropy graph. Ideal for firmware analysis and "
            "detecting embedded files or compression within a binary."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "extract": {
                    "type": "boolean",
                    "description": "If true, attempt to extract embedded files. Default false.",
                    "default": False,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        extract = bool(kwargs.get("extract", False))

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        flags = "-e -M" if extract else ""
        cmd = f"binwalk {flags} /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=120)
        return {"exit_code": res["exit_code"], "output": res["output"][:6000]}


class CheksecTool(DockerBasedTool):
    """Checksec — report binary security mitigations (PIE, NX, canary, RELRO, ASLR)."""

    @property
    def name(self) -> str:
        return "checksec"

    @property
    def docker_image(self) -> str:
        return "ai-reo/checksec:latest"

    @property
    def description(self) -> str:
        return (
            "Check binary security mitigations: PIE (position-independent executable), "
            "NX/DEP (non-executable stack), Stack Canary, RELRO (relocation read-only), "
            "and Fortify Source. Essential for vulnerability research."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        cmd = f"checksec --format=json --file=/mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=30)

        output = res["output"].strip()
        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}

        try:
            data = json.loads(output)
            # checksec.sh wraps results under the binary path as the top-level key;
            # extract the inner dict for a cleaner agent-facing response.
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, dict):
                        return val
            return data
        except json.JSONDecodeError:
            return {"output": output}


class UnipackerTool(DockerBasedTool):
    """Unipacker — emulation-based Windows PE generic unpacker."""

    @property
    def name(self) -> str:
        return "unipacker"

    @property
    def docker_image(self) -> str:
        return "ai-reo/unipacker:latest"

    @property
    def description(self) -> str:
        return (
            "Attempt to unpack a Windows PE binary using Unipacker (emulation-based). "
            "Supports many PE packers (UPX, MPRESS, PEtite, ASPack, etc.). "
            "Writes unpacked binary to the session staging directory."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "output_filename": {
                    "type": "string",
                    "description": "Filename to write the unpacked binary to (default: <name>_unpacked.exe)",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        import os as _os
        filepath = kwargs["filepath"]
        base_name = _os.path.splitext(_os.path.basename(filepath))[0]
        output_filename = kwargs.get("output_filename") or f"{base_name}_unpacked.exe"

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        out_path = f"/mnt/staging/{session_id}/workspace/{output_filename}"
        cmd = f"unipacker -d /mnt/staging/{session_id}/workspace/{filepath} -o {out_path}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=120)
        return {
            "exit_code": res["exit_code"],
            "output": res["output"][:3000],
            "output_file": output_filename,
        }
