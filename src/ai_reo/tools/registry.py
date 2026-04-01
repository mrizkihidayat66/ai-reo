"""Central registry for discovering and routing tools."""

from typing import Any, Dict, List, Type

from ai_reo.tools.interface import BaseTool


class ToolRegistry:
    """Maintains the runtime catalog of available agent tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register an instantiated tool."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool:
        """Retrieve a specific tool by name."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered.")
        return self._tools[name]

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return MCP/OpenAI-friendly metadata array of all loaded tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.get_schema(),
                }
            }
            for tool in self._tools.values()
        ]

    async def dispatch(self, tool_name: str, session_id: str, kwargs: Dict[str, Any]) -> Any:
        """Validate tool arguments and execute it."""
        tool = self.get_tool(tool_name)
        tool.validate_args(kwargs)
        return await tool.execute(session_id=session_id, **kwargs)


# Global singleton bounding all active AI-REO tools
tool_registry = ToolRegistry()
