"""Specialized AI-REO agent roles."""

from typing import Optional
from ai_reo.agents.base import BaseAgent

class StaticAnalyst(BaseAgent):
    """Agent specialized in structural disassembly and offline parsing."""
    def __init__(self) -> None:
        super().__init__(
            role_name="static_analyst",
            # Strict authorization ensuring it has no sandbox execution capability (dynamic analysis)
            allowed_tools=["strings_extract", "binary_info", "radare2", "objdump", "readelf", "nm", "angr", "upx", "capa", "yara", "ghidra_headless", "fs_read", "fs_write"]
        )

class DynamicAnalyst(BaseAgent):
    """Agent specialized in running the binary in sandboxes."""
    def __init__(self) -> None:
        super().__init__(
            role_name="dynamic_analyst",
            # For the MVP, it utilizes basic shell commands. 
            # We haven't implemented ShellCommandTool specifically yet, but declaring intent here.
            allowed_tools=["fs_read", "fs_write"]
        )

class DocumentationAgent(BaseAgent):
    """Agent specialized strictly in synthesizing final readable reports. Sandboxed heavily."""
    def __init__(self) -> None:
        super().__init__(
            role_name="documentation",
            allowed_tools=[]  # Explicitly ZERO tools. Documentation cannot invoke arbitrary execution.
        )

class OrchestratorAgent(BaseAgent):
    """Agent specialized in planning and routing."""
    def __init__(self) -> None:
        super().__init__(
            role_name="orchestrator",
            allowed_tools=[]  # The Orchestrator plans structurally via LLM outputs, tools aren't strictly required for routing in our LangGraph architecture.
        )
