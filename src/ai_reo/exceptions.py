"""Domain-specific exception hierarchy for AI-REO.

All custom exceptions extend :class:`AiReoError` so callers can catch the
entire family with a single ``except AiReoError`` clause.
"""

from __future__ import annotations


class AiReoError(Exception):
    """Base exception for all AI-REO domain errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict = details or {}


# ---------------------------------------------------------------------------
# Session errors
# ---------------------------------------------------------------------------


class SessionNotFoundError(AiReoError):
    """Raised when a requested analysis session does not exist."""


class SessionConflictError(AiReoError):
    """Raised when a session already exists for the given binary hash."""


# ---------------------------------------------------------------------------
# Agent errors
# ---------------------------------------------------------------------------


class AgentError(AiReoError):
    """Base class for errors originating inside an agent node."""


class AgentTimeoutError(AgentError):
    """Raised when an agent exceeds its allocated execution time."""


class AgentConfigurationError(AgentError):
    """Raised when an agent is mis-configured (missing provider, bad prompt, …)."""


# ---------------------------------------------------------------------------
# Tool errors
# ---------------------------------------------------------------------------


class ToolError(AiReoError):
    """Base class for errors originating from the tool integration layer."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not registered."""


class ToolExecutionError(ToolError):
    """Raised when a tool container exits with a non-zero exit code."""


class ToolTimeoutError(ToolError):
    """Raised when a tool execution exceeds the configured timeout."""


# ---------------------------------------------------------------------------
# LLM provider errors
# ---------------------------------------------------------------------------


class LLMError(AiReoError):
    """Base class for LLM provider errors."""


class LLMProviderUnavailableError(LLMError):
    """Raised when no LLM provider can service the request."""


# ---------------------------------------------------------------------------
# Validation / input errors
# ---------------------------------------------------------------------------


class ValidationError(AiReoError):
    """Raised for invalid user input that does not fit domain rules."""


class BinaryNotFoundError(AiReoError):
    """Raised when the referenced binary file cannot be located."""
