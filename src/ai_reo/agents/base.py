"""Base implementations for AI-REO agents.

After every step, agents:
  1. Parse their LLM response into an ``AgentStepResult``
  2. Write each finding to the Knowledge Graph DB
  3. Log the LLM interaction to the DB for history persistence
  4. Broadcast structured progress via WebSocket
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ai_reo.agents.protocol import AgentStepResult, parse_agent_step_result
from ai_reo.llm.context import ConversationContext
from ai_reo.llm.providers import llm_manager
from ai_reo.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# Maximum tool-call rounds per step to prevent infinite tool loops
MAX_TOOL_ROUNDS = 10


class BaseAgent:
    """Core agent class orchestrating LLM ↔ tool interaction with structured outputs."""

    def __init__(self, role_name: str, allowed_tools: Optional[List[str]] = None) -> None:
        self.role_name = role_name
        self.allowed_tools = allowed_tools or []

    # ------------------------------------------------------------------
    # Tool schema helpers
    # ------------------------------------------------------------------

    def _get_tools_schema(self, tool_names: Optional[List[str]] = None) -> Optional[List[Dict[str, Any]]]:
        """Fetch OpenAI-compatible schemas for the specified (or all allowed) tools."""
        names = tool_names if tool_names is not None else self.allowed_tools
        if not names:
            return None
        schemas = [
            t for t in tool_registry.list_tools()
            if t["function"]["name"] in names
        ]
        return schemas if schemas else None

    def _should_use_tools(self) -> bool:
        """Check if the current provider supports tool calling reliably."""
        try:
            provider = llm_manager.get_provider()
            ptype = provider.config.provider_type
            # Ollama doesn't reliably support tool_calls in all models
            if ptype == "ollama":
                return False
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool_call(self, session_id: str, tool_call: Any) -> str:
        """Execute a tool requested by the LLM and return its serialized result."""
        name = tool_call.function.name
        try:
            kwargs = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "INVALID_ARGS", "message": "Invalid JSON arguments for tool."})

        if name not in self.allowed_tools:
            return json.dumps({
                "error": "UNAUTHORIZED_TOOL",
                "message": f"Tool '{name}' is not authorized for the {self.role_name} agent.",
            })

        try:
            result = await tool_registry.dispatch(name, session_id, kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": "TOOL_EXECUTION_ERROR", "message": str(e)})

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_findings(self, session_id: str, result: AgentStepResult) -> None:
        """Write each finding from the agent's result to the Knowledge Graph."""
        if not result.findings:
            return

        try:
            from ai_reo.db.engine import get_db_session
            from ai_reo.db.repositories import KnowledgeGraphRepository

            with get_db_session() as db:
                repo = KnowledgeGraphRepository(db)
                for finding in result.findings:
                    repo.add_node(
                        session_id=session_id,
                        node_type=finding.finding_type,
                        created_by_agent=self.role_name,
                        address=finding.address,
                        name=finding.name,
                        data={
                            "description": finding.description,
                            "evidence": finding.raw_evidence,
                            "confidence": finding.confidence,
                        },
                    )
            logger.info(
                "Agent %s: persisted %d finding(s) to KG for session %s",
                self.role_name, len(result.findings), session_id,
            )
        except Exception:
            logger.exception("Failed to persist findings for session %s", session_id)

    def _persist_interaction(
        self,
        session_id: str,
        content: str,
        context: ConversationContext,
    ) -> None:
        """Log the LLM interaction to the database for chat history."""
        try:
            from ai_reo.db.engine import get_db_session
            from ai_reo.db.repositories import LLMInteractionRepository

            provider = llm_manager.get_provider()
            with get_db_session() as db:
                repo = LLMInteractionRepository(db)
                # Serialize the last few context messages as the "prompt"
                recent_messages = context.get_history()[-3:]
                prompt_text = json.dumps(recent_messages, default=str)[:4000]

                repo.log_interaction(
                    session_id=session_id,
                    agent_name=self.role_name,
                    provider=provider.config.display_name,
                    model=provider.config.get_effective_model(),
                    prompt=prompt_text,
                    response=content[:4000],
                    token_count=self._estimate_tokens(content),
                )
        except Exception:
            logger.exception("Failed to persist LLM interaction for session %s", session_id)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token count estimate (≈ 4 chars per token for English)."""
        return max(1, len(text) // 4)

    # ------------------------------------------------------------------
    # Core step logic
    # ------------------------------------------------------------------

    async def step(self, session_id: str, context: ConversationContext) -> AgentStepResult:
        """Execute a single reasoning step with structured output.

        Flow:
          1. LLM call (with tool schemas if supported)
          2. Tool execution loop (if LLM requests tools)
          3. Parse final response into AgentStepResult
          4. Persist findings to KG + interaction to DB
          5. Broadcast via WebSocket
        """
        provider = llm_manager.get_provider()

        # Decide whether to pass tools based on provider capability
        tools_schema = self._get_tools_schema() if self._should_use_tools() else None

        # Broadcast that this agent is starting its step
        ws_manager = self._get_ws_manager()
        if ws_manager:
            await ws_manager.broadcast_to_session(session_id, {
                "type": "agent_step",
                "agent": self.role_name,
                "status": "thinking",
                "message": f"{self.role_name} is working...",
            })

        content = ""
        tool_calls_made: List[str] = []

        for round_num in range(MAX_TOOL_ROUNDS):
            response = await provider.chat_completion(
                messages=context.get_history(),
                tools=tools_schema,
            )

            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                # Append the LLM's tool-call intention to history
                context.messages.append(msg.model_dump(exclude_none=True))

                # Execute tools and feed results back
                for tc in tool_calls:
                    tool_name = tc.function.name
                    tool_calls_made.append(tool_name)

                    result_str = await self.execute_tool_call(session_id, tc)

                    context.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tool_name,
                        "content": result_str,
                    })

                    # Broadcast tool activity via WS
                    if ws_manager:
                        try:
                            await ws_manager.broadcast_to_session(session_id, {
                                "type": "tool_result",
                                "agent": self.role_name,
                                "tool": tool_name,
                                "result_preview": result_str[:500],
                            })
                        except Exception:
                            pass

                logger.debug(
                    "Agent %s: tool round %d — looping back for synthesis",
                    self.role_name, round_num + 1,
                )
                continue

            else:
                # Final text response (no more tool calls)
                content = msg.content or ""
                context.add_message("assistant", content)
                break
        else:
            # Safety: exhausted tool rounds, force completion
            logger.warning(
                "Agent %s hit MAX_TOOL_ROUNDS (%d), forcing completion",
                self.role_name, MAX_TOOL_ROUNDS,
            )
            content = content or "Maximum tool execution rounds reached. Returning current findings."
            context.add_message("assistant", content)

        # ── Parse structured output ──────────────────────────────────
        result = parse_agent_step_result(content)

        # Augment with tracked tool calls (in case the LLM forgot to list them)
        if tool_calls_made and not result.tool_calls_made:
            result.tool_calls_made = tool_calls_made

        # ── Persist to DB ────────────────────────────────────────────
        self._persist_findings(session_id, result)
        self._persist_interaction(session_id, content, context)

        # ── Broadcast final response via WS ──────────────────────────
        if ws_manager:
            try:
                await ws_manager.broadcast_to_session(session_id, {
                    "type": "chat_message",
                    "role": "assistant",
                    "agent": self.role_name,
                    "content": result.summary,
                    "goal_completed": result.goal_completed,
                    "findings_count": len(result.findings),
                })
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _get_ws_manager():
        """Lazy-import WebSocket manager — may not be available in tests."""
        try:
            from ai_reo.api.websockets import manager
            return manager
        except Exception:
            return None
