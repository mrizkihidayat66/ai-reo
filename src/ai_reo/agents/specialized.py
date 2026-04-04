"""Specialized AI-REO agent roles."""

from typing import Dict, Optional
from ai_reo.agents.base import BaseAgent

class StaticAnalyst(BaseAgent):
    """Agent specialized in structural disassembly and offline parsing."""
    def __init__(self) -> None:
        super().__init__(
            role_name="static_analyst",
            allowed_tools=[
                "strings_extract", "binary_info", "entropy_analysis", "hex_dump",
                "file_type", "pefile", "radare2", "objdump", "readelf", "nm",
                "angr", "upx", "capa", "yara", "die", "lief", "floss",
                "checksec", "ghidra_headless", "fs_read", "fs_write",
                "scripts_write", "scripts_list",
            ]
        )

class DynamicAnalyst(BaseAgent):
    """Agent specialized in running the binary in sandboxes and emulators."""
    def __init__(self) -> None:
        super().__init__(
            role_name="dynamic_analyst",
            allowed_tools=[
                "strings_extract", "hex_dump", "radare2", "binary_info", "file_type",
                "fs_read", "fs_write",
                # Sandboxing & emulation
                "cape", "frida", "qiling",
                # Memory forensics
                "volatility3",
            ]
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
            allowed_tools=[
                "upx", "die", "entropy_analysis", "hex_dump", "file_type",
                "floss", "yara", "radare2", "angr", "lief", "unipacker",
                "strings_extract", "fs_read", "fs_write", "scripts_write", "scripts_list",
                # PE memory unpacking / evasion detection
                "pe_sieve", "hollows_hunter", "unlicense",
                # Emulation-based unpacking
                "qiling",
            ]
        )

class DebuggerAgent(BaseAgent):
    """Agent specialized in symbolic execution and vulnerability triage."""
    def __init__(self) -> None:
        super().__init__(
            role_name="debugger",
            allowed_tools=[
                "angr", "radare2", "lief", "pefile", "checksec", "hex_dump",
                "strings_extract", "fs_read", "fs_write", "scripts_write", "scripts_list",
                # Fuzzing
                "afl_plusplus",
                # Memory dumps
                "volatility3",
            ]
        )

class MobileAnalyst(BaseAgent):
    """Agent specialized in Android APK/DEX reverse engineering."""
    def __init__(self) -> None:
        super().__init__(
            role_name="mobile_analyst",
            allowed_tools=[
                "jadx", "apktool", "apkid",
                "strings_extract", "binary_info", "file_type",
                "yara", "die",
                "fs_read", "fs_write", "scripts_write", "scripts_list",
            ]
        )

class CryptoAnalyst(BaseAgent):
    """Agent specialized in cryptographic algorithm identification and key extraction."""
    def __init__(self) -> None:
        super().__init__(
            role_name="crypto_analyst",
            allowed_tools=[
                "radare2", "ghidra_headless", "pefile", "lief",
                "strings_extract", "hex_dump", "yara", "angr",
                "fs_read", "fs_write", "scripts_write", "scripts_list",
            ]
        )

class NetworkAnalyst(BaseAgent):
    """Agent specialized in network protocol reverse engineering and C2 traffic analysis."""
    def __init__(self) -> None:
        super().__init__(
            role_name="network_analyst",
            allowed_tools=[
                "strings_extract", "hex_dump", "radare2", "binary_info", "file_type",
                "frida", "cape", "volatility3",
                "fs_read", "fs_write", "scripts_write", "scripts_list",
            ]
        )

class FirmwareAnalyst(BaseAgent):
    """Agent specialized in IoT/embedded firmware extraction and analysis."""
    def __init__(self) -> None:
        super().__init__(
            role_name="firmware_analyst",
            allowed_tools=[
                "binwalk", "strings_extract", "radare2", "hex_dump",
                "file_type", "entropy_analysis", "objdump", "readelf", "nm",
                "die", "floss", "pefile", "lief", "yara",
                "fs_read", "fs_write", "scripts_write", "scripts_list",
            ]
        )

class ExploitDeveloper(BaseAgent):
    """Agent specialized in exploit development, ROP chains, and PoC construction."""
    def __init__(self) -> None:
        super().__init__(
            role_name="exploit_developer",
            allowed_tools=[
                "radare2", "angr", "checksec", "pefile", "lief",
                "hex_dump", "strings_extract",
                "afl_plusplus", "volatility3",
                "fs_read", "fs_write", "scripts_write", "scripts_list",
            ]
        )

class CodeAuditor(BaseAgent):
    """Agent specialized in source-level and binary code auditing for security issues."""
    def __init__(self) -> None:
        super().__init__(
            role_name="code_auditor",
            allowed_tools=[
                "radare2", "ghidra_headless", "strings_extract",
                "pefile", "lief", "capa", "hex_dump", "checksec",
                "fs_read", "fs_write", "scripts_write", "scripts_list",
            ]
        )


