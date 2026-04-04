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
    AGENT_REGISTRY,
    CodeAuditor,
    CryptoAnalyst,
    DebuggerAgent,
    DeobfuscatorAgent,
    DocumentationAgent,
    DynamicAnalyst,
    ExploitDeveloper,
    FirmwareAnalyst,
    MobileAnalyst,
    NetworkAnalyst,
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

    # Anti-redundancy: tools that already ran successfully in prior invocations
    completed_tools: str
    # Tools that failed permanently (e.g. capa exit 12, angr exit 1) — don't retry
    permanently_failed_tools: str

    # Agents invoked so far (comma-separated) — used to prevent premature documentation
    used_agents: str

    # Optional: "continuation" bypasses intent classifier
    mode: str

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
deobfuscator_agent = DeobfuscatorAgent()
debugger_agent = DebuggerAgent()
mobile_analyst = MobileAnalyst()
crypto_analyst = CryptoAnalyst()
network_analyst = NetworkAnalyst()
firmware_analyst = FirmwareAnalyst()
exploit_developer = ExploitDeveloper()
code_auditor = CodeAuditor()


# ---------------------------------------------------------------------------
# Intent classifier (runs before orchestration)
# ---------------------------------------------------------------------------

async def classify_intent_node(state: AnalysisState) -> Dict[str, Any]:
    """Classify the user's message and set the route.

    - ANALYSIS → orchestrator (full multi-agent pipeline)
    - CHAT/QUESTION → direct_chat (single LLM response, no agents)
    - mode="continuation" → skips classifier, goes directly to orchestrator
    """
    goal = state.get("current_goal", "")
    session_id = state["session_id"]

    # Continuation mode: user is following up on an ongoing analysis — skip LLM classifier
    if state.get("mode") == "continuation":
        logger.info("Continuation mode — routing directly to orchestrator.")
        return {"active_agent": "orchestrator"}

    try:
        from ai_reo.agents.classifier import classify_user_intent
        intent = await classify_user_intent(goal)
    except Exception as e:
        logger.warning("Intent classification failed: %s — defaulting to ANALYSIS", e)
        intent = "ANALYSIS"

    logger.info("Intent classified as %s for goal: %.80s", intent, goal)

    if intent in ("CHAT", "QUESTION", "COMMAND"):
        return {"active_agent": "direct_chat"}

    # Shortcut: if the user explicitly requests documentation/report and we already
    # have KG findings, skip the orchestrator and go straight to documentation.
    doc_keywords = ("document", "report", "summarize", "summary", "write report", "generate report")
    if any(kw in goal.lower() for kw in doc_keywords) and state.get("findings_count", 0) > 0:
        logger.info("Documentation shortcut triggered (findings_count=%d).", state.get("findings_count", 0))
        return {"active_agent": "documentation"}

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
        provider = llm_manager.get_provider(task_type="CHAT")
        response = await provider.chat_completion(messages=ctx.get_history(), task_type="CHAT")
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

        provider = llm_manager.get_provider(task_type="CHAT")
        with get_db_session() as db:
            repo = LLMInteractionRepository(db)
            repo.log_interaction(
                session_id=session_id,
                agent_name="direct_chat",
                provider=provider.config.display_name,
                model=provider.config.get_effective_model(task_type="CHAT"),
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
        tools="static_analyst, dynamic_analyst, deobfuscator, debugger, mobile_analyst, crypto_analyst, network_analyst, firmware_analyst, exploit_developer, code_auditor, documentation",
    )
    ctx.add_message("system", sys_msg)

    # Anti-redundancy: inform orchestrator of tools already run in this session
    completed_tools = state.get("completed_tools", "")
    if completed_tools:
        ctx.add_message(
            "system",
            f"PREVIOUSLY COMPLETED TOOLS (their results are already in the Knowledge Graph — "
            f"DO NOT re-invoke these unless the user explicitly requests it): {completed_tools}",
        )

    permanently_failed = state.get("permanently_failed_tools", "")
    if permanently_failed:
        ctx.add_message(
            "system",
            f"PERMANENTLY FAILED TOOLS (these tools fail on this binary and must NOT be retried): "
            f"{permanently_failed}",
        )

    used_agents_ctx = state.get("used_agents", "")
    if used_agents_ctx:
        ctx.add_message(
            "system",
            f"AGENTS ALREADY INVOKED THIS SESSION: {used_agents_ctx}. "
            "Prioritize agents NOT YET invoked before routing to documentation.",
        )

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
    findings_count = state.get("findings_count", 0)
    used_agents_str = state.get("used_agents", "")
    used_agents_list = [a for a in used_agents_str.split(", ") if a]
    specialist_count = len(set(a for a in used_agents_list if a not in ("orchestrator", "documentation", "direct_chat")))

    if consecutive_empty >= 5:
        logger.info("5+ consecutive empty steps — forcing documentation synthesis.")
        return {
            "active_agent": "documentation",
            "current_goal": state.get("current_goal", "Analyze the binary."),
            "messages": [{"role": "assistant", "content": "Analysis has stagnated after 5 empty steps. Synthesizing findings."}],
        }

    # --- Text heuristic fallback — driven by AGENT_REGISTRY route_keywords ---
    lower = content.lower()
    next_agent = None
    # Iterate registry in priority order (deobfuscator before static, exploit before debugger)
    _priority_order = [
        "deobfuscator", "exploit_developer", "debugger", "crypto_analyst",
        "network_analyst", "firmware_analyst", "code_auditor", "mobile_analyst",
        "static_analyst", "dynamic_analyst", "documentation",
    ]
    for agent_key in _priority_order:
        meta = AGENT_REGISTRY.get(agent_key, {})
        if any(kw in lower for kw in meta.get("route_keywords", [])):
            next_agent = agent_key
            break

    if next_agent is None:
        # Default: static first, then documentation only if adequately explored
        findings = state.get("findings_count", 0)
        if findings > 0 and specialist_count >= 2:
            next_agent = "documentation"
        else:
            next_agent = "static_analyst"

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
        binary_dir = _Path(_settings.tools.sessions_dir).resolve() / session_id / "workspace"
        if not binary_dir.exists():
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

    # Inject matching skills as additional system context.
    try:
        from ai_reo.skills.loader import skill_loader as _skill_loader
        agent_skills = _skill_loader.get_for_agent(agent_name)
        for skill in agent_skills:
            ctx.add_message(
                "system",
                f"## Skill: {skill.name}\n\n{skill.content}",
            )
        if agent_skills:
            logger.debug("Injected %d skill(s) for agent %s: %s",
                         len(agent_skills), agent_name, [s.name for s in agent_skills])
    except Exception as _e:
        logger.debug("Could not inject skills for agent %s: %s", agent_name, _e)

    # Inject a user message so LM Studio doesn't crash on tool schemas
    ctx.add_message("user", f"Your current task: {state.get('current_goal', 'Analyze the binary.')}")

    # Anti-redundancy: inform agent of tools already run in this session
    completed_tools = state.get("completed_tools", "")
    if completed_tools:
        ctx.add_message(
            "system",
            f"PREVIOUSLY COMPLETED TOOLS (their results are already in the Knowledge Graph — "
            f"DO NOT re-invoke these unless the user explicitly requests it): {completed_tools}",
        )

    permanently_failed = state.get("permanently_failed_tools", "")
    if permanently_failed:
        ctx.add_message(
            "system",
            f"PERMANENTLY FAILED TOOLS (these tools fail on this binary and MUST NOT be retried — "
            f"they always error on this specific file): {permanently_failed}",
        )

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

    # Validate output quality: warn if agent returned 0 findings with no explanation
    new_findings_count = len(result.findings)
    if new_findings_count == 0 and not result.blocked_reason and not result.goal_completed:
        logger.warning(
            "Agent %s produced 0 findings with no blocked_reason and no goal_completed "
            "(summary: %.120s)", agent_name, result.summary,
        )

    total_findings = state.get("findings_count", 0) + new_findings_count
    consecutive_empty = 0 if new_findings_count > 0 else state.get("consecutive_empty_steps", 0) + 1

    # Track permanently failing tools (exit_code != 0 and no findings produced)
    # These are injected into subsequent agent steps to prevent pointless retries.
    try:
        from ai_reo.db.engine import get_db_session as _get_db
        from ai_reo.db.repositories import ToolExecutionRepository as _TER
        # Exit codes that are definitively "this tool cannot process this binary"
        _PERM_FAIL_CODES = {1, 2, 12, 127}
        with _get_db() as _db:
            _history = _TER(_db).get_history(session_id)
        _failed = {
            t.tool_name for t in _history
            if t.exit_code in _PERM_FAIL_CODES
            and all(o.exit_code in _PERM_FAIL_CODES for o in _history if o.tool_name == t.tool_name)
        }
        existing_failed = set(state.get("permanently_failed_tools", "").split(", ")) - {""}
        new_failed_str = ", ".join(sorted(existing_failed | _failed))
    except Exception:
        new_failed_str = state.get("permanently_failed_tools", "")

    updates: Dict[str, Any] = {
        "messages": new_msgs,
        "last_result": result.model_dump(),
        "findings_count": total_findings,
        "consecutive_empty_steps": consecutive_empty,
        "permanently_failed_tools": new_failed_str,
    }

    # Track which agents have been called (for doc gate and diversity enforcement)
    existing_used = [a for a in state.get("used_agents", "").split(", ") if a]
    if agent_name not in existing_used:
        existing_used.append(agent_name)
    updates["used_agents"] = ", ".join(existing_used)

    return updates


