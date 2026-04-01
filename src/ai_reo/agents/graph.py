"""LangGraph multi-agent orchestration with structured completion logic.

Key improvements over the original:
  - Intent classifier routes conversational messages directly (no full pipeline)
  - Orchestrator uses AgentStepResult signals for routing decisions
  - Smart completion: the loop ends based on semantic signals, not arbitrary limits
  - State tracks findings count and consecutive empty steps for stagnation detection
"""

import json
import logging
import operator
import re
from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict

from langgraph.graph import StateGraph, END

from ai_reo.agents.protocol import AgentStepResult
from ai_reo.agents.specialized import (
    DocumentationAgent,
    DynamicAnalyst,
    OrchestratorAgent,
    StaticAnalyst,
)
from ai_reo.llm.context import ConversationContext
from ai_reo.llm.prompts import prompt_engine

logger = logging.getLogger(__name__)

# Generous safety net — should never actually be needed with correct completion signals
GRAPH_MAX_RECURSION_LIMIT = 100


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AnalysisState(TypedDict):
    """The central state dictionary flowing through the LangGraph."""
    session_id: str

    # Core LLM message sequence (appended via operator.add)
    messages: Annotated[Sequence[Dict[str, Any]], operator.add]

    # State tracking
    active_agent: str
    current_goal: str
    kg_summary: str

    # Structured completion signals (new)
    last_result: Optional[Dict[str, Any]]       # Serialised AgentStepResult from last agent
    findings_count: int                          # Total KG nodes accumulated in this session
    consecutive_empty_steps: int                 # Steps with 0 new findings in a row

    # Final output
    final_report: str
    error: str


# ---------------------------------------------------------------------------
# Agent singletons
# ---------------------------------------------------------------------------

orchestrator = OrchestratorAgent()
static_analyst = StaticAnalyst()
dynamic_analyst = DynamicAnalyst()
documentation_agent = DocumentationAgent()


# ---------------------------------------------------------------------------
# Intent classifier (runs before orchestration)
# ---------------------------------------------------------------------------

async def classify_intent_node(state: AnalysisState) -> Dict[str, Any]:
    """Classify the user's message and set the route.

    - ANALYSIS → orchestrator (full multi-agent pipeline)
    - CHAT/QUESTION → direct_chat (single LLM response, no agents)
    """
    goal = state.get("current_goal", "")
    session_id = state["session_id"]

    try:
        from ai_reo.agents.classifier import classify_user_intent
        intent = await classify_user_intent(goal)
    except Exception as e:
        logger.warning("Intent classification failed: %s — defaulting to ANALYSIS", e)
        intent = "ANALYSIS"

    logger.info("Intent classified as %s for goal: %.80s", intent, goal)

    if intent in ("CHAT", "QUESTION", "COMMAND"):
        return {"active_agent": "direct_chat"}
    return {"active_agent": "orchestrator"}


