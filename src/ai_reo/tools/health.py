"""Tool health and readiness service.

Provides a centralized service to:
  - Check readiness of all registered tools (Docker daemon + image status)
  - Pull missing Docker images with progress streaming
  - Aggregate status for the frontend ToolsPage
"""

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ai_reo.tools.interface import DockerBasedTool
from ai_reo.tools.registry import tool_registry

logger = logging.getLogger(__name__)


@dataclass
class ToolStatus:
    """Readiness status for a single tool."""
    name: str
    ready: bool = False
    docker_required: bool = False
    docker_available: bool = False
    image: str = ""
    image_available: bool = False
    error: Optional[str] = None


class ToolHealthService:
    """Checks and manages the readiness of all registered tools."""

    async def ensure_environment(self) -> Dict[str, Any]:
        """Ensure required local Docker/tool environment is prepared."""
        report: Dict[str, Any] = {
            "sessions_dir": {"ok": False, "path": ""},
            "docker": {"ok": False},
            "network": {"ok": False, "name": ""},
        }

        try:
            from ai_reo.config import settings
            sessions_dir = Path(settings.tools.sessions_dir).expanduser().resolve()
            sessions_dir.mkdir(parents=True, exist_ok=True)
            report["sessions_dir"] = {"ok": True, "path": str(sessions_dir)}

            # Ensure the persistent scripts directory exists (user-generated scripts)
            Path(settings.tools.scripts_dir).expanduser().resolve().mkdir(parents=True, exist_ok=True)

            from ai_reo.tools.docker_exec import docker_executor

            client = docker_executor.client
            if not client:
                report["docker"] = {"ok": False, "error": "Docker client not initialized"}
                return report

            client.ping()
            report["docker"] = {"ok": True}

            network_name = settings.tools.docker_network
            report["network"]["name"] = network_name
            try:
                client.networks.get(network_name)
                report["network"]["ok"] = True
            except Exception:
                client.networks.create(network_name, check_duplicate=True)
                report["network"]["ok"] = True

            return report
        except Exception as exc:
            report["error"] = str(exc)
            return report

    async def _build_local_image_if_supported(self, tool_name: str, tool: DockerBasedTool) -> bool:
        """Build known local images when they are not published to Docker Hub."""
        image = tool.docker_image
        # Maps image tag to its tool subdirectory under docker/<tool>/
        local_image_map = {
            "ai-reo/objdump:latest":   "objdump",
            "ai-reo/angr:latest":      "angr",
            "ai-reo/upx:latest":       "upx",
            "ai-reo/capa:latest":      "capa",
            "ai-reo/yara:latest":      "yara",
            "ai-reo/die:latest":       "die",
            "ai-reo/lief:latest":      "lief",
            "ai-reo/checksec:latest":  "checksec",
            "ai-reo/unipacker:latest": "unipacker",
            "ai-reo/floss:latest":     "floss",
            "ai-reo/binwalk:latest":   "binwalk",
        }
        tool_dir = local_image_map.get(image)
        if tool_dir is None:
            return False

        try:
            from ai_reo.tools.docker_exec import docker_executor

            if not docker_executor.client:
                return False

            # Build context is the tool's own directory — keeps context small
            project_root = Path(__file__).resolve().parents[3]
            context = project_root / "docker" / tool_dir
            logger.info("Tool %s: building local image %s from %s...", tool_name, image, context)
            docker_executor.client.images.build(
                path=str(context),
                dockerfile="Dockerfile",
                tag=image,
                rm=True,
            )
            logger.info("Tool %s: local image build complete.", tool_name)
            return True
        except Exception as exc:
            logger.warning("Tool %s: local image build failed: %s", tool_name, exc)
            return False

    async def get_status(self) -> Dict[str, ToolStatus]:
        """Return readiness status for every registered tool."""
        result = {}

        for name, tool in tool_registry._tools.items():
            if isinstance(tool, DockerBasedTool):
                docker_ok = tool.is_docker_available()
                image_ok = tool.is_image_available() if docker_ok else False
                result[name] = ToolStatus(
                    name=name,
                    docker_required=True,
                    docker_available=docker_ok,
                    image=tool.docker_image,
                    image_available=image_ok,
                    ready=docker_ok and image_ok,
                    error=None if docker_ok else "Docker daemon not available",
                )
            else:
                # Non-Docker tools (fs_read, fs_write) are always ready
                result[name] = ToolStatus(name=name, ready=True)

        return result

    async def setup_tool(
        self,
        tool_name: str,
        ws_callback: Optional[Callable] = None,
    ) -> bool:
        """Pull the required Docker image for a specific tool.

        Args:
            tool_name: Name of the tool to set up.
            ws_callback: Optional async callable for progress updates.

        Returns:
            True on success, False on failure.
        """
        tool = tool_registry.get_tool(tool_name)
        if not isinstance(tool, DockerBasedTool):
            return True  # Non-Docker tools need no setup

        # Always rebuild repo-owned images so local Dockerfile changes are applied.
        if tool.docker_image.startswith("ai-reo/"):
            if await self._build_local_image_if_supported(tool_name, tool):
                return tool.is_image_available()

        if tool.is_image_available():
            logger.info("Tool %s: image %s already available.", tool_name, tool.docker_image)
            return True

        logger.info("Tool %s: pulling image %s...", tool_name, tool.docker_image)
        return await tool.pull_image(progress_callback=ws_callback)

    async def setup_all(
        self,
        ws_callback: Optional[Callable] = None,
    ) -> Dict[str, bool]:
        """Pull all missing tool images, returning success status per tool."""
        results = {}

        for name, tool in tool_registry._tools.items():
            if isinstance(tool, DockerBasedTool) and tool.docker_image.startswith("ai-reo/"):
                results[name] = await self._build_local_image_if_supported(name, tool)
                continue
            if isinstance(tool, DockerBasedTool) and not tool.is_image_available():
                success = await tool.pull_image(progress_callback=ws_callback)
                results[name] = success
            else:
                results[name] = True

        return results

    async def get_docker_status(self) -> Dict[str, Any]:
        """Return overall Docker daemon status."""
        try:
            from ai_reo.tools.docker_exec import docker_executor
            if docker_executor.client:
                info = docker_executor.client.info()
                return {
                    "available": True,
                    "server_version": info.get("ServerVersion", "unknown"),
                    "images_count": info.get("Images", 0),
                    "containers_running": info.get("ContainersRunning", 0),
                }
            return {"available": False, "error": "Docker client not initialized"}
        except Exception as e:
            return {"available": False, "error": str(e)}


# Module-level singleton
tool_health_service = ToolHealthService()