async def static_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("static_analyst", static_analyst, state)


async def dynamic_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("dynamic_analyst", dynamic_analyst, state)


async def deobfuscator_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("deobfuscator", deobfuscator_agent, state)


async def debugger_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("debugger", debugger_agent, state)


async def mobile_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("mobile_analyst", mobile_analyst, state)


async def crypto_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("crypto_analyst", crypto_analyst, state)


async def network_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("network_analyst", network_analyst, state)


async def firmware_analyst_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("firmware_analyst", firmware_analyst, state)


async def exploit_developer_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("exploit_developer", exploit_developer, state)


async def code_auditor_node(state: AnalysisState) -> Dict[str, Any]:
    return await run_agent_node("code_auditor", code_auditor, state)


# Keywords that indicate user explicitly asked for documentation
_DOC_REQUEST_KEYWORDS = ("document", "report", "summarize", "summary", "write report", "generate report")


async def documentation_node(state: AnalysisState) -> Dict[str, Any]:
    # Guard: if KG has no findings and user did NOT explicitly request a report,
    # return a placeholder rather than wasting an LLM call on empty input.
    findings_count = state.get("findings_count", 0)
    kg_summary = state.get("kg_summary", "")
    is_empty_kg = findings_count == 0 and (not kg_summary or kg_summary in ("Empty Graph", "[]"))
    goal_lower = state.get("current_goal", "").lower()
    user_requested_doc = any(kw in goal_lower for kw in _DOC_REQUEST_KEYWORDS)

    if is_empty_kg and not user_requested_doc:
        placeholder = (
            "**No analysis data is available yet.** "
            "Please run an analysis first so the agents can gather findings, "
            "then request a report."
        )
        session_id = state["session_id"]
        try:
            from ai_reo.api.websockets import manager as _ws
            await _ws.broadcast_to_session(session_id, {
                "type": "chat_message",
                "role": "assistant",
                "agent": "documentation",
                "content": placeholder,
            })
        except Exception:
            pass
        return {
            "final_report": placeholder,
            "messages": [{"role": "assistant", "content": placeholder}],
        }

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
    elif "deobfusc" in target or "obfusc" in target or "unpack" in target:
        return "deobfuscator"
    elif "exploit" in target or "rop" in target:
        return "exploit_developer"
    elif "debug" in target or "vuln" in target:
        return "debugger"
    elif "crypto" in target:
        return "crypto_analyst"
    elif "network" in target or "protocol" in target:
        return "network_analyst"
    elif "firmware" in target:
        return "firmware_analyst"
    elif "audit" in target:
        return "code_auditor"
    elif "mobile" in target or "apk" in target or "android" in target or "dex" in target:
        return "mobile_analyst"
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
    workflow.add_node("deobfuscator", deobfuscator_node)
    workflow.add_node("debugger", debugger_node)
    workflow.add_node("mobile_analyst", mobile_analyst_node)
    workflow.add_node("crypto_analyst", crypto_analyst_node)
    workflow.add_node("network_analyst", network_analyst_node)
    workflow.add_node("firmware_analyst", firmware_analyst_node)
    workflow.add_node("exploit_developer", exploit_developer_node)
    workflow.add_node("code_auditor", code_auditor_node)
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
            "deobfuscator": "deobfuscator",
            "debugger": "debugger",
            "mobile_analyst": "mobile_analyst",
            "crypto_analyst": "crypto_analyst",
            "network_analyst": "network_analyst",
            "firmware_analyst": "firmware_analyst",
            "exploit_developer": "exploit_developer",
            "code_auditor": "code_auditor",
            "documentation": "documentation",
        },
    )

    # Analyst cycle: agents finish → back to orchestrator for re-evaluation
    workflow.add_edge("static_analyst", "orchestrator")
    workflow.add_edge("dynamic_analyst", "orchestrator")
    workflow.add_edge("deobfuscator", "orchestrator")
    workflow.add_edge("debugger", "orchestrator")
    workflow.add_edge("mobile_analyst", "orchestrator")
    workflow.add_edge("crypto_analyst", "orchestrator")
    workflow.add_edge("network_analyst", "orchestrator")
    workflow.add_edge("firmware_analyst", "orchestrator")
    workflow.add_edge("exploit_developer", "orchestrator")
    workflow.add_edge("code_auditor", "orchestrator")

    # Documentation is terminal
    workflow.add_edge("documentation", END)

    compiled_graph = workflow.compile()
    return compiled_graph


app_graph = build_graph()
