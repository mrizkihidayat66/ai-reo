"""Structured output protocol for AI-REO agents.

Every agent step produces an ``AgentStepResult`` which:
  - Tells the orchestrator whether the assigned goal was achieved
  - Carries concrete, typed findings for the Knowledge Graph
  - Surfaces tool call evidence to prevent hallucination
  - Signals blocked states so the system can react gracefully
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class AgentFinding(BaseModel):
    """A single, discrete discovery made by an agent during analysis."""

    finding_type: Literal[
        "function", "string", "import", "section", "header",
        "behavior", "vulnerability", "flag", "other",
    ]
    address: Optional[str] = None
    name: Optional[str] = None
    description: str
    raw_evidence: Optional[str] = Field(
        default=None,
        description="Verbatim tool output supporting this finding.",
    )
    confidence: Literal["high", "medium", "low"] = "medium"


class AgentStepResult(BaseModel):
    """Structured response every agent step must produce.

    The orchestrator uses these fields — especially ``goal_completed``,
    ``findings``, and ``blocked_reason`` — to make routing decisions
    without relying on LLM prose interpretation.
    """

    goal_completed: bool = Field(
        description="True if the assigned sub-goal was fully achieved.",
    )
    findings: List[AgentFinding] = Field(
        default_factory=list,
        description="Concrete discoveries (can be empty if nothing was found).",
    )
    next_suggested_action: Optional[str] = Field(
        default=None,
        description="If not complete, what should be done next?",
    )
    summary: str = Field(
        description="Human-readable prose summary of what this step accomplished.",
    )
    tool_calls_made: List[str] = Field(
        default_factory=list,
        description="Names of tools actually invoked (not hallucinated).",
    )
    blocked_reason: Optional[str] = Field(
        default=None,
        description="Non-None if the agent could not proceed (no binary, missing tool, etc.).",
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

import json
import re
import logging

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.DOTALL,
)
_BARE_JSON_RE = re.compile(
    r'(\{[^{}]*"goal_completed"[^{}]*\})',
    re.DOTALL,
)


def parse_agent_step_result(raw_text: str) -> AgentStepResult:
    """Best-effort extraction of an ``AgentStepResult`` from LLM output.

    Strategy:
      1. Try to find a fenced ```json block
      2. Fall back to bare JSON object containing ``goal_completed``
      3. If all parsing fails, wrap the raw text as a summary-only result
    """
    # Strategy 1: fenced code block
    match = _JSON_BLOCK_RE.search(raw_text)
    if match:
        try:
            return AgentStepResult.model_validate_json(match.group(1))
        except Exception:
            logger.debug("Fenced JSON block found but failed to parse as AgentStepResult.")

    # Strategy 2: bare JSON with goal_completed key
    match = _BARE_JSON_RE.search(raw_text)
    if match:
        try:
            return AgentStepResult.model_validate_json(match.group(1))
        except Exception:
            logger.debug("Bare JSON found but failed to parse as AgentStepResult.")

    # Strategy 3: try the entire text as JSON
    stripped = raw_text.strip()
    if stripped.startswith("{"):
        try:
            return AgentStepResult.model_validate_json(stripped)
        except Exception:
            pass

    # Fallback: wrap as unstructured prose
    logger.warning("Could not parse AgentStepResult from LLM output; wrapping as prose summary.")
    return AgentStepResult(
        goal_completed=False,
        summary=raw_text[:2000],
        findings=[],
        tool_calls_made=[],
        blocked_reason=None,
    )
