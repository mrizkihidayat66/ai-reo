import asyncio
import io
import json
import hashlib
import logging
import re
import shutil
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ai_reo.config import settings
from ai_reo.agents import graph as agent_graph
from ai_reo.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    GraphExportResponse,
    SessionCreateRequest,
    SessionRenameRequest,
    SessionResponse,
    ToolInvokeRequest,
    BinaryUploadResponse,
    ZipUploadResponse,
)
from ai_reo.api.websockets import manager as ws_manager
from ai_reo.db.engine import get_db
from ai_reo.db.repositories import (
    KnowledgeGraphRepository,
    LLMInteractionRepository,
    SessionRepository,
    ToolExecutionRepository,
)
from ai_reo.db.services import (
    KnowledgeGraphService,
    SessionService,
    ToolExecutionService,
)
from ai_reo.tools.registry import tool_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Separate router for non-session-prefixed endpoints (auto-run)
runs_router = APIRouter(prefix="/runs", tags=["runs"])

# ---------------------------------------------------------------------------
# Per-session asyncio.Event-based pause mechanism
# set() = running, cleared = paused
# ---------------------------------------------------------------------------

_session_run_events: Dict[str, asyncio.Event] = {}


# ---------------------------------------------------------------------------
# Dependency injection factory functions
# ---------------------------------------------------------------------------

def get_session_service(db: Session = Depends(get_db)) -> SessionService:
    return SessionService(db, SessionRepository(db))


def get_kg_service(db: Session = Depends(get_db)) -> KnowledgeGraphService:
    return KnowledgeGraphService(db, KnowledgeGraphRepository(db))


def get_tool_service(db: Session = Depends(get_db)) -> ToolExecutionService:
    return ToolExecutionService(db, ToolExecutionRepository(db))


# ---------------------------------------------------------------------------
# Helper: build a SessionResponse from an ORM object
# ---------------------------------------------------------------------------

def _session_to_response(session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        name=session.name,
        status=session.status,
        binary_path=session.binary_path,
        binary_hash=session.binary_hash,
        working_dir=session.working_dir,
        created_at=session.created_at.isoformat(),
    )