# ---------------------------------------------------------------------------
# Agent registry — authoritative source for all agent metadata.
# Used by graph.py to build the LangGraph and by prompts.py to inject
# a dynamic {agents_and_tools} block into the orchestrator prompt.
# ---------------------------------------------------------------------------

AGENT_REGISTRY: Dict[str, Dict] = {
    "static_analyst": {
        "class": StaticAnalyst,
        "description": "Binary inspection without execution. File format, sections, headers, entropy, strings, disassembly, function identification, cross-references, imports/exports, CFG.",
        "primary_tools": "radare2, objdump, ghidra_headless, die, lief, entropy_analysis, hex_dump, file_type, pefile, floss, capa, yara, angr, checksec",
        "route_keywords": ["static", "strings", "disassem", "header", "radare", "objdump", "section", "import", "export"],
    },
    "dynamic_analyst": {
        "class": DynamicAnalyst,
        "description": "Runtime analysis. Execution traces, sandbox behavior, API call monitoring, memory snapshots. Use ONLY when static analysis is insufficient.",
        "primary_tools": "cape, frida, qiling, volatility3",
        "route_keywords": ["dynamic", "execut", "trace", "emulat", "sandbox", "runtime"],
    },
    "deobfuscator": {
        "class": DeobfuscatorAgent,
        "description": "Packing, protection, and obfuscation analysis. Use when entropy > 6.8 AND a packer is detected, or imports are stripped.",
        "primary_tools": "upx, die, entropy_analysis, yara, angr, lief, unipacker, pe_sieve, hollows_hunter, unlicense",
        "route_keywords": ["obfuscat", "packed", "packer", "unpack", "protect"],
    },
    "debugger": {
        "class": DebuggerAgent,
        "description": "Symbolic execution and vulnerability triage. Use when a specific bug class (overflow, UAF, format string) must be confirmed.",
        "primary_tools": "angr, radare2, checksec, afl_plusplus, volatility3",
        "route_keywords": ["debug", "vuln", "afl", "fuzz", "crash"],
    },
    "mobile_analyst": {
        "class": MobileAnalyst,
        "description": "Android APK/DEX reverse engineering. APK/DEX/smali/Java decompilation, manifest audit, DexClassLoader, native lib analysis.",
        "primary_tools": "apkid, apktool, jadx",
        "route_keywords": ["apk", "android", "mobile", "dex", "smali", "jadx", "apktool"],
    },
    "crypto_analyst": {
        "class": CryptoAnalyst,
        "description": "Cryptographic algorithm identification and key extraction. AES/SHA/RC4 constants, hardcoded keys, custom cipher implementations.",
        "primary_tools": "capa, radare2, yara, angr",
        "route_keywords": ["crypto", "aes", "sha", "rc4", "cipher", "key extraction", "encrypt"],
    },
    "network_analyst": {
        "class": NetworkAnalyst,
        "description": "Network protocol RE and C2 traffic analysis. Custom protocols, beacons, Winsock/WinHTTP/curl imports.",
        "primary_tools": "strings_extract, radare2, cape, frida, volatility3",
        "route_keywords": ["network", "protocol", "c2", "beacon", "traffic", "packet", "pcap"],
    },
    "firmware_analyst": {
        "class": FirmwareAnalyst,
        "description": "IoT/embedded firmware extraction and analysis. .bin/.img/.trx, squashfs/JFFS2, credential hunting, service identification.",
        "primary_tools": "binwalk, entropy_analysis, readelf, die",
        "route_keywords": ["firmware", "iot", "embedded", "binwalk", "squashfs", "bootloader"],
    },
    "exploit_developer": {
        "class": ExploitDeveloper,
        "description": "Exploit development and PoC construction. Use ONLY after a specific vulnerability has been confirmed.",
        "primary_tools": "radare2, angr, checksec, afl_plusplus",
        "route_keywords": ["rop", "shellcode", "exploit", "heap", "buffer overflow", "rop chain", "symbolic"],
    },
    "code_auditor": {
        "class": CodeAuditor,
        "description": "Systematic security auditing. Dangerous API usage, input validation gaps, injection vulnerabilities, cryptographic misuse.",
        "primary_tools": "capa, pefile, radare2, ghidra_headless, checksec",
        "route_keywords": ["audit", "source code", "code review", "vulnerability scan", "code quality"],
    },
    "documentation": {
        "class": DocumentationAgent,
        "description": "Final synthesis of all findings into a readable report. Use ONLY when sufficient findings exist, or analysis has stagnated.",
        "primary_tools": "(none — report synthesis only)",
        "route_keywords": ["report", "done", "complete", "summary", "final", "document"],
    },
}
