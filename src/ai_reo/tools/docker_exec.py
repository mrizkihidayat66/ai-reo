"""Docker execution engine providing an isolated environment for external tools."""

import logging
from pathlib import Path
from typing import Any, Dict

import docker
from docker.errors import DockerException

from ai_reo.config import settings
from ai_reo.exceptions import AiReoError

logger = logging.getLogger(__name__)


class DockerExecutionError(AiReoError):
    """Raised when the docker executor fails."""


class DockerToolExecutor:
    """Executes arbitrary commands inside sandboxed Docker containers."""

    def __init__(self) -> None:
        try:
            self.client = docker.from_env()
        except DockerException as e:
            logger.warning("Docker daemon unavailable: %s", e)
            self.client = None

    def execute(self, image: str, command: str, timeout: int = 120) -> Dict[str, Any]:
        """Run a command inside a specific image mapping the staging binary volume."""
        if not self.client:
            raise DockerExecutionError(
                "Docker daemon is not available. Please ensure Docker Desktop is running."
            )

        staging_dir_path = Path(settings.tools.sessions_dir).expanduser().resolve()
        staging_dir_path.mkdir(parents=True, exist_ok=True)
        staging_dir = str(staging_dir_path)

        # Mount the host's binary staging dir as read/write into /mnt/staging inside container
        volumes = {
            staging_dir: {"bind": "/mnt/staging", "mode": "rw"}
        }

        logger.info(f"Docker Exec [{image}]: {command}")

        try:
            # Docker disallows passing both network and network_mode together.
            run_kwargs: Dict[str, Any] = {
                "image": image,
                "command": ["/bin/sh", "-c", command],
                "volumes": volumes,
                "detach": True,
                # Memory cap for sandboxing; cpu_quota omitted — not supported on all Docker Desktop configs
                "mem_limit": "1g",
            }
            if settings.tools.docker_network:
                run_kwargs["network"] = settings.tools.docker_network
            else:
                run_kwargs["network_mode"] = "bridge"

            container = self.client.containers.run(**run_kwargs)
            
            # Wait for execution with timeout
            result = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            
            container.remove(force=True)
            
            return {
                "exit_code": result["StatusCode"],
                "output": logs
            }
            
        except Exception as e:
            raise DockerExecutionError(f"Secure Docker execution failed: {e}")


    async def execute_with_retry(
        self,
        image: str,
        command: str,
        timeout: int = 120,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        """Execute with exponential backoff retry for transient Docker failures."""
        import asyncio

        last_error: Exception = RuntimeError("No attempts made")
        delay = 1.0
        for attempt in range(max_attempts):
            try:
                return self.execute(image, command, timeout)
            except DockerExecutionError as e:
                last_error = e
                if attempt < max_attempts - 1:
                    logger.warning(
                        "Docker execution attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt + 1, max_attempts, e, delay,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2.0
        raise last_error


docker_executor = DockerToolExecutor()
