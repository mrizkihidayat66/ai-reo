# Agent System — Integration Guide

AI-REO uses a LangGraph multi-agent graph. Each agent is a specialised node that receives a goal, invokes tools, and returns structured findings. Agents are driven by instruction files at `agents/*.md`.

---

## Agent Graph

```
User message
     │
     ▼
classify_intent ──► direct_chat  (conversational, no binary analysis needed)
     │
     ▼
 orchestrator ──► static_analyst
             \──► dynamic_analyst
              \──► deobfuscator
               \──► debugger
                \──► documentation ──► END
```

Each step routes back to the orchestrator, which decides the next specialist or terminates the graph.

---

## Available Agents

| Agent | File | Purpose |
|---|---|---|
| `orchestrator` | `agents/orchestrator.md` | Reads KG state, assigns sub-goals, routes to specialists |
| `static_analyst` | `agents/static_analyst.md` | Offline binary analysis — disassembly, imports, strings, entropy |
| `dynamic_analyst` | `agents/dynamic_analyst.md` | Runtime/sandbox analysis — API traces, memory, behaviour |
| `deobfuscator` | `agents/deobfuscator.md` | Packing / obfuscation — unpacking, decoder identification |
| `debugger` | `agents/debugger.md` | Symbolic execution, vulnerability triage, PoC sketching |
| `documentation` | `agents/documentation.md` | Final synthesis into structured report |
| `chat` | `agents/chat.md` | Direct conversational responses (short-circuit, no tools used) |

---

## Agent Instruction Files (`agents/*.md`)

Each `.md` file is the **system prompt** for that agent. The file is loaded at runtime by `PromptEngine` and injected into the agent's first message.

### Location

```
ai-reo/
└── agents/
    ├── orchestrator.md
    ├── static_analyst.md
    ├── dynamic_analyst.md
    ├── deobfuscator.md
    ├── debugger.md
    ├── documentation.md
    └── chat.md
```

Override the directory at runtime with `AI_REO_AGENTS_DIR=/path/to/custom/agents`.

### File Format

```markdown
---
name: static_analyst        # must match the agent's internal name
version: "2.1"              # informational; not enforced
description: One-line role summary
when_to_use: |
  When the orchestrator should route to this agent.
---

You are the AI-REO Static Analyst — ...

## Section Heading

Instructions, rules, tool usage guidance.

## Template Variables

The following placeholders are substituted at call time:

- {session_id}      — current session UUID
- {current_goal}    — sub-goal assigned by the orchestrator
- {kg_summary}      — summary of the session Knowledge Graph (findings so far)
- {findings_count}  — number of KG nodes discovered so far
```

### Template Variables

| Variable | Where injected | Contents |
|---|---|---|
| `{session_id}` | All analysis agents | The active session UUID |
| `{current_goal}` | All analysis agents | Sub-goal assigned by orchestrator |
| `{kg_summary}` | Orchestrator, all specialists | Serialised knowledge graph summary |
| `{findings_count}` | Orchestrator | Count of discovered KG nodes |
| `{last_agent_summary}` | Orchestrator | Last agent's report summary |
| `{last_goal_completed}` | Orchestrator | Whether the last sub-goal was marked complete |
| `{last_findings_count}` | Orchestrator | Findings added by the last agent step |

Variables that have no value are substituted with an empty string.

---

## Customising an Agent

Edit the corresponding `agents/<name>.md` file. Changes take effect on the next server start (or immediately if using `PromptEngine.reload()`).

**Best practices:**
- Keep the YAML frontmatter (`---`) intact — `name` and `description` fields are required.
- Template variables (`{current_goal}`, etc.) must not be renamed — they are injected by `PromptEngine`.
- Add new sections rather than removing existing ones; agents depend on structural cues.
- Keep instructions specific: vague instructions produce vague tool invocations.

---

## Adding a New Agent

1. **Create the instruction file** at `agents/<your-agent>.md`.

2. **Create the agent class** in `src/ai_reo/agents/specialized.py`:
   ```python
   class YourAgent(BaseAgent):
       agent_name = "your_agent"
   ```
   `BaseAgent` handles skill injection, KG context formatting, and structured output parsing automatically.

3. **Register the node** in `src/ai_reo/agents/graph.py`:
   ```python
   from ai_reo.agents.specialized import YourAgent

   your_agent = YourAgent()

   async def your_agent_node(state: AgentState) -> AgentState:
       return await your_agent.step(state)

   workflow.add_node("your_agent", your_agent_node)
   ```

4. **Add a routing edge** from `orchestrator` to `your_agent`:
   ```python
   workflow.add_conditional_edges(
       "orchestrator",
       route_from_orchestrator,  # existing router
       {
           ...
           "your_agent": "your_agent",
       }
   )
   ```

5. **Add the agent name** to the orchestrator's instruction file (`agents/orchestrator.md`) under the "Available Specialist Agents" section so the orchestrator knows when to route there.

---

## How Skills Are Injected

Skills relevant to an agent are automatically prepended to its system prompt at runtime. The `SkillLoader` selects skills where `targets` includes the agent's name (or the skill has no `targets`, making it universal).

See [skills.md](skills.md) for the full skills documentation.
