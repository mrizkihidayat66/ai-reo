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

# Matches any fenced code block (```json or ``` plain). Finds ALL occurrences — we try last-to-first
# because the AgentStepResult JSON block is always appended at the END of the response.
_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.DOTALL,
)
# Broad search for any JSON object containing "goal_completed" at any nesting depth.
# Uses a stack-based extractor (see _extract_json_with_goal_completed) rather than regex
# because [^{}]* can't match nested objects (findings array contains nested braces).
_GOAL_COMPLETED_RE = re.compile(r'"goal_completed"\s*:', re.DOTALL)


def _extract_json_with_goal_completed(text: str) -> list[str]:
    """Extract all top-level JSON objects that contain 'goal_completed' using brace counting."""
    results = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:j + 1]
                        if '"goal_completed"' in candidate:
                            results.append(candidate)
                        i = j + 1
                        break
            else:
                break
        else:
            i += 1
    return results


def parse_agent_step_result(raw_text: str) -> AgentStepResult:
    """Best-effort extraction of an ``AgentStepResult`` from LLM output.

    Strategy:
      1. Try fenced ```json blocks in REVERSE order (last block first — JSON is always appended last)
      2. Fall back to brace-counted extraction of any JSON object containing 'goal_completed'
      3. Try the entire text as JSON
      4. Wrap as prose fallback (0 findings, no KG writes)
    """
    # Strategy 1: fenced code blocks — iterate in reverse (last match = appended JSON block)
    all_blocks = _JSON_BLOCK_RE.findall(raw_text)
    for block in reversed(all_blocks):
        try:
            return AgentStepResult.model_validate_json(block)
        except Exception:
            logger.debug("Fenced code block found but not a valid AgentStepResult, trying next.")

    # Strategy 2: brace-counted JSON objects containing "goal_completed" — try last-to-first
    candidates = _extract_json_with_goal_completed(raw_text)
    for candidate in reversed(candidates):
        try:
            return AgentStepResult.model_validate_json(candidate)
        except Exception:
            logger.debug("Bare JSON candidate found but failed to parse as AgentStepResult.")

    # Strategy 3: try the entire text as JSON
    stripped = raw_text.strip()
    if stripped.startswith("{"):
        try:
            return AgentStepResult.model_validate_json(stripped)
        except Exception:
            pass

    # Fallback: wrap as unstructured prose — 0 findings, nothing written to KG
    logger.warning("Could not parse AgentStepResult from LLM output; wrapping as prose summary.")
    return AgentStepResult(
        goal_completed=False,
        summary=raw_text[:2000],
        findings=[],
        tool_calls_made=[],
        blocked_reason=None,
    )
