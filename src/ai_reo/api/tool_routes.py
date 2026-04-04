"""REST endpoints for tool readiness management."""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from ai_reo.tools.health import tool_health_service

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/status")
async def get_tools_status() -> Dict[str, Any]:
    """Return readiness status for all registered tools."""
    status = await tool_health_service.get_status()
    docker_info = await tool_health_service.get_docker_status()

    return {
        "docker": docker_info,
        "tools": {
            name: {
                "name": s.name,
                "ready": s.ready,
                "docker_required": s.docker_required,
                "docker_available": s.docker_available,
                "image": s.image,
                "image_available": s.image_available,
                "error": s.error,
                "description": s.description,
            }
            for name, s in status.items()
        },
    }


@router.post("/setup/environment")
async def setup_environment() -> Dict[str, Any]:
    """Prepare Docker/tool environment prerequisites (paths, Docker network)."""
    report = await tool_health_service.ensure_environment()
    return report


@router.post("/setup")
async def setup_all_tools() -> Dict[str, Any]:
    """Pull/build all missing Docker images for tools."""
    env_report = await tool_health_service.ensure_environment()
    results = await tool_health_service.setup_all()
    return {
        "environment": env_report,
        "results": results,
        "all_ready": all(results.values()),
    }


@router.post("/{tool_name}/setup")
async def setup_tool(tool_name: str) -> Dict[str, Any]:
    """Pull/build the Docker image for a specific tool."""
    try:
        env_report = await tool_health_service.ensure_environment()
        success = await tool_health_service.setup_tool(tool_name)
        return {"tool": tool_name, "success": success, "environment": env_report}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")


@router.post("/{tool_name}/test")
async def test_tool(tool_name: str) -> Dict[str, Any]:
    """Run a quick smoke test on a specific tool to verify it is working."""
    from ai_reo.tools.registry import tool_registry
    from ai_reo.tools.interface import DockerBasedTool
    from ai_reo.tools.docker_exec import docker_executor

    try:
        tool = tool_registry.get_tool(tool_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")

    if isinstance(tool, DockerBasedTool):
        try:
            if not tool.is_docker_available():
                return {"ok": False, "tool": tool_name, "error": "Docker daemon not available"}
            if not tool.is_image_available():
                return {
                    "ok": False,
                    "tool": tool_name,
                    "error": f"Image '{tool.docker_image}' not pulled. Click Setup first.",
                }
            result = docker_executor.execute(
                tool.docker_image,
                tool.smoke_test_cmd if tool.smoke_test_cmd is not None else "echo AI-REO-OK",
                timeout=30,
            )
            if tool.smoke_test_cmd is not None:
                ok = result.get("exit_code", 1) == 0
            else:
                ok = "AI-REO-OK" in result.get("output", "")
            return {"ok": ok, "tool": tool_name, "output": result.get("output", "")[:400]}
        except Exception as e:
            return {"ok": False, "tool": tool_name, "error": str(e)}
    else:
        return {"ok": True, "tool": tool_name, "output": "Built-in tool — no Docker required"}
