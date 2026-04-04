"""Main FastAPI application for AI-REO.

Entry points:
  • HTTP  – REST endpoints (health, ready, info)
  • CLI   – ``ai-reo`` script via ``main()``
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from pathlib import Path

import docker  # type: ignore[import-untyped]
import sqlalchemy
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ai_reo import __version__
from ai_reo.config import settings
from ai_reo.exceptions import (
    AgentError,
    AiReoError,
    BinaryNotFoundError,
    LLMError,
    SessionConflictError,
    SessionNotFoundError,
    ToolError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=settings.server.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ai_reo")


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown tasks and store shared resources in app.state."""
    logger.info("AI-REO v%s starting up…", __version__)

    # 1. Verify storage configuration
    try:
        sessions_dir = settings.tools.sessions_dir
        sessions_dir.mkdir(parents=True, exist_ok=True)
        # Check if we can write to it
        test_file = sessions_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        logger.info("Storage directory verified: %s", sessions_dir)
    except Exception as exc:
        logger.critical("Failed to verify sessions directory '%s': %s", settings.tools.sessions_dir, exc)
        raise RuntimeError(f"Storage directory failure: {exc}")

    # 2. Database engine (lazy – we just use the configured one to verify connectivity)
    from ai_reo.db.engine import engine
    app.state.db_engine = engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection OK: %s", settings.database.database_url)
        app.state.db_ok = True

        # Auto-create tables from ORM models (safe to call on existing schemas)
        from ai_reo.db.engine import Base
        import ai_reo.db.models  # noqa: F401 — ensure models are registered
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created.")

    except Exception as exc:
        logger.warning("Database unavailable at startup: %s", exc)
        app.state.db_ok = False

    # Docker client (optional – tools won't work without it)
    try:
        docker_client = docker.from_env()
        docker_client.ping()
        logger.info("Docker daemon reachable.")
        app.state.docker_client = docker_client
        app.state.docker_ok = True
    except Exception as exc:
        logger.warning("Docker daemon unavailable: %s", exc)
        app.state.docker_client = None
        app.state.docker_ok = False

    # Register all tools into the global registry
    from ai_reo.tools.registry import tool_registry
    from ai_reo.tools.basic import (
        FsReadTool, FsWriteTool, StringsExtractTool, BinaryInfoTool,
        EntropyAnalysisTool, HexDumpTool, FileTypeTool, SharedWriteTool,
        SharedListTool, PEFileTool,
    )
    from ai_reo.tools.re_tools import (
        Radare2Tool, ObjdumpTool, ReadelfTool, NmTool, AngrTool, UpxTool,
        CapaTool, YaraTool, GhidraHeadlessTool, DieTool, LiefTool, FlossTool,
        CheksecTool, UnipackerTool,
        # New tools added in re-evaluation
        CapeAnalysisTool, FridaTool, QilingTool, PeSieveTool, HollowsHunterTool,
        UnlicenseTool, Volatility3Tool, JadxTool, ApktoolTool, ApkidTool, AflplusplusTool,
    )
    tool_registry.register(FsReadTool())
    tool_registry.register(FsWriteTool())
    tool_registry.register(StringsExtractTool())
    tool_registry.register(BinaryInfoTool())
    tool_registry.register(EntropyAnalysisTool())
    tool_registry.register(HexDumpTool())
    tool_registry.register(FileTypeTool())
    tool_registry.register(SharedWriteTool())
    tool_registry.register(SharedListTool())
    tool_registry.register(PEFileTool())
    tool_registry.register(Radare2Tool())
    tool_registry.register(ObjdumpTool())
    tool_registry.register(ReadelfTool())
    tool_registry.register(NmTool())
    tool_registry.register(AngrTool())
    tool_registry.register(UpxTool())
    tool_registry.register(CapaTool())
    tool_registry.register(YaraTool())
    tool_registry.register(GhidraHeadlessTool())
    tool_registry.register(DieTool())
    tool_registry.register(LiefTool())
    tool_registry.register(FlossTool())
    tool_registry.register(CheksecTool())
    tool_registry.register(UnipackerTool())
    # New additions
    tool_registry.register(CapeAnalysisTool())
    tool_registry.register(FridaTool())
    tool_registry.register(QilingTool())
    tool_registry.register(PeSieveTool())
    tool_registry.register(HollowsHunterTool())
    tool_registry.register(UnlicenseTool())
    tool_registry.register(Volatility3Tool())
    tool_registry.register(JadxTool())
    tool_registry.register(ApktoolTool())
    tool_registry.register(ApkidTool())
    tool_registry.register(AflplusplusTool())
    logger.info("Tool registry initialised with %d tools.", len(tool_registry._tools))

    yield  # hand off to the application

    logger.info("AI-REO shutting down.")
    engine.dispose()
    if app.state.docker_client:
        app.state.docker_client.close()


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Reverse Engineering Orchestrator",
    description=(
        "A local-first, chat-driven platform that automates binary analysis "
        "using a team of specialized AI agents."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production (e.g., ["http://localhost:5173"])
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request-logging middleware (adds correlation IDs to every request)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Any:
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "[%s] %s %s → %d (%.1f ms)",
        correlation_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


def _error_body(exc: AiReoError, code: str) -> dict[str, Any]:
    return {"error": code, "message": exc.message, "details": exc.details}


def _safe_exception_message(exc: Exception) -> str:
    """Return a compact, ASCII-safe exception message for transport/log echoing."""
    message = str(exc)
    safe = message.encode("ascii", errors="replace").decode("ascii")
    return safe[:500] if safe else "Internal server error"


@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(
    _request: Request, exc: SessionNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=_error_body(exc, "SESSION_NOT_FOUND"),
    )


@app.exception_handler(SessionConflictError)
async def session_conflict_handler(
    _request: Request, exc: SessionConflictError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=_error_body(exc, "SESSION_CONFLICT"),
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(
    _request: Request, exc: ValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_body(exc, "VALIDATION_ERROR"),
    )


@app.exception_handler(ToolError)
async def tool_error_handler(_request: Request, exc: ToolError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=_error_body(exc, "TOOL_ERROR"),
    )


@app.exception_handler(AgentError)
async def agent_error_handler(_request: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(exc, "AGENT_ERROR"),
    )


@app.exception_handler(LLMError)
async def llm_error_handler(_request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=_error_body(exc, "LLM_ERROR"),
    )


@app.exception_handler(BinaryNotFoundError)
async def binary_not_found_handler(
    _request: Request, exc: BinaryNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=_error_body(exc, "BINARY_NOT_FOUND"),
    )


@app.exception_handler(AiReoError)
async def generic_ai_reo_error_handler(
    _request: Request, exc: AiReoError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(exc, "INTERNAL_ERROR"),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "INTERNAL_SERVER_ERROR", "message": _safe_exception_message(exc)},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from ai_reo.api.routes import router as sessions_router, runs_router
from ai_reo.api.provider_routes import router as providers_router
from ai_reo.api.tool_routes import router as tools_router
from ai_reo.api.skills_routes import router as skills_router
from ai_reo.api.agents_routes import router as agents_router
app.include_router(sessions_router)
app.include_router(providers_router)
app.include_router(runs_router)
app.include_router(tools_router)
app.include_router(skills_router)
app.include_router(agents_router)


@app.get("/", summary="API root information")
async def root() -> dict[str, str]:
    """Return basic information about the running AI-REO instance."""
    return {
        "name": "AI Reverse Engineering Orchestrator (AI-REO)",
        "version": __version__,
        "docs": "/docs",
    }


@app.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Always returns 200 while the process is alive."""
    return {"status": "ok", "version": __version__}


@app.get("/ready", summary="Readiness probe")
async def ready(request: Request) -> JSONResponse:
    """Returns 200 only when both the database and Docker daemon are reachable."""
    db_ok: bool = getattr(request.app.state, "db_ok", False)
    docker_ok: bool = getattr(request.app.state, "docker_ok", False)

    checks = {
        "database": "ok" if db_ok else "unavailable",
        "docker": "ok" if docker_ok else "unavailable",
    }
    ready = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=http_status,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )



# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the uvicorn server – used by the ``ai-reo`` CLI script."""
    import os
    import sys
    import socket
    import psutil
    import uvicorn

    current_pid = os.getpid()
    running_pids = []

    # 1. Check if AI-REO is already running anywhere
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
            if not cmdline:
                continue

            cmd_str = " ".join(cmdline)
            is_ai_reo = False
            
            # Pattern 1: explicitly running via uvicorn
            if "uvicorn" in cmd_str and "ai_reo.main:app" in cmd_str:
                is_ai_reo = True
            # Pattern 2: running via the ai-reo CLI entrypoint
            elif any(arg.endswith("ai-reo") or arg.endswith("ai-reo.exe") for arg in cmdline):
                if "python" in cmdline[0].lower() or cmdline[0].endswith("ai-reo.exe"):
                    is_ai_reo = True
                    
            if is_ai_reo and proc.info['pid'] != current_pid:
                running_pids.append(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if running_pids:
        pid_list = ", ".join(str(p) for p in running_pids)
        print(f"ERROR: AI-REO is already running in another process (PID: {pid_list}).")
        print("Please terminate the existing instance before starting a new one.")
        if sys.platform == "win32":
            kill_cmds = [f"taskkill /PID {p} /F /T" for p in running_pids]
            print("\nTo forcefully stop it on Windows, you can run:\n  " + "\n  ".join(kill_cmds))
        else:
            kill_cmds = [f"kill -9 {p}" for p in running_pids]
            print("\nTo forcefully stop it, you can run:\n  " + "\n  ".join(kill_cmds))
        sys.exit(1)

    # 2. Check if the required port is actually available
    host = settings.server.host
    port = settings.server.port
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            blocking_pids = []
            blocking_names = []
            for c in psutil.net_connections(kind='inet'):
                if c.laddr and c.laddr.port == port and c.status == 'LISTEN':
                    if c.pid:
                        blocking_pids.append(c.pid)
                        try:
                            blocking_names.append(psutil.Process(c.pid).name())
                        except psutil.Error:
                            blocking_names.append("Unknown")
            
            pid_str = ", ".join(str(p) for p in blocking_pids) or "Unknown"
            name_str = ", ".join(blocking_names) or "Unknown"
            
            print(f"ERROR: Port {port} is already in use by another application (PID: {pid_str}, Name: {name_str}).")
            print("AI-REO cannot start unless this port is free.")
            print("Please terminate that application, or change AI_REO_PORT in your .env file to a different port (e.g., 8080).")
            if sys.platform == "win32" and blocking_pids:
                print(f"\nTo forcefully stop it on Windows, you can run:\n  taskkill /PID {blocking_pids[0]} /F /T")
            sys.exit(1)

    # 3. Start the application
    uvicorn.run(
        "ai_reo.main:app",
        host=host,
        port=port,
        log_level=settings.server.log_level,
        reload=False,
    )

def diag() -> None:
    """Diagnostic utility — shows port, Docker, and process status."""
    import os
    import socket
    import psutil

    port = settings.server.port
    host = settings.server.host

    print(f"=== AI-REO Diagnostic (target: {host}:{port}) ===\n")

    # 1. Port check
    print(f"[Port {port}]")
    found_port = False
    for c in psutil.net_connections(kind="inet"):
        if c.laddr and c.laddr.port == port:
            pid = c.pid
            print(f"  PID {pid} is using port {port} (status: {c.status})")
            try:
                if pid:
                    p = psutil.Process(pid)
                    print(f"    → Name: {p.name()}, Cmd: {' '.join(p.cmdline()[:5])}")
            except psutil.Error as e:
                print(f"    → Error: {e}")
            found_port = True
    if not found_port:
        print("  Port is free ✓")

    # 2. Docker check
    print(f"\n[Docker]")
    try:
        import docker as docker_lib
        client = docker_lib.from_env()
        client.ping()
        print("  Docker daemon: reachable ✓")
        images = client.images.list()
        re_images = [
            img.tags[0] for img in images
            if img.tags and any(
                kw in img.tags[0] for kw in ("radare", "remnux", "ghidra", "objdump")
            )
        ]
        if re_images:
            print(f"  RE tool images found: {', '.join(re_images)}")
        else:
            print("  No RE tool images found. Run tool setup from the UI.")
    except Exception as e:
        print(f"  Docker daemon: unavailable ✗ ({e})")

    # 3. AI-REO processes
    print(f"\n[AI-REO Processes]")
    current_pid = os.getpid()
    found_procs = False
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline)
            if ("ai_reo" in cmd_str or "ai-reo" in cmd_str) and proc.info["pid"] != current_pid:
                print(f"  PID {proc.info['pid']}: {cmd_str[:100]}")
                found_procs = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if not found_procs:
        print("  No running AI-REO processes found.")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
