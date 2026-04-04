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
from ai_reo.tools.interface import BaseTool, DockerBasedTool

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


def _get_safe_output_path(session_id: str, filename: str, default_suffix: str = "_out") -> str:
    """Return a workspace-relative output filename that is safe from path traversal.

    Strips all directory components and ensures the result stays inside the
    session workspace mount visible to Docker containers.  Returns a plain
    filename (basename only) suitable for appending to the container path
    ``/mnt/staging/<session_id>/workspace/``.
    """
    safe_name = Path(filename).name  # strip any directory prefix
    if not safe_name or ".." in safe_name:
        safe_name = f"output{default_suffix}"
    return safe_name


class Radare2Tool(DockerBasedTool):
    """radare2 reversing tool utilizing the official Docker image."""

    @property
    def name(self) -> str:
        return "radare2"

    @property
    def docker_image(self) -> str:
        return "radare/radare2"

    @property
    def smoke_test_cmd(self) -> str:
        return "r2 -v"

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
        return "ai-reo/objdump:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "objdump --version"

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
    def smoke_test_cmd(self) -> str:
        return "readelf --version"

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
    def smoke_test_cmd(self) -> str:
        return "nm --version"

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
    def smoke_test_cmd(self) -> str:
        # Import angr directly — fast and confirms it is installed correctly
        return "python -c \"import angr; print('angr ok')\""

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
        import os as _os
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        # Write the analysis script to the session workspace so it can be mounted
        # into the container.  This avoids shell-escaping issues with filenames.
        sessions_root = Path(settings.tools.sessions_dir).resolve()
        script_host_path = sessions_root / session_id / "workspace" / "_angr_analysis.py"
        script_content = (
            "import json, sys, traceback\n"
            "try:\n"
            "    import angr\n"
            f"    proj = angr.Project('/mnt/staging/{session_id}/workspace/{filepath}', auto_load_libs=False)\n"
            "    cfg = proj.analyses.CFGFast(normalize=True)\n"
            "    funcs = list(cfg.functions.values())\n"
            "    imports = sorted(list(getattr(proj.loader.main_object, 'imports', {}).keys()))[:100]\n"
            "    print(json.dumps({\n"
            "        'arch': proj.arch.name,\n"
            "        'entry': hex(proj.entry),\n"
            "        'loader': type(proj.loader.main_object).__name__,\n"
            "        'function_count': len(funcs),\n"
            "        'sample_functions': [{'name': f.name, 'addr': hex(f.addr)} for f in funcs[:50]],\n"
            "        'imports': imports,\n"
            "    }))\n"
            "except Exception as exc:\n"
            "    print(json.dumps({'error': str(exc), 'traceback': traceback.format_exc()}))\n"
            "    sys.exit(1)\n"
        )
        script_host_path.write_text(script_content, encoding="utf-8")

        full_cmd = f"python /mnt/staging/{session_id}/workspace/_angr_analysis.py"
        res = docker_executor.execute(self.docker_image, full_cmd, timeout=300)

        # Clean up helper script regardless of outcome
        try:
            _os.unlink(script_host_path)
        except OSError:
            pass

        output = res["output"].strip()
        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}
        try:
            parsed = json.loads(output)
            if "error" in parsed:
                return {"error": parsed["error"], "exit_code": 1}
            return parsed
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
    def smoke_test_cmd(self) -> str:
        return "upx --version"

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
            raw_output_path = kwargs.get("output_path") or f"{filepath}.unpacked"
            safe_output = _get_safe_output_path(session_id, raw_output_path, "_unpacked")
            full_cmd = (
                f"cp /mnt/staging/{session_id}/workspace/{filepath} "
                f"/mnt/staging/{session_id}/workspace/{safe_output} && "
                f"upx -d /mnt/staging/{session_id}/workspace/{safe_output}"
            )
            res = docker_executor.execute(self.docker_image, full_cmd, timeout=180)
            return {
                "exit_code": res["exit_code"],
                "output": res["output"],
                "output_file": safe_output,
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
    def smoke_test_cmd(self) -> str:
        return "capa --version"
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

        # pip-installed capa finds its own bundled rules automatically; no -r flag needed
        full_cmd = f"capa --json /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, full_cmd, timeout=300)

        output = res["output"].strip()
        if res["exit_code"] not in (0, 1):  # capa exits 1 when no capabilities found
            # Exit code 12 means the binary format is not supported by capa
            # (common for heavily packed/protected PE like Themida). Treat gracefully.
            if res["exit_code"] == 12:
                return {
                    "status": "not_applicable",
                    "message": (
                        "capa: Binary format not supported (exit 12). "
                        "The binary is likely packed or protected (e.g., Themida/WinLicense). "
                        "Run the deobfuscator agent to unpack it first, then retry capa."
                    ),
                    "exit_code": 12,
                }
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
    def smoke_test_cmd(self) -> str:
        return "yara --version"

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
    def smoke_test_cmd(self) -> str:
        return "/ghidra/support/analyzeHeadless -help 2>&1 | head -5"
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
            f"/ghidra/support/analyzeHeadless /tmp tmp_project "
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
    def smoke_test_cmd(self) -> str:
        return "diec --version"
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
    def smoke_test_cmd(self) -> str:
        return "python -c \"import lief; print('lief', lief.__version__)\""
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
    def smoke_test_cmd(self) -> str:
        return "floss --version"

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

        # Size gate: FLOSS times out / OOMs on files larger than 16 MB
        _MAX_FLOSS_BYTES = 16 * 1024 * 1024
        try:
            file_bytes = resolved.stat().st_size
        except OSError:
            file_bytes = 0
        if file_bytes > _MAX_FLOSS_BYTES:
            return {
                "error": "FILE_TOO_LARGE",
                "message": (
                    f"File is {file_bytes // 1024 // 1024} MB — FLOSS is limited to 16 MB. "
                    "Consider using strings_extract for large files."
                ),
            }

        cmd = f"floss --json /mnt/staging/{session_id}/workspace/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=300)

        output = res["output"].strip()
        if res["exit_code"] not in (0, 1):
            return {"error": output, "exit_code": res["exit_code"]}

        try:
            data = json.loads(output)
            static = data.get("strings", {}).get("static_strings", [])
            stack = data.get("strings", {}).get("stack_strings", [])
            decoded = data.get("strings", {}).get("decoded_strings", [])
            _LIMITS = (200, 100, 100)
            return {
                "static_strings": static[:_LIMITS[0]],
                "stack_strings": stack[:_LIMITS[1]],
                "decoded_strings": decoded[:_LIMITS[2]],
                "meta": data.get("metadata", {}),
                "truncated": {
                    "static_strings": len(static) > _LIMITS[0],
                    "stack_strings": len(stack) > _LIMITS[1],
                    "decoded_strings": len(decoded) > _LIMITS[2],
                },
                "totals": {
                    "static_strings": len(static),
                    "stack_strings": len(stack),
                    "decoded_strings": len(decoded),
                },
            }
        except (json.JSONDecodeError, KeyError):
            return {"output": output[:4000]}


class CheksecTool(DockerBasedTool):
    """Checksec — report binary security mitigations (PIE, NX, canary, RELRO, ASLR)."""

    @property
    def name(self) -> str:
        return "checksec"

    @property
    def docker_image(self) -> str:
        return "ai-reo/checksec:latest"
    @property
    def smoke_test_cmd(self) -> str:
        return "checksec --version"
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
    def smoke_test_cmd(self) -> str:
        return "python -c \"import unipacker; print('unipacker ok')\""
    @property
    def description(self) -> str:
        return (
            "Attempt to unpack a Windows PE binary using Unipacker (emulation-based). "
            "Supports many PE packers (UPX, MPRESS, PEtite, ASPack, etc.). "
            "The 'filepath' parameter must be the EXISTING packed input binary (e.g. 'sample.exe'). "
            "The 'output_filename' parameter (optional) sets the name of the unpacked output file. "
            "Do NOT pass the intended output filename as 'filepath' — that is a common mistake."
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
        raw_output = kwargs.get("output_filename") or f"{base_name}_unpacked.exe"
        output_filename = _get_safe_output_path(session_id, raw_output, "_unpacked.exe")

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


# ---------------------------------------------------------------------------
# New tools — Priority additions from the tool stack re-evaluation
# ---------------------------------------------------------------------------

class CapeAnalysisTool(BaseTool):
    """CAPE Sandbox — full dynamic analysis with memory dumps and behaviour reporting.

    This is a BaseTool (not DockerBasedTool) — it communicates with an external
    CAPE REST API rather than running a local container directly. Configure the
    CAPE URL via the AI_REO_CAPE_URL environment variable or .env file.
    """

    @property
    def name(self) -> str:
        return "cape"

    @property
    def description(self) -> str:
        return (
            "Submit a binary to CAPE Sandbox for full dynamic analysis. "
            "Returns behaviour report: process tree, API calls, network connections, "
            "memory dumps, and YARA signature matches. Requires a running CAPE instance "
            "(set AI_REO_CAPE_URL to the CAPE API base URL, e.g. http://localhost:8000)."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Analysis timeout in seconds (default 120)",
                    "default": 120,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    def validate_args(self, kwargs: Dict[str, Any]) -> None:
        import jsonschema
        jsonschema.validate(instance=kwargs, schema=self.get_schema())

    def is_ready(self) -> bool:
        """Check if the CAPE API is reachable."""
        cape_url = settings.tools.cape_url
        if not cape_url:
            return False
        try:
            import urllib.request
            with urllib.request.urlopen(f"{cape_url.rstrip('/')}/cuckoo/status/", timeout=5) as r:
                return r.status < 500
        except Exception:
            return False

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        import urllib.request, urllib.parse, urllib.error, time as _time

        cape_url = settings.tools.cape_url
        if not cape_url:
            return {
                "error": "CAPE_NOT_CONFIGURED",
                "message": "Set AI_REO_TOOLS_CAPE_URL to the CAPE API base URL (e.g. http://localhost:8000).",
            }

        filepath = kwargs["filepath"]
        analysis_timeout = int(kwargs.get("timeout", 120))
        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        binary_data = resolved.read_bytes()
        base = cape_url.rstrip("/")

        # Submit task
        try:
            import http.client, mimetypes, io as _io
            boundary = "----CapeUpload"
            body_parts = [
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filepath}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n".encode(),
                binary_data,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
            body = b"".join(body_parts)
            url_parts = urllib.parse.urlparse(f"{base}/tasks/create/file/")
            conn = http.client.HTTPConnection(url_parts.netloc, timeout=30)
            conn.request(
                "POST", url_parts.path,
                body=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            resp = conn.getresponse()
            resp_data = json.loads(resp.read().decode())
            task_id = resp_data.get("task_id") or (resp_data.get("data", {}) or {}).get("task_id")
        except Exception as e:
            return {"error": f"CAPE submit failed: {e}"}

        if not task_id:
            return {"error": "CAPE did not return a task_id", "response": str(resp_data)}

        # Poll for completion
        deadline = _time.time() + analysis_timeout + 60
        while _time.time() < deadline:
            import asyncio as _asyncio
            await _asyncio.sleep(10)
            try:
                url_parts = urllib.parse.urlparse(f"{base}/tasks/view/{task_id}/")
                conn2 = http.client.HTTPConnection(url_parts.netloc, timeout=10)
                conn2.request("GET", url_parts.path)
                status_resp = conn2.getresponse()
                status_data = json.loads(status_resp.read().decode())
                task_status = (status_data.get("data") or {}).get("status", "pending")
                if task_status == "reported":
                    break
            except Exception:
                continue

        # Fetch report
        try:
            url_parts = urllib.parse.urlparse(f"{base}/tasks/get/report/{task_id}/json/")
            conn3 = http.client.HTTPConnection(url_parts.netloc, timeout=30)
            conn3.request("GET", url_parts.path)
            report_resp = conn3.getresponse()
            report = json.loads(report_resp.read().decode())
            # Return a focused summary rather than the full (very large) report
            summary = report.get("info", {})
            behavior = report.get("behavior", {})
            return {
                "task_id": task_id,
                "status": summary.get("status"),
                "score": summary.get("score"),
                "signatures": [s.get("name") for s in report.get("signatures", [])[:20]],
                "processes": [p.get("process_name") for p in behavior.get("processes", [])[:20]],
                "network_hosts": [h.get("ip") for h in (report.get("network") or {}).get("hosts", [])[:20]],
                "yara_matches": [y.get("name") for y in report.get("target", {}).get("file", {}).get("yara", [])],
            }
        except Exception as e:
            return {"task_id": task_id, "error": f"Failed to fetch CAPE report: {e}"}


class FridaTool(DockerBasedTool):
    """Frida dynamic instrumentation toolkit for runtime hooking and tracing."""

    @property
    def name(self) -> str:
        return "frida"

    @property
    def docker_image(self) -> str:
        return "ai-reo/frida:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "frida --version"

    @property
    def description(self) -> str:
        return (
            "Use Frida to dynamically instrument and trace a process at runtime. "
            "Supports hooking functions, tracing API calls, and extracting decrypted data "
            "from running processes. Requires a frida-server or a file-based spawn. "
            "Provide a Frida script as 'script_content' or a script 'filepath'."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Binary to spawn and instrument",
                },
                "script_content": {
                    "type": "string",
                    "description": "Frida JavaScript instrumentation script content",
                },
            },
            "required": ["filepath", "script_content"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        script_content = kwargs["script_content"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        # Write script to a temp path inside the container
        script_path = f"/tmp/frida_script_{session_id}.js"
        escaped = script_content.replace('"', '\\"').replace('\n', '\\n')
        cmd = (
            f'printf "{escaped}" > {script_path} && '
            f"frida -f /mnt/staging/{session_id}/workspace/{filepath} "
            f"--no-pause -l {script_path} 2>&1"
        )
        res = docker_executor.execute(self.docker_image, cmd, timeout=60)
        return {"exit_code": res["exit_code"], "output": res["output"][:4000]}


class QilingTool(DockerBasedTool):
    """Qiling multi-platform binary emulation framework for sandbox-free dynamic analysis."""

    @property
    def name(self) -> str:
        return "qiling"

    @property
    def docker_image(self) -> str:
        return "ai-reo/qiling:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "python -c \"import qiling; print('qiling', qiling.__version__)\""

    @property
    def description(self) -> str:
        return (
            "Emulate Windows/Linux/macOS/Android binaries using Qiling without an actual OS. "
            "Captures syscalls, API calls, and memory operations during emulation. "
            "Ideal for malware behaviour analysis in a fully controlled environment."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "os": {
                    "type": "string",
                    "enum": ["windows", "linux", "macos", "freebsd"],
                    "default": "windows",
                    "description": "Target OS to emulate (default: windows)",
                },
                "arch": {
                    "type": "string",
                    "enum": ["x86", "x8664", "arm", "arm64", "mips"],
                    "default": "x8664",
                    "description": "Target architecture (default: x8664)",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        os_target = kwargs.get("os", "windows")
        arch = kwargs.get("arch", "x8664")

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        script = (
            "from qiling import Qiling; "
            "from qiling.const import QL_VERBOSE; "
            "import json; "
            "log_entries = []; "
            f"ql = Qiling(['/mnt/staging/{session_id}/workspace/{filepath}'], "
            f"            '/opt/qiling/examples/rootfs/{os_target}_x8664', "
            f"            verbose=QL_VERBOSE.OFF); "
            "orig_syscall = ql.os.set_syscall; "
            "api_calls = []; "
            "ql.run(); "
            "print(json.dumps({'status': 'completed', 'api_calls': api_calls[:100]}))"
        )
        cmd = f"timeout 60 python3 -c \"{script}\" 2>&1"
        res = docker_executor.execute(self.docker_image, cmd, timeout=90)

        output = res["output"].strip()
        try:
            for line in output.splitlines():
                if line.startswith("{"):
                    return json.loads(line)
        except Exception:
            pass
        return {"exit_code": res["exit_code"], "output": output[:3000]}


class PeSieveTool(DockerBasedTool):
    """PE-sieve — in-memory PE scanner and unpacker via Wine."""

    @property
    def name(self) -> str:
        return "pe_sieve"

    @property
    def docker_image(self) -> str:
        return "ai-reo/pe_sieve:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "wine pe-sieve.exe /? 2>&1 | head -3"

    @property
    def description(self) -> str:
        return (
            "Run PE-sieve (by hasherezade) via Wine to detect process hollowing, "
            "DLL/shellcode injection, hooks, and in-memory PE modifications. "
            "Pass a PID for live scanning or use in headless mode against a static PE."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target PE binary inside the session binary dir",
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

        cmd = f"wine /opt/pe-sieve/pe-sieve.exe /img /mnt/staging/{session_id}/workspace/{filepath} /json 2>&1"
        res = docker_executor.execute(self.docker_image, cmd, timeout=120)
        output = res["output"].strip()
        try:
            for line in output.splitlines():
                if line.startswith("{"):
                    return json.loads(line)
        except Exception:
            pass
        return {"exit_code": res["exit_code"], "output": output[:4000]}


class HollowsHunterTool(DockerBasedTool):
    """Hollows Hunter — process-wide PE anomaly scanner via Wine."""

    @property
    def name(self) -> str:
        return "hollows_hunter"

    @property
    def docker_image(self) -> str:
        return "ai-reo/hollows_hunter:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "wine hollows_hunter.exe /? 2>&1 | head -3"

    @property
    def description(self) -> str:
        return (
            "Run Hollows Hunter (by hasherezade) via Wine to scan for hollowed processes, "
            "implanted shellcode, patched modules, and other in-memory PE anomalies. "
            "Complement to PE-sieve for full process-tree coverage."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target PE binary inside the session binary dir",
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

        cmd = (
            f"wine /opt/hollows_hunter/hollows_hunter.exe /json "
            f"/mnt/staging/{session_id}/workspace/{filepath} 2>&1"
        )
        res = docker_executor.execute(self.docker_image, cmd, timeout=120)
        output = res["output"].strip()
        try:
            for line in output.splitlines():
                if line.startswith("{"):
                    return json.loads(line)
        except Exception:
            pass
        return {"exit_code": res["exit_code"], "output": output[:4000]}


class UnlicenseTool(DockerBasedTool):
    """unlicense — dynamic Themida/WinLicense 2.x & 3.x unpacker."""

    @property
    def name(self) -> str:
        return "unlicense"

    @property
    def docker_image(self) -> str:
        return "ai-reo/unlicense:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "wine --version"

    @property
    def description(self) -> str:
        return (
            "Unpack Themida/WinLicense 2.x and 3.x protected PE binaries using unlicense. "
            "Reconstructs the original import table and writes the unpacked PE. "
            "Use when die/capa identifies Themida or WinLicense as the protector."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to Themida/WinLicense protected PE",
                },
                "output_filename": {
                    "type": "string",
                    "description": "Output filename for the unpacked binary (default: <name>_unlicensed.exe)",
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        import os as _os
        filepath = kwargs["filepath"]
        base_name = _os.path.splitext(_os.path.basename(filepath))[0]
        output_filename = kwargs.get("output_filename") or f"{base_name}_unlicensed.exe"

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        out_path = f"/mnt/staging/{session_id}/workspace/{output_filename}"
        cmd = (
            f"unlicense /mnt/staging/{session_id}/workspace/{filepath} {out_path} 2>&1"
        )
        res = docker_executor.execute(self.docker_image, cmd, timeout=300)
        return {
            "exit_code": res["exit_code"],
            "output": res["output"][:3000],
            "output_file": output_filename,
        }


class Volatility3Tool(DockerBasedTool):
    """Volatility 3 memory forensics framework."""

    @property
    def name(self) -> str:
        return "volatility3"

    @property
    def docker_image(self) -> str:
        return "ai-reo/volatility3:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "vol --version 2>&1 | head -1"

    @property
    def description(self) -> str:
        return (
            "Run Volatility 3 memory forensics plugins against a memory dump. "
            "Supports Windows, Linux, and macOS memory images. "
            "Useful plugins: windows.pslist, windows.cmdline, windows.netscan, "
            "windows.dlllist, windows.malfind, linux.bash."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to a memory dump (.dmp, .raw, .vmem) inside the session dir",
                },
                "plugin": {
                    "type": "string",
                    "description": "Volatility 3 plugin name (e.g. 'windows.pslist', 'windows.malfind')",
                    "default": "windows.pslist",
                },
            },
            "required": ["filepath", "plugin"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        plugin = kwargs.get("plugin", "windows.pslist")

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        cmd = (
            f"vol -f /mnt/staging/{session_id}/workspace/{filepath} "
            f"{plugin} 2>&1"
        )
        res = docker_executor.execute(self.docker_image, cmd, timeout=300)
        output = res["output"].strip()
        return {"exit_code": res["exit_code"], "output": output[:6000]}


class JadxTool(DockerBasedTool):
    """JADX — Android DEX/APK/AAR decompiler to Java/Kotlin source."""

    @property
    def name(self) -> str:
        return "jadx"

    @property
    def docker_image(self) -> str:
        return "ai-reo/jadx:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "jadx --version"

    @property
    def description(self) -> str:
        return (
            "Decompile Android APK, DEX, AAR, or JAR files to Java source code using JADX. "
            "Produces human-readable source in the session workspace under a jadx_out/ directory. "
            "Ideal first step for Android malware analysis."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to APK/DEX/JAR inside the session binary dir",
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

        out_dir = f"/mnt/staging/{session_id}/workspace/jadx_out"
        cmd = f"jadx -d {out_dir} /mnt/staging/{session_id}/workspace/{filepath} 2>&1"
        res = docker_executor.execute(self.docker_image, cmd, timeout=300)
        output = res["output"].strip()
        return {
            "exit_code": res["exit_code"],
            "output": output[:3000],
            "output_dir": f"jadx_out/",
        }


class ApktoolTool(DockerBasedTool):
    """Apktool — Android APK disassembly and resource decoding."""

    @property
    def name(self) -> str:
        return "apktool"

    @property
    def docker_image(self) -> str:
        return "ai-reo/apktool:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "apktool --version"

    @property
    def description(self) -> str:
        return (
            "Disassemble Android APK files to Smali code and decode binary resources using Apktool. "
            "Extracts AndroidManifest.xml, resources, and Smali bytecode for static analysis."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to APK inside the session binary dir",
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

        out_dir = f"/mnt/staging/{session_id}/workspace/apktool_out"
        cmd = f"apktool d -f -o {out_dir} /mnt/staging/{session_id}/workspace/{filepath} 2>&1"
        res = docker_executor.execute(self.docker_image, cmd, timeout=120)
        output = res["output"].strip()
        return {
            "exit_code": res["exit_code"],
            "output": output[:3000],
            "output_dir": "apktool_out/",
        }


class ApkidTool(DockerBasedTool):
    """APKiD — Android packer, obfuscator, and anti-analysis feature detector."""

    @property
    def name(self) -> str:
        return "apkid"

    @property
    def docker_image(self) -> str:
        return "ai-reo/apkid:latest"

    @property
    def smoke_test_cmd(self) -> str:
        return "apkid -v"

    @property
    def description(self) -> str:
        return (
            "Identify Android-specific packers, obfuscators, anti-analysis techniques, "
            "and pinned certificates in APK files using APKiD. "
            "Similar to DIE/capa but specialised for Android DEX bytecode."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to APK/DEX inside the session binary dir",
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

        cmd = f"apkid -j /mnt/staging/{session_id}/workspace/{filepath} 2>&1"
        res = docker_executor.execute(self.docker_image, cmd, timeout=120)
        output = res["output"].strip()
        try:
            for line in output.splitlines():
                if line.startswith("{"):
                    return json.loads(line)
        except Exception:
            pass
        return {"exit_code": res["exit_code"], "output": output[:3000]}


class AflplusplusTool(DockerBasedTool):
    """AFL++ — state-of-the-art grey-box fuzzer in QEMU mode for black-box binaries."""

    @property
    def name(self) -> str:
        return "afl_plusplus"

    @property
    def docker_image(self) -> str:
        return "aflplusplus/aflplusplus"

    @property
    def smoke_test_cmd(self) -> str:
        return "afl-fuzz --version 2>&1 | head -3"

    @property
    def description(self) -> str:
        return (
            "Fuzz a binary using AFL++ in QEMU mode (no source required). "
            "stdin_input=true pipes mutations via stdin; otherwise uses '@@' for file input. "
            "Runs for 'duration' seconds then returns crash count, coverage, and any found crashes. "
            "Requires an 'input_dir' with at least one seed corpus file in the session workspace."
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to target binary inside the session binary dir",
                },
                "input_dir": {
                    "type": "string",
                    "description": "Relative path to seed corpus directory inside the session dir (default: 'input')",
                    "default": "input",
                },
                "duration": {
                    "type": "integer",
                    "description": "How many seconds to fuzz (default 60)",
                    "default": 60,
                },
                "stdin_input": {
                    "type": "boolean",
                    "description": "Feed mutations via stdin if true; otherwise use file (@@). Default false.",
                    "default": False,
                },
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]
        input_dir = kwargs.get("input_dir", "input")
        duration = int(kwargs.get("duration", 60))
        stdin_input = bool(kwargs.get("stdin_input", False))

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available. Set up from the Tools page.",
            }

        input_flag = "" if stdin_input else "@@"
        seeds = f"/mnt/staging/{session_id}/workspace/{input_dir}"
        output = f"/mnt/staging/{session_id}/workspace/afl_out"
        target = f"/mnt/staging/{session_id}/workspace/{filepath}"
        cmd = (
            f"timeout {duration + 10} afl-fuzz -Q -i {seeds} -o {output} "
            f"-- {target} {input_flag} 2>&1; "
            f"echo 'CRASHES:' $(ls {output}/crashes/ 2>/dev/null | wc -l); "
            f"echo 'HANGS:' $(ls {output}/hangs/ 2>/dev/null | wc -l)"
        )
        res = docker_executor.execute(self.docker_image, cmd, timeout=duration + 60)
        output_text = res["output"]
        # Parse crash/hang counts from tail
        crashes, hangs = 0, 0
        for line in output_text.splitlines():
            if line.startswith("CRASHES:"):
                try:
                    crashes = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("HANGS:"):
                try:
                    hangs = int(line.split(":")[1].strip())
                except ValueError:
                    pass
        return {
            "exit_code": res["exit_code"],
            "crashes_found": crashes,
            "hangs_found": hangs,
            "output": output_text[-3000:],
            "output_dir": "afl_out/",
        }
