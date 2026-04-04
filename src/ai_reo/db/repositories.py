"""Data Access Object (DAO) repositories for isolating database logic."""

from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from ai_reo.db.models import (
    KnowledgeGraphNode,
    LLMInteraction,
    Session as AnalysisSession,
    ToolExecution,
)
from ai_reo.exceptions import SessionConflictError, SessionNotFoundError


class SessionRepository:
    """Repository for managing Analysis Sessions."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def create(self, binary_path: str, binary_hash: str, name: Optional[str] = None, working_dir: Optional[str] = None) -> AnalysisSession:
        """Create a new analysis session."""
        session = AnalysisSession(
            binary_path=binary_path,
            binary_hash=binary_hash,
            name=name,
            working_dir=working_dir,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(self, session_id: str) -> AnalysisSession:
        """Retrieve a session by ID, or raise SessionNotFoundError."""
        session = self.db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()
        if not session:
            raise SessionNotFoundError(f"Session id {session_id} not found.")
        return session

    def list_all(self) -> list:
        """Return all sessions ordered by most recent first."""
        return (
            self.db.query(AnalysisSession)
            .order_by(AnalysisSession.created_at.desc())
            .all()
        )

    def delete(self, session_id: str) -> None:
        """Delete a session by ID."""
        session = self.get(session_id)
        self.db.delete(session)
        self.db.commit()

    def rename(self, session_id: str, name: str) -> AnalysisSession:
        """Update the display name of a session."""
        session = self.get(session_id)
        session.name = name
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_status(
        self, session_id: str, status: str, state_id: Optional[str] = None
    ) -> AnalysisSession:
        """Update the status and optionally the workflow state ID."""
        session = self.get(session_id)
        session.status = status
        if state_id:
            session.current_workflow_state_id = state_id
        self.db.commit()
        self.db.refresh(session)
        return session


class KnowledgeGraphRepository:
    """Repository for managing Knowledge Graph Nodes."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def add_node(
        self,
        session_id: str,
        node_type: str,
        created_by_agent: str,
        address: Optional[str] = None,
        name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeGraphNode:
        """Add a new node to the knowledge graph."""
        node = KnowledgeGraphNode(
            session_id=session_id,
            node_type=node_type,
            address=address,
            name=name,
            data=data or {},
            created_by_agent=created_by_agent,
        )
        self.db.add(node)
        self.db.commit()
        self.db.refresh(node)
        return node

    def get_nodes_by_type(self, session_id: str, node_type: str) -> List[KnowledgeGraphNode]:
        """Fetch all nodes of a specific type in a session."""
        return (
            self.db.query(KnowledgeGraphNode)
            .filter(
                KnowledgeGraphNode.session_id == session_id,
                KnowledgeGraphNode.node_type == node_type,
            )
            .all()
        )

    def find_node_by_address(
        self, session_id: str, address: str
    ) -> Optional[KnowledgeGraphNode]:
        """Find a single node at a specific address in a session."""
        return (
            self.db.query(KnowledgeGraphNode)
            .filter(
                KnowledgeGraphNode.session_id == session_id,
                KnowledgeGraphNode.address == address,
            )
            .first()
        )

    def delete_node(self, node_id: str) -> bool:
        """Delete a single node by its ID. Returns True if deleted, False if not found."""
        node = self.db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.id == node_id).first()
        if not node:
            return False
        self.db.delete(node)
        self.db.commit()
        return True

    def bulk_delete_nodes(self, node_ids: List[str]) -> int:
        """Delete multiple nodes by ID. Returns the count deleted."""
        deleted = (
            self.db.query(KnowledgeGraphNode)
            .filter(KnowledgeGraphNode.id.in_(node_ids))
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return deleted

    def delete_edge(self, source_node_id: str, target_node_id: str, relationship: str) -> bool:
        """Remove a logical edge stored in the source node's JSON data."""
        node = self.db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.id == source_node_id).first()
        if not node:
            return False
        edges = (node.data or {}).get("edges", [])
        new_edges = [
            e for e in edges
            if not (e.get("target") == target_node_id and e.get("relationship") == relationship)
        ]
        if len(new_edges) == len(edges):
            return False
        node.data = {**node.data, "edges": new_edges}
        self.db.commit()
        return True


class ToolExecutionRepository:
    """Repository for tracking tool execution logs."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def log_execution(
        self,
        session_id: str,
        tool_name: str,
        invoked_by: str,
        command: Dict[str, Any],
        stdout: Optional[str],
        stderr: Optional[str],
        exit_code: int,
    ) -> ToolExecution:
        """Log a tool execution to the database."""
        exec_record = ToolExecution(
            session_id=session_id,
            tool_name=tool_name,
            invoked_by_agent=invoked_by,
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
        self.db.add(exec_record)
        self.db.commit()
        self.db.refresh(exec_record)
        return exec_record

    def get_history(self, session_id: str) -> List[ToolExecution]:
        """Retrieve execution history for a session."""
        return (
            self.db.query(ToolExecution)
            .filter(ToolExecution.session_id == session_id)
            .order_by(ToolExecution.timestamp.asc())
            .all()
        )


class LLMInteractionRepository:
    """Repository for tracing LLM interactions."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def log_interaction(
        self,
        session_id: str,
        agent_name: str,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        token_count: int,
    ) -> LLMInteraction:
        """Save a complete LLM interaction record."""
        interaction = LLMInteraction(
            session_id=session_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            prompt=prompt,
            response=response,
            token_count=token_count,
        )
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def get_history(self, session_id: str) -> list:
        """Retrieve all LLM interactions for a session, ordered by timestamp."""
        return (
            self.db.query(LLMInteraction)
            .filter(LLMInteraction.session_id == session_id)
            .order_by(LLMInteraction.timestamp.asc())
            .all()
        )

