"""Core interfaces for all AI-REO tools."""

import jsonschema
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base class representing an MCP-style tool for AI agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the tool as exposed to the LLM."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Prompt-friendly description of what the tool accomplishes."""
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Return the JSON schema for this tool's parameters (OpenAI function/MCP compatible)."""
        pass

    def validate_args(self, kwargs: Dict[str, Any]) -> None:
        """Validate input arguments against the schema. Raises jsonschema.ValidationError on failure."""
        jsonschema.validate(instance=kwargs, schema=self.get_schema())

    @abstractmethod
    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        """Core execution logic.

        Args:
            session_id: Analysis session contextual ID (useful for locating binaries).
            **kwargs: Arguments supplied by the LLM (must match schema).
        Returns:
            JSON-serializable result representing strict tool output.
        """
        pass


class DockerBasedTool(BaseTool):
    """Extended base for Docker-backed tools with image readiness tracking.

    Subclasses must implement ``docker_image`` in addition to the standard
    ``BaseTool`` methods. This class provides:
      - Local image availability checking (no network call)
      - Image pulling with progress streaming
      - Pre-execution checks for Docker daemon + binary existence
    """

    @property
    @abstractmethod
    def docker_image(self) -> str:
        """The Docker image this tool requires (e.g., 'radare/radare2')."""
        pass

    def is_docker_available(self) -> bool:
        """Check if the Docker daemon is reachable."""
        try:
            from ai_reo.tools.docker_exec import docker_executor
            return docker_executor.client is not None
        except Exception:
            return False

    def is_image_available(self) -> bool:
        """Check if the required Docker image is present locally (no network call)."""
        try:
            from ai_reo.tools.docker_exec import docker_executor
            if not docker_executor.client:
                return False
            docker_executor.client.images.get(self.docker_image)
            return True
        except Exception:
            return False

    def is_ready(self) -> bool:
        """Full readiness check: Docker available AND image pulled."""
        return self.is_docker_available() and self.is_image_available()

    async def pull_image(self, progress_callback=None) -> bool:
        """Pull the Docker image, streaming progress via callback.

        Args:
            progress_callback: Optional async callable receiving progress dicts.
        Returns:
            True on success, False on failure.
        """
        try:
            from ai_reo.tools.docker_exec import docker_executor
            if not docker_executor.client:
                return False

            for line in docker_executor.client.api.pull(
                self.docker_image, stream=True, decode=True
            ):
                if progress_callback and "status" in line:
                    await progress_callback({
                        "tool": self.name,
                        "image": self.docker_image,
                        "status": line["status"],
                        "progress": line.get("progressDetail", {}),
                    })
            return True
        except Exception:
            return False
