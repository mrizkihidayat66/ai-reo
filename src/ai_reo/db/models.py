"""SQLAlchemy models representing the core database schema.

Defined closely to `docs/database_schema.md`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ai_reo.db.engine import Base


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class Session(Base):
    """Analysis Session: The top-level container for analyzing a specific binary."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=True)
    binary_path = Column(String, nullable=False)
    binary_hash = Column(String, index=True, nullable=False)
    working_dir = Column(String, nullable=True)
    status = Column(String, index=True, nullable=False, default="initializing")
    created_at = Column(DateTime, index=True, default=utc_now)
    last_updated = Column(DateTime, default=utc_now, onupdate=utc_now)
    current_workflow_state_id = Column(String, nullable=True)

    # Relationships
    nodes = relationship("KnowledgeGraphNode", back_populates="session", cascade="all, delete-orphan")
    tool_executions = relationship("ToolExecution", back_populates="session", cascade="all, delete-orphan")
    llm_interactions = relationship("LLMInteraction", back_populates="session", cascade="all, delete-orphan")


class KnowledgeGraphNode(Base):
    """Knowledge Graph Node: Concepts discovered during analysis (functions, symbols, etc)."""

    __tablename__ = "knowledge_graph_nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id"), index=True, nullable=False)
    node_type = Column(String, index=True, nullable=False)
    address = Column(String, index=True, nullable=True)
    name = Column(String, index=True, nullable=True)
    data = Column(JSON, nullable=True)
    created_by_agent = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    session = relationship("Session", back_populates="nodes")


class ToolExecution(Base):
    """Tool Execution Record: Log of external analysis tool invocations."""

    __tablename__ = "tool_executions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id"), index=True, nullable=False)
    tool_name = Column(String, index=True, nullable=False)
    invoked_by_agent = Column(String, index=True, nullable=False)
    command = Column(JSON, nullable=False)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    timestamp = Column(DateTime, index=True, default=utc_now)

    session = relationship("Session", back_populates="tool_executions")


class LLMInteraction(Base):
    """LLM Interaction Log: Record of agent LLM calls for debugging and cost tracking."""

    __tablename__ = "llm_interactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id"), index=True, nullable=False)
    agent_name = Column(String, index=True, nullable=False)
    provider = Column(String, index=True, nullable=False)
    model = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    timestamp = Column(DateTime, index=True, default=utc_now)

    session = relationship("Session", back_populates="llm_interactions")