async def direct_chat_node(state: AnalysisState) -> Dict[str, Any]:
    """Handle conversational/non-analysis messages with a single LLM call."""
    session_id = state["session_id"]
    from ai_reo.llm.providers import llm_manager

    ctx = ConversationContext(session_id)

    # Load chat system prompt
    sys_msg = prompt_engine.render(
        "chat",
        kg_summary=state.get("kg_summary", "No analysis data yet."),
    )
    ctx.add_message("system", sys_msg)
    ctx.add_message("user", state.get("current_goal", "Hello"))

    try:
        provider = llm_manager.get_provider()
        response = await provider.chat_completion(messages=ctx.get_history())
        content = response.choices[0].message.content or "Hello! I'm AI-REO."
    except Exception as e:
        content = f"I'm AI-REO, your binary reverse engineering assistant. (LLM error: {e})"

    # Broadcast via WS
    try:
        from ai_reo.api.websockets import manager as ws_manager
        await ws_manager.broadcast_to_session(session_id, {
            "type": "chat_message",
            "role": "assistant",
            "agent": "ai-reo",
            "content": content,
        })
    except Exception:
        pass

    # Persist interaction
    try:
        from ai_reo.db.engine import get_db_session
        from ai_reo.db.repositories import LLMInteractionRepository

        provider = llm_manager.get_provider()
        with get_db_session() as db:
            repo = LLMInteractionRepository(db)
            repo.log_interaction(
                session_id=session_id,
                agent_name="direct_chat",
                provider=provider.config.display_name,
                model=provider.config.get_effective_model(),
                prompt=state.get("current_goal", "")[:2000],
                response=content[:4000],
                token_count=max(1, len(content) // 4),
            )
    except Exception:
        logger.exception("Failed to persist direct chat interaction")

    return {
        "final_report": content,
        "messages": [{"role": "assistant", "content": content}],
    }


# ---------------------------------------------------------------------------
# Orchestrator node (planning + routing)
# ---------------------------------------------------------------------------

async def orchestrator_node(state: AnalysisState) -> Dict[str, Any]:
    """The Orchestrator evaluates the Knowledge Graph and routes to the next agent."""
    session_id = state["session_id"]

    ctx = ConversationContext(session_id)

    # Build rich context for the orchestrator
    last_result = state.get("last_result")
    last_summary = "N/A (first step)"
    last_goal_completed = False
    last_findings_count = 0
    if last_result:
        last_summary = last_result.get("summary", "N/A")
        last_goal_completed = last_result.get("goal_completed", False)
        last_findings_count = len(last_result.get("findings", []))

    sys_msg = prompt_engine.render(
        "orchestrator",
        current_goal=state.get("current_goal", "Analyze the binary."),
        kg_summary=state.get("kg_summary", "Empty — no findings yet."),
        findings_count=str(state.get("findings_count", 0)),
        last_agent_summary=last_summary,
        last_goal_completed=str(last_goal_completed),
        last_findings_count=str(last_findings_count),
        tools="static_analyst, dynamic_analyst, documentation",
    )
    ctx.add_message("system", sys_msg)

    # Ensure there is at least one user message
    recent = list(state["messages"][-5:])
    has_user = any(m.get("role") == "user" for m in recent)
    if not has_user:
        ctx.add_message("user", f"Current task: {state.get('current_goal', 'Analyze the binary.')}")

    for msg in recent:
        ctx.messages.append(msg)

    try:
        result = await orchestrator.step(session_id, ctx)
    except Exception as exc:
        logger.warning("Orchestrator LLM error: %s — falling back to static_analyst", exc)
        return {
            "active_agent": "static_analyst",
            "current_goal": state.get("current_goal", "Analyze the binary."),
            "messages": [{"role": "assistant", "content": f"Orchestrator error: {exc}"}],
        }

    content = result.summary

    # --- Extract JSON routing decision ---
    json_match = re.search(r'\{[^{}]*"next_agent"[^{}]*\}', content, re.DOTALL)
    if json_match:
        try:
            plan = json.loads(json_match.group())
            return {
                "active_agent": plan.get("next_agent", "static_analyst"),
                "current_goal": plan.get("goal", state.get("current_goal", "Analyze the binary.")),
                "messages": [{"role": "assistant", "content": f"Orchestrator: {content}"}],
            }
        except json.JSONDecodeError:
            pass

    # --- Smart completion: check for stagnation ---
    consecutive_empty = state.get("consecutive_empty_steps", 0)
    if consecutive_empty >= 3:
        logger.info("3+ consecutive empty steps — forcing documentation synthesis.")
        return {
            "active_agent": "documentation",
            "current_goal": state.get("current_goal", "Analyze the binary."),
            "messages": [{"role": "assistant", "content": "Analysis has stagnated. Synthesizing findings."}],
        }

    # --- Text heuristic fallback ---
    lower = content.lower()
    if any(kw in lower for kw in ("static", "strings", "disassem", "header", "radare", "objdump")):
        next_agent = "static_analyst"
    elif any(kw in lower for kw in ("dynamic", "execut", "trace", "emulat", "sandbox")):
        next_agent = "dynamic_analyst"
    elif any(kw in lower for kw in ("report", "done", "complete", "summary", "final", "document")):
        next_agent = "documentation"
    else:
        # Default: static first, then documentation if KG has data
        kg = str(state.get("kg_summary", ""))
        findings = state.get("findings_count", 0)
        next_agent = "documentation" if findings > 0 else "static_analyst"

    return {
        "active_agent": next_agent,
        "current_goal": state.get("current_goal", "Analyze the binary."),
        "messages": [{"role": "assistant", "content": content or "Orchestrating..."}],
    }


# ---------------------------------------------------------------------------
# Agent wrapper nodes
# ---------------------------------------------------------------------------

async def run_agent_node(agent_name: str, agent_obj: Any, state: AnalysisState) -> Dict[str, Any]:
    """Execute an agent step and propagate structured result signals back to state."""
    session_id = state["session_id"]
    ctx = ConversationContext(session_id)

    sys_msg = prompt_engine.render(
        agent_name,
        current_goal=state.get("current_goal", ""),
        kg_summary=state.get("kg_summary", ""),
        session_id=session_id,
    )
    ctx.add_message("system", sys_msg)

    # Inject binary file inventory so agents know the exact filename to use in tool calls.
    try:
        from pathlib import Path as _Path
        from ai_reo.config import settings as _settings
        binary_dir = _Path(_settings.tools.sessions_dir).resolve() / session_id / "binary"
        if binary_dir.exists():
            binary_files = [f.name for f in binary_dir.iterdir() if f.is_file()]
            if binary_files:
                ctx.add_message(
                    "system",
                    f"BINARY FILES AVAILABLE IN THIS SESSION: {', '.join(binary_files)}. "
                    "Use these exact filenames (just the name, no path prefix) in every tool call's filepath argument.",
                )
    except Exception as _e:
        logger.debug("Could not enumerate binary files: %s", _e)

    # Inject a user message so LM Studio doesn't crash on tool schemas
    ctx.add_message("user", f"Your current task: {state.get('current_goal', 'Analyze the binary.')}")

    # Append recent history
    history_slice = list(state["messages"][-10:])
    for msg in history_slice:
        ctx.messages.append(msg)

    initial_count = len(ctx.messages)

    try:
        result: AgentStepResult = await agent_obj.step(session_id, ctx)
    except Exception as exc:
        logger.warning("Agent %s LLM error: %s", agent_name, exc)
        return {
            "messages": [{"role": "assistant", "content": f"[{agent_name}] Error: {exc}"}],
            "last_result": {"goal_completed": False, "summary": f"Error: {exc}", "findings": []},
            "consecutive_empty_steps": state.get("consecutive_empty_steps", 0) + 1,
        }

    # Extract new messages added by step()
    new_msgs = ctx.messages[initial_count:]
    if not new_msgs:
        new_msgs = [{"role": "assistant", "content": f"[{agent_name}] {result.summary}"}]

    # Update structured signals
    new_findings_count = len(result.findings)
    total_findings = state.get("findings_count", 0) + new_findings_count
    consecutive_empty = 0 if new_findings_count > 0 else state.get("consecutive_empty_steps", 0) + 1

    updates: Dict[str, Any] = {
        "messages": new_msgs,
        "last_result": result.model_dump(),
        "findings_count": total_findings,
        "consecutive_empty_steps": consecutive_empty,
    }

    return updates


async def static_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("static_analyst", static_analyst, state)


async def dynamic_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("dynamic_analyst", dynamic_analyst, state)


async def documentation_node(state: AnalysisState) -> Dict[str, Any]:
    res = await run_agent_node("documentation", documentation_agent, state)

    # The last message is the final report
    final_text = ""
    if res.get("messages"):
        final_text = res["messages"][-1].get("content", "")
    res["final_report"] = final_text
    return res


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def intent_router(state: AnalysisState) -> str:
    """Route from intent classifier to either orchestrator or direct chat."""
    agent = str(state.get("active_agent", "orchestrator")).lower()
    if "direct_chat" in agent:
        return "direct_chat"
    return "orchestrator"


def agent_router(state: AnalysisState) -> str:
    """Route from orchestrator to the selected agent."""
    target = str(state.get("active_agent", "")).lower()

    # Smart completion override: if the last agent reported goal_completed, go to docs
    last_result = state.get("last_result")
    if last_result and last_result.get("goal_completed"):
        logger.info("Last agent reported goal_completed → routing to documentation.")
        return "documentation"

    # If blocked, go to docs immediately
    if last_result and last_result.get("blocked_reason"):
        logger.info("Last agent is blocked ('%s') → routing to documentation.",
                     last_result["blocked_reason"])
        return "documentation"

    if "static" in target:
        return "static_analyst"
    elif "dynamic" in target:
        return "dynamic_analyst"
    elif "doc" in target:
        return "documentation"
    return "documentation"  # Final fallback


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    workflow = StateGraph(AnalysisState)

    # Nodes
    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("direct_chat", direct_chat_node)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("static_analyst", static_analyst_node)
    workflow.add_node("dynamic_analyst", dynamic_analyst_node)
    workflow.add_node("documentation", documentation_node)

    # Entry: classify intent first
    workflow.set_entry_point("classify_intent")

    # Intent routing: chat vs. analysis
    workflow.add_conditional_edges(
        "classify_intent",
        intent_router,
        {
            "direct_chat": "direct_chat",
            "orchestrator": "orchestrator",
        },
    )

    # Direct chat is terminal
    workflow.add_edge("direct_chat", END)

    # Orchestrator → conditional agent routing
    workflow.add_conditional_edges(
        "orchestrator",
        agent_router,
        {
            "static_analyst": "static_analyst",
            "dynamic_analyst": "dynamic_analyst",
            "documentation": "documentation",
        },
    )

    # Analyst cycle: analyst finishes → back to orchestrator for re-evaluation
    workflow.add_edge("static_analyst", "orchestrator")
    workflow.add_edge("dynamic_analyst", "orchestrator")

    # Documentation is terminal
    workflow.add_edge("documentation", END)

    compiled_graph = workflow.compile()
    return compiled_graph


app_graph = build_graph()
