"""High-level business logic services for database operations.

These services wrap the DAOs/Repositories and provide domain-specific orchestration
such as graph traversals, lifecycle management, and bulk operations.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from ai_reo.db.models import KnowledgeGraphNode, Session as AnalysisSession, ToolExecution
from ai_reo.db.repositories import (
    KnowledgeGraphRepository,
    SessionRepository,
    ToolExecutionRepository,
)


class KnowledgeGraphService:
    """Service handling Knowledge Graph logic including edges and bulk operations."""

    def __init__(self, db: DBSession, repo: KnowledgeGraphRepository) -> None:
        self.db = db
        self.repo = repo

    def add_node(
        self,
        session_id: str,
        node_type: str,
        created_by_agent: str,
        address: Optional[str] = None,
        name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeGraphNode:
        return self.repo.add_node(
            session_id=session_id,
            node_type=node_type,
            created_by_agent=created_by_agent,
            address=address,
            name=name,
            data=data,
        )

    def update_node_data(self, node_id: str, updates: Dict[str, Any]) -> Optional[KnowledgeGraphNode]:
        """Merge new keys into a node's existing JSON data."""
        node = self.db.query(KnowledgeGraphNode).get(node_id)
        if not node:
            return None
        
        # SQLAlchemy requires assigning a new dict to trigger JSON column updates
        current_data = dict(node.data) if node.data else {}
        current_data.update(updates)
        node.data = current_data
        
        self.db.commit()
        self.db.refresh(node)
        return node

    def add_edge(self, source_node_id: str, target_node_id: str, relationship: str) -> bool:
        """Store an edge logically inside the source node's JSON data field."""
        node = self.db.query(KnowledgeGraphNode).get(source_node_id)
        if not node:
            return False
            
        current_data = dict(node.data) if node.data else {}
        edges: List[Dict[str, str]] = current_data.get("edges", [])
        
        # Prevent duplicates
        if not any(e.get("target") == target_node_id and e.get("relationship") == relationship for e in edges):
            edges.append({"target": target_node_id, "relationship": relationship})
            current_data["edges"] = edges
            node.data = current_data
            self.db.commit()
            
        return True

    def get_related_nodes(self, source_node_id: str, relationship: Optional[str] = None) -> List[KnowledgeGraphNode]:
        """Graph traversal utility: find all nodes logically connected from this source."""
        node = self.db.query(KnowledgeGraphNode).get(source_node_id)
        if not node or not node.data or "edges" not in node.data:
            return []
            
        edges = node.data["edges"]
        target_ids = [
            e["target"] for e in edges 
            if relationship is None or e.get("relationship") == relationship
        ]
        
        if not target_ids:
            return []
            
        return self.db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.id.in_(target_ids)).all()

    def delete_node(self, session_id: str, node_id: str) -> bool:
        """Delete a node and strip any dangling edge references pointing to it."""
        deleted = self.repo.delete_node(node_id)
        if not deleted:
            return False
        # Cascade: remove any edges in this session that referenced the deleted node
        remaining = self.db.query(KnowledgeGraphNode).filter(
            KnowledgeGraphNode.session_id == session_id
        ).all()
        for node in remaining:
            edges = (node.data or {}).get("edges", [])
            cleaned = [e for e in edges if e.get("target") != node_id]
            if len(cleaned) != len(edges):
                node.data = {**node.data, "edges": cleaned}
        self.db.commit()
        return True

    def bulk_delete_nodes(self, session_id: str, node_ids: List[str]) -> int:
        """Delete multiple nodes and strip all dangling edges in the session."""
        id_set = set(node_ids)
        count = self.repo.bulk_delete_nodes(node_ids)
        remaining = self.db.query(KnowledgeGraphNode).filter(
            KnowledgeGraphNode.session_id == session_id
        ).all()
        for node in remaining:
            edges = (node.data or {}).get("edges", [])
            cleaned = [e for e in edges if e.get("target") not in id_set]
            if len(cleaned) != len(edges):
                node.data = {**node.data, "edges": cleaned}
        self.db.commit()
        return count

    def delete_edge(self, source_node_id: str, target_node_id: str, relationship: str) -> bool:
        return self.repo.delete_edge(source_node_id, target_node_id, relationship)

    def export_graph(self, session_id: str) -> Dict[str, Any]:
        """Bulk export graph data entirely to JSON."""
        nodes = self.db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == session_id).all()
        return {
            "session_id": session_id,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.node_type,
                    "address": n.address,
                    "name": n.name,
                    "data": n.data,
                    "created_by_agent": n.created_by_agent,
                }
                for n in nodes
            ]
        }

    def import_graph(self, session_id: str, graph_data: Dict[str, Any]) -> None:
        """Bulk import nodes into the graph from JSON format."""
        nodes_to_insert = []
        for n_data in graph_data.get("nodes", []):
            nodes_to_insert.append(
                KnowledgeGraphNode(
                    id=n_data.get("id"),
                    session_id=session_id,
                    node_type=n_data.get("type"),
                    address=n_data.get("address"),
                    name=n_data.get("name"),
                    data=n_data.get("data", {}),
                    created_by_agent=n_data.get("created_by_agent", "import"),
                )
            )
        if nodes_to_insert:
            self.db.bulk_save_objects(nodes_to_insert)
            self.db.commit()