def _ascii_filename_fragment(value: str) -> str:
    """Convert a free-form session name to an ASCII-safe filename fragment."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    collapsed = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text).strip("._-")
    return collapsed[:50] or "session"


def _content_disposition_filename(raw_name: str) -> str:
    """Build a standards-friendly Content-Disposition filename value."""
    safe_ascii = _ascii_filename_fragment(raw_name)
    utf8_name = quote(f"ai-reo_{raw_name}.zip", safe="")
    return (
        f'attachment; filename="ai-reo_{safe_ascii}.zip"; '
        f"filename*=UTF-8''{utf8_name}"
    )


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=List[SessionResponse])
def list_sessions(
    svc: SessionService = Depends(get_session_service),
) -> List[SessionResponse]:
    """Return all sessions ordered by most recent first."""
    sessions = svc.list_sessions()
    return [_session_to_response(s) for s in sessions]


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    req: SessionCreateRequest,
    svc: SessionService = Depends(get_session_service),
) -> SessionResponse:
    """Create a new analysis session.

    Multiple sessions can reference the same binary — no conflict.
    """
    # Derive a default name from the filename if not provided
    name = req.name or f"{Path(req.binary_path).name} @ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

    # Create the DB record first to get the session ID
    session = svc.create_session(
        binary_path=req.binary_path,
        binary_hash=req.binary_hash,
        name=name,
        working_dir=req.working_dir,
    )

    # Create the per-session working directory
    sessions_root = Path(settings.tools.sessions_dir).resolve()
    session_dir = sessions_root / session.id
    workspace_dir = session_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Update the DB record with the resolved working directory
    session.working_dir = str(session_dir)
    # Commit via the service repo's DB session
    svc.repo.db.commit()
    svc.repo.db.refresh(session)

    return _session_to_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str, svc: SessionService = Depends(get_session_service)
) -> SessionResponse:
    """Retrieve metadata about a session."""
    session = svc.load_session(session_id)
    return _session_to_response(session)


@router.patch("/{session_id}", response_model=SessionResponse)
def rename_session(
    session_id: str,
    req: SessionRenameRequest,
    svc: SessionService = Depends(get_session_service),
) -> SessionResponse:
    """Rename a session."""
    session = svc.rename_session(session_id, req.name)
    return _session_to_response(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    svc: SessionService = Depends(get_session_service),
):
    """Delete a session and its working directory."""
    session = svc.load_session(session_id)

    # Remove working directory from disk
    if session.working_dir:
        working_path = Path(session.working_dir)
        if working_path.exists():
            shutil.rmtree(working_path, ignore_errors=True)

    svc.delete_session(session_id)


# ---------------------------------------------------------------------------
# Binary upload — writes binary into a session's working directory
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=BinaryUploadResponse, status_code=201)
async def upload_binary(
    file: UploadFile = File(...),
    session_id: str = Query(None, description="Target session ID. If omitted, binary is placed in a temp staging area."),
) -> BinaryUploadResponse:
    """Upload a binary into a session's working directory, deriving its SHA-256 hash."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    # Determine destination directory
    if session_id:
        session_dir = Path(settings.tools.sessions_dir).resolve() / session_id / "workspace"
    else:
        session_dir = Path(settings.tools.sessions_dir).resolve() / "_staging"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Secure filename against path traversal
    safe_filename = Path(file.filename).name
    destination = session_dir / safe_filename

    size = 0
    sha256_hash = hashlib.sha256()

    try:
        with open(destination, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                sha256_hash.update(chunk)
                buffer.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stream binary: {e}")

    return BinaryUploadResponse(
        filename=safe_filename,
        binary_hash=sha256_hash.hexdigest(),
        size_bytes=size,
    )


@router.post("/upload-zip", response_model=ZipUploadResponse, status_code=201)
async def upload_zip(
    file: UploadFile = File(...),
    session_id: str = Query(None, description="Target session ID. If omitted, files are placed in a temp staging area."),
) -> ZipUploadResponse:
    """Upload a ZIP archive, extract all files into the session's binary directory."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    fname_lower = (file.filename or "").lower()
    if not fname_lower.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")

    # Read entire zip into memory (capped at configured limit)
    from ai_reo.config import settings
    MAX_ZIP_SIZE = settings.server.max_upload_size_mb * 1024 * 1024
    data = await file.read()
    if len(data) > MAX_ZIP_SIZE:
        raise HTTPException(status_code=400, detail=f"ZIP file exceeds {settings.server.max_upload_size_mb} MB limit.")

    import io as _io
    try:
        zf = zipfile.ZipFile(_io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive.")

    # Determine destination directory
    if session_id:
        session_dir = Path(settings.tools.sessions_dir).resolve() / session_id / "workspace"
    else:
        session_dir = Path(settings.tools.sessions_dir).resolve() / "_staging"
    session_dir.mkdir(parents=True, exist_ok=True)

    extracted: List[str] = []
    total_size = 0
    sha256_hash = hashlib.sha256()

    for info in zf.infolist():
        # Skip directories
        if info.is_dir():
            continue

        name = info.filename
        # Path traversal guard
        if ".." in name or name.startswith("/") or name.startswith("\\"):
            continue
        # Skip macOS resource forks and hidden files
        basename = Path(name).name
        if basename.startswith(".") or "__MACOSX" in name:
            continue

        # Flatten: extract just the filename (ignore zip internal directory paths)
        safe_name = Path(basename).name
        if not safe_name:
            continue

        dest = session_dir / safe_name
        file_data = zf.read(info.filename)
        total_size += len(file_data)
        sha256_hash.update(file_data)
        dest.write_bytes(file_data)
        extracted.append(safe_name)

    zf.close()

    if not extracted:
        raise HTTPException(status_code=400, detail="ZIP archive contains no usable files.")

    return ZipUploadResponse(
        filenames=extracted,
        binary_hash=sha256_hash.hexdigest(),
        total_size_bytes=total_size,
    )


@router.patch("/upload/{session_id}/finalize", response_model=SessionResponse)
def finalize_upload(
    session_id: str,
    binary_hash: str = Query(..., description="The real SHA-256 hash computed after upload."),
    svc: SessionService = Depends(get_session_service),
) -> SessionResponse:
    """Update the session record with the real binary hash after upload completes."""
    session = svc.load_session(session_id)
    session.binary_hash = binary_hash
    session.status = "ready"
    svc.repo.db.commit()
    svc.repo.db.refresh(session)
    return _session_to_response(session)


# ---------------------------------------------------------------------------
# Export — ZIP download of session data + binary
# ---------------------------------------------------------------------------

@router.get("/{session_id}/export")
def export_session(
    session_id: str,
    svc: SessionService = Depends(get_session_service),
    kg: KnowledgeGraphService = Depends(get_kg_service),
    tool_svc: ToolExecutionService = Depends(get_tool_service),
):
    """Download a ZIP archive containing the session binary, knowledge graph, and logs."""
    session = svc.load_session(session_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Session metadata
        meta = {
            "id": session.id,
            "name": session.name,
            "binary_path": session.binary_path,
            "binary_hash": session.binary_hash,
            "status": session.status,
            "created_at": session.created_at.isoformat(),
        }
        zf.writestr("session.json", json.dumps(meta, indent=2))

        # 2. Knowledge graph
        graph_data = kg.export_graph(session_id)
        zf.writestr("knowledge_graph.json", json.dumps(graph_data, indent=2, default=str))

        # 3. Tool execution log
        tool_history = tool_svc.get_history(session_id)
        tools_data = [
            {
                "id": t.id,
                "tool_name": t.tool_name,
                "invoked_by": t.invoked_by_agent,
                "command": t.command,
                "stdout": t.stdout,
                "stderr": t.stderr,
                "exit_code": t.exit_code,
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            }
            for t in tool_history
        ]
        zf.writestr("tool_executions.json", json.dumps(tools_data, indent=2, default=str))

        # 4. Workspace files (if they exist on disk)
        if session.working_dir:
            workspace_dir = Path(session.working_dir) / "workspace"
            if not workspace_dir.exists():
                workspace_dir = Path(session.working_dir) / "binary"  # compat with old sessions
            if workspace_dir.exists():
                for fpath in workspace_dir.iterdir():
                    if fpath.is_file():
                        zf.write(fpath, f"workspace/{fpath.name}")

    buf.seek(0)
    raw_name = session.name or session.id
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_filename(raw_name)},
    )


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

@router.get("/{session_id}/graph", response_model=GraphExportResponse)
def get_graph(
    session_id: str, svc: KnowledgeGraphService = Depends(get_kg_service)
) -> GraphExportResponse:
    """Download the current state of the extracted Knowledge Graph."""
    export = svc.export_graph(session_id)
    return GraphExportResponse(**export)


@router.post("/{session_id}/kg/import")
def import_knowledge_graph(
    session_id: str,
    payload: Dict[str, Any],
    svc: SessionService = Depends(get_session_service),
    kg: KnowledgeGraphService = Depends(get_kg_service),
) -> Dict[str, Any]:
    """Import and merge nodes from an exported Knowledge Graph JSON into this session.

    Deduplicates by node name+type to avoid inflating the graph with redundant entries.
    """
    # Validate target session exists
    svc.load_session(session_id)

    nodes_to_import = payload.get("nodes", [])
    if not isinstance(nodes_to_import, list):
        raise HTTPException(status_code=400, detail="Payload must have a 'nodes' list.")

    # Build dedup set from existing nodes (name+type)
    existing = kg.export_graph(session_id)
    existing_keys = {
        (n.get("name", ""), n.get("type", ""))
        for n in existing.get("nodes", [])
    }

    imported = 0
    skipped = 0
    for node in nodes_to_import:
        key = (node.get("name", ""), node.get("type", ""))
        if key in existing_keys or (not key[0] and not key[1]):
            skipped += 1
            continue
        kg.repo.add_node(
            session_id=session_id,
            node_type=node.get("type") or "unknown",
            created_by_agent=node.get("created_by_agent") or "import",
            address=node.get("address"),
            name=node.get("name"),
            data=node.get("data", {}),
        )
        existing_keys.add(key)
        imported += 1

    return {"imported": imported, "skipped": skipped, "session_id": session_id}


# ---------------------------------------------------------------------------
# Analysis Pipeline
# ---------------------------------------------------------------------------

@router.post("/{session_id}/analyze", response_model=AnalyzeResponse)
async def analyze_session(
    session_id: str,
    req: AnalyzeRequest,
    svc: SessionService = Depends(get_session_service),
    kg: KnowledgeGraphService = Depends(get_kg_service),
    tool_svc: ToolExecutionService = Depends(get_tool_service),
) -> AnalyzeResponse:
    """Trigger the LangGraph workflow to autonomously analyze the binary."""

    session = svc.load_session(session_id)

    # *** Fix Bug Class 5: set status to active ***
    svc.repo.update_status(session_id, "active")

    # Persist the user's goal message so it appears in chat history on reload
    try:
        LLMInteractionRepository(svc.repo.db).log_interaction(
            session_id=session_id,
            agent_name="user",
            provider="user",
            model="-",
            prompt="",
            response=req.goal,
            token_count=max(1, len(req.goal) // 4),
        )
    except Exception:
        logger.warning("Failed to persist user message for session %s", session_id)

    graph_data = kg.export_graph(session_id)
    graph_str = json.dumps(graph_data["nodes"]) if graph_data["nodes"] else "Empty Graph"

    # Build a summary of tools already run in previous invocations so agents
    # don't redundantly re-execute them.
    tool_history = tool_svc.get_history(session_id)
    completed_tools = ", ".join(
        sorted({t.tool_name for t in tool_history if t.exit_code == 0})
    ) if tool_history else ""

    initial_state = {
        "session_id": session_id,
        "messages": [{"role": "user", "content": req.goal}],
        "active_agent": "classify_intent",
        "current_goal": req.goal,
        "kg_summary": graph_str,
        "final_report": "",
        "error": "",
        # Structured completion signals
        "last_result": None,
        "findings_count": len(graph_data.get("nodes", [])),
        "consecutive_empty_steps": 0,
        # Previously completed tools (anti-redundancy)
        "completed_tools": completed_tools,
    }

    final_state = initial_state

    # Set up pause event for this session
    pause_event = asyncio.Event()
    pause_event.set()  # Start in running state
    _session_run_events[session_id] = pause_event

    try:
        async for output in agent_graph.app_graph.astream(
            initial_state, {"recursion_limit": agent_graph.GRAPH_MAX_RECURSION_LIMIT}
        ):
            # Check pause state — yields to event loop if paused
            if not pause_event.is_set():
                await ws_manager.broadcast_to_session(session_id, {
                    "type": "status", "message": "Execution paused.",
                })
                svc.repo.update_status(session_id, "paused")
                await pause_event.wait()  # Block until resumed
                await ws_manager.broadcast_to_session(session_id, {
                    "type": "status", "message": "Execution resumed.",
                })

            node_name = list(output.keys())[0]
            node_state = output[node_name]
            final_state = node_state

            await ws_manager.broadcast_to_session(session_id, {
                "type": "agent_state_override",
                "node_executed": node_name,
                "active_agent": final_state.get("active_agent"),
                "current_goal": final_state.get("current_goal"),
                "findings_count": final_state.get("findings_count", 0),
            })

    except Exception as e:
        err_str = str(e)
        logger.error("Analysis pipeline error for session %s: %s", session_id, e)
        svc.repo.update_status(session_id, "error")

        # Translate internal errors to user-friendly messages
        if "GRAPH_RECURSION_LIMIT" in err_str or "recursion_limit" in err_str.lower():
            user_message = (
                "Analysis reached maximum steps. The agents have gathered findings — "
                "generating the final report from what was found."
            )
        elif "No LLM providers" in err_str or "no provider" in err_str.lower():
            user_message = "No LLM provider configured. Please visit Settings to add one."
        else:
            user_message = "An internal error occurred during analysis. Please try again."

        await ws_manager.broadcast_to_session(session_id, {
            "type": "error",
            "message": user_message,
            "technical_detail": err_str[:200],
        })
        raise HTTPException(status_code=500, detail=user_message)

    finally:
        _session_run_events.pop(session_id, None)

    active_agent = final_state.get("active_agent", "documentation")
    svc.update_workflow_checkpoint(session_id, active_agent)

    if active_agent == "documentation" or final_state.get("final_report"):
        svc.complete_session(session_id)

    # Notify the UI that the pipeline has finished
    await ws_manager.broadcast_to_session(session_id, {
        "type": "analysis_complete",
        "status": "completed" if final_state.get("final_report") else "paused_for_input",
        "active_agent": active_agent,
    })

    return AnalyzeResponse(
        status="completed" if final_state.get("final_report") else "paused_for_input",
        final_report=final_state.get("final_report"),
        active_agent=active_agent,
    )


# ---------------------------------------------------------------------------
# Chat History
# ---------------------------------------------------------------------------

@router.get("/{session_id}/history")
def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return a merged, time-ordered timeline of LLM interactions AND tool executions."""
    llm_repo = LLMInteractionRepository(db)
    tool_repo = ToolExecutionRepository(db)

    # LLM interaction entries — type is 'chat_message' for all (agent field drives rendering)
    interactions = llm_repo.get_history(session_id)
    llm_entries = [
        {
            "id": i.id,
            "type": "chat_message",
            "agent": i.agent_name,
            "response": i.response,
            "timestamp": i.timestamp.isoformat() if i.timestamp else "",
        }
        for i in interactions
    ]

    # Tool execution entries — type is 'tool_result'
    executions = tool_repo.get_history(session_id)
    tool_entries = [
        {
            "id": t.id,
            "type": "tool_result",
            "agent": t.invoked_by_agent,
            "tool": t.tool_name,
            "result_preview": (t.stdout or "")[:8000],
            "exit_code": t.exit_code,
            "timestamp": t.timestamp.isoformat() if t.timestamp else "",
        }
        for t in executions
    ]

    # Merge and sort chronologically
    merged = sorted(llm_entries + tool_entries, key=lambda x: x.get("timestamp", ""))
    return merged


# ---------------------------------------------------------------------------
# Human-in-the-Loop Tool Override
# ---------------------------------------------------------------------------

@router.post("/{session_id}/tools")
async def invoke_tool_manually(
    session_id: str,
    req: ToolInvokeRequest,
    tool_svc: ToolExecutionService = Depends(get_tool_service),
) -> Dict[str, Any]:
    """Manual tool override for human-in-the-loop execution."""
    try:
        await ws_manager.broadcast_to_session(session_id, {"type": "tool_start", "tool": req.tool_name})

        res = await tool_registry.dispatch(req.tool_name, session_id, req.kwargs)

        tool_svc.log(
            session_id=session_id,
            tool_name=req.tool_name,
            invoked_by="human_api",
            command=req.kwargs,
            stdout=str(res.get("output", "")),
            stderr=str(res.get("error", "")),
            exit_code=int(res.get("exit_code", 0)),
        )

        await ws_manager.broadcast_to_session(session_id, {"type": "tool_end", "tool": req.tool_name, "exit_code": int(res.get("exit_code", 0))})
        return {"result": res}

    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/{session_id}/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Bi-directional WebSocket route for real-time UI updates."""
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                cmd = payload.get("command")
                if cmd in ("pause", "resume", "toggle_pause"):
                    event = _session_run_events.get(session_id)
                    currently_running = event.is_set() if event else False
                    # Determine desired state
                    do_pause = (cmd == "pause") or (cmd == "toggle_pause" and currently_running)
                    if do_pause:
                        if event:
                            event.clear()
                        msg = "⏸ Execution paused by user."
                        paused = True
                    else:
                        if event:
                            event.set()
                        msg = "▶ Execution resumed."
                        paused = False
                    await ws_manager.broadcast_to_session(session_id, {
                        "type": "pause_state",
                        "paused": paused,
                        "message": msg,
                    })
                    # Persist pause/resume event to history
                    try:
                        from ai_reo.db.engine import get_db_session
                        with get_db_session() as _pause_db:
                            LLMInteractionRepository(_pause_db).log_interaction(
                                session_id=session_id,
                                agent_name="system",
                                provider="system",
                                model="-",
                                prompt="",
                                response=msg,
                                token_count=1,
                            )
                    except Exception:
                        pass
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)


# ---------------------------------------------------------------------------
# Auto-run CTF Test
# ---------------------------------------------------------------------------

@runs_router.post("/ctf-test")
def auto_run_ctf_test(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Automated CTF test: creates a session from tmp/CTF_Level5.exe and returns it.

    The frontend navigates to the session dashboard and triggers analyze automatically.
    """
    # Locate the test binary
    project_root = Path(__file__).resolve().parents[3]  # ai-reo/
    test_binary = project_root / "tmp" / "CTF_Level5.exe"
    if not test_binary.exists():
        raise HTTPException(status_code=404, detail=f"Test binary not found at {test_binary}")

    # Create the session record
    svc = SessionService(db, SessionRepository(db))
    name = f"[AutoRun] CTF Level 5 - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    session = svc.create_session(
        binary_path="CTF_Level5.exe",
        binary_hash="pending",
        name=name,
    )

    # Create session working directory and copy binary
    sessions_root = Path(settings.tools.sessions_dir).resolve()
    session_dir = sessions_root / session.id
    workspace_dir = session_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    dest = workspace_dir / "CTF_Level5.exe"
    shutil.copy2(str(test_binary), str(dest))

    # Compute real hash
    sha256 = hashlib.sha256()
    with open(dest, "rb") as f:
        while chunk := f.read(1024 * 1024):
            sha256.update(chunk)
    real_hash = sha256.hexdigest()

    # Finalize session record
    session.binary_hash = real_hash
    session.working_dir = str(session_dir)
    session.status = "ready"
    db.commit()
    db.refresh(session)

    # Build the structured CTF goal
    ctf_goal = (
        "You are solving a CTF (Capture The Flag) binary challenge. "
        "The binary is CTF_Level5.exe, located in your session's binary directory.\n\n"
        "Solve it step by step:\n"
        "1. Identify binary type, architecture, and packing (file headers, entropy analysis)\n"
        "2. Extract all printable strings — look for flags, hints, encoded text\n"
        "3. Disassemble the main() function and map the control flow\n"
        "4. Identify any string comparison operations or password-check logic\n"
        "5. Determine the correct input or hardcoded flag\n"
        "6. Report the flag or required input to solve the challenge\n\n"
        "Return each discovery as a structured finding. "
        "At the end, synthesize a final report with the flag."
    )

    return {
        "session_id": session.id,
        "session_name": name,
        "binary_hash": real_hash,
        "ctf_goal": ctf_goal,
        "status": "ready",
    }

