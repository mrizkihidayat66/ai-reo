"""Specialized AI-REO agent roles."""

from typing import Optional
from ai_reo.agents.base import BaseAgent

class StaticAnalyst(BaseAgent):
    """Agent specialized in structural disassembly and offline parsing."""
    def __init__(self) -> None:
        super().__init__(
            role_name="static_analyst",
            allowed_tools=["strings_extract", "binary_info", "entropy_analysis", "hex_dump", "file_type", "bintropy", "pefile", "radare2", "objdump", "readelf", "nm", "angr", "upx", "capa", "yara", "die", "lief", "floss", "binwalk", "checksec", "ghidra_headless", "fs_read", "fs_write", "scripts_write", "scripts_list"]
        )

class DynamicAnalyst(BaseAgent):
    """Agent specialized in running the binary in sandboxes."""
    def __init__(self) -> None:
        super().__init__(
            role_name="dynamic_analyst",
            allowed_tools=["fs_read", "fs_write"]
        )

class DocumentationAgent(BaseAgent):
    """Agent specialized strictly in synthesizing final readable reports. Sandboxed heavily."""
    def __init__(self) -> None:
        super().__init__(
            role_name="documentation",
            allowed_tools=[]
        )

class OrchestratorAgent(BaseAgent):
    """Agent specialized in planning and routing."""
    def __init__(self) -> None:
        super().__init__(
            role_name="orchestrator",
            allowed_tools=[]
        )

class DeobfuscatorAgent(BaseAgent):
    """Agent specialized in detecting and reversing obfuscation, packing, and encryption."""
    def __init__(self) -> None:
        super().__init__(
            role_name="deobfuscator",
            allowed_tools=["upx", "die", "entropy_analysis", "hex_dump", "file_type", "bintropy", "floss", "yara", "radare2", "angr", "lief", "unipacker", "strings_extract", "fs_read", "fs_write", "scripts_write", "scripts_list"]
        )

class DebuggerAgent(BaseAgent):
    """Agent specialized in symbolic execution and vulnerability triage."""
    def __init__(self) -> None:
        super().__init__(
            role_name="debugger",
            allowed_tools=["angr", "radare2", "lief", "pefile", "checksec", "hex_dump", "strings_extract", "fs_read", "fs_write", "scripts_write", "scripts_list"]
        )