class SessionService:
    """Service for orchestrating analysis session lifecycles."""

    def __init__(self, db: DBSession, repo: SessionRepository) -> None:
        self.db = db
        self.repo = repo

    def create_session(self, binary_path: str, binary_hash: str, name: Optional[str] = None, working_dir: Optional[str] = None) -> AnalysisSession:
        return self.repo.create(binary_path, binary_hash, name=name, working_dir=working_dir)

    def load_session(self, session_id: str) -> AnalysisSession:
        return self.repo.get(session_id)

    def list_sessions(self) -> list:
        return self.repo.list_all()

    def delete_session(self, session_id: str) -> None:
        self.repo.delete(session_id)

    def rename_session(self, session_id: str, name: str) -> AnalysisSession:
        return self.repo.rename(session_id, name)

    def update_workflow_checkpoint(self, session_id: str, state_id: str) -> AnalysisSession:
        return self.repo.update_status(session_id, status="active", state_id=state_id)

    def complete_session(self, session_id: str) -> AnalysisSession:
        return self.repo.update_status(session_id, status="completed")

    def export_manifest(self, session_id: str, kg_service: KnowledgeGraphService) -> Dict[str, Any]:
        """Serialize the complete session, including its knowledge graph snapshot."""
        session = self.load_session(session_id)
        graph = kg_service.export_graph(session_id)
        return {
            "session": {
                "id": session.id,
                "binary_path": session.binary_path,
                "hash": session.binary_hash,
                "status": session.status,
                "created_at": session.created_at.isoformat(),
                "checkpoint_id": session.current_workflow_state_id,
            },
            "knowledge_graph": graph
        }


class ToolExecutionService:
    """Service handling tool invocation logs and cleanup logic."""

    def __init__(self, db: DBSession, repo: ToolExecutionRepository) -> None:
        self.db = db
        self.repo = repo

    def log(
        self,
        session_id: str,
        tool_name: str,
        invoked_by: str,
        command: Dict[str, Any],
        stdout: Optional[str],
        stderr: Optional[str],
        exit_code: int,
    ) -> ToolExecution:
        return self.repo.log_execution(
            session_id, tool_name, invoked_by, command, stdout, stderr, exit_code
        )

    def get_history(self, session_id: str) -> List[ToolExecution]:
        return self.repo.get_history(session_id)

    def cleanup_old_logs(self, retention_days: int = 30) -> int:
        """Delete tool execution records older than a specific retention period."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted_count = (
            self.db.query(ToolExecution)
            .filter(ToolExecution.timestamp < cutoff)
            .delete()
        )
        self.db.commit()
        return deleted_count
