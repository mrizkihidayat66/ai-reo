# Skills System — Integration Guide

Skills are reusable instruction files that are automatically injected into an agent's context when relevant. They encode domain knowledge — recommended tool sequences, threat-hunting patterns, vulnerability checklists — that any agent can act on without duplicating that knowledge in every agent prompt.

---

## Concept

When an agent runs, the `SkillLoader` scans the `skills/` directory, selects skills that apply to that agent (by `targets` match or universal), and prepends them as additional system context. The agent reads the skill body as additional instructions.

This aligns with the [Anthropic SKILL.md specification](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview):
- Skills are **directories** containing a `SKILL.md` file.
- Loading is tiered: L1 (metadata only, always present), L2 (full body, loaded on match).

---

## Directory Structure

```
ai-reo/
└── skills/
    ├── malware-analysis/
    │   └── SKILL.md
    ├── vulnerability-research/
    │   └── SKILL.md
    └── firmware-analysis/
        └── SKILL.md
```

Each skill is a **named directory** containing `SKILL.md`. Additional reference files or scripts can live alongside `SKILL.md` in the directory.

Override the skills directory with `AI_REO_SKILLS_DIR=/path/to/custom/skills`.

---

## SKILL.md Format

```markdown
---
name: malware-analysis          # required — lowercase, hyphens only, max 64 chars
description: >                  # required — what the skill does AND when to use it
  Structured workflow for malware triage, IOC extraction, and packer detection.
  Use when the user provides a suspicious or unknown PE binary.
targets: [static_analyst, deobfuscator]   # AI-REO extension: which agents receive this skill
---

# Skill Title

Skill body — markdown instructions, tables, ordered steps. Loaded when the skill is triggered.
```

### Frontmatter Fields

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique skill identifier. Lowercase, hyphens only. Max 64 characters. Must not contain "anthropic" or "claude". |
| `description` | Yes | What the skill does and when to use it. Max 1024 characters. Both parts are required. |
| `targets` | No (AI-REO extension) | List of agent names that receive this skill. Absent or empty = universal (all agents). |

---

## Bundled Skills

| Skill | Directory | Targets |
|---|---|---|
| Malware Static Analysis | `skills/malware-analysis/` | `static_analyst`, `deobfuscator` |
| Vulnerability Research | `skills/vulnerability-research/` | `debugger` |
| Firmware Analysis | `skills/firmware-analysis/` | `static_analyst`, `dynamic_analyst` |

---

## Writing a New Skill

### 1. Create the directory and SKILL.md

```bash
mkdir skills/my-new-skill
```

Create `skills/my-new-skill/SKILL.md`:

```markdown
---
name: my-new-skill
description: >
  Short description of what this skill does. Use when the user asks about <scenario>.
targets: [static_analyst]   # omit to make universal
---

# My New Skill

## Recommended Tool Order

1. **First step** — run `tool_name` with these parameters.
2. **Second step** — interpret output, look for X.

## Patterns to Look For

| Pattern | Significance |
|---|---|
| ... | ... |
```

### 2. Reload the server (or call SkillLoader.reload())

The skill loader caches on first load. In development, restart the server. In future: `POST /admin/reload-skills` (if implemented).

---

## How Skills Are Injected (Technical Detail)

The injection happens in `src/ai_reo/agents/base.py`. Before each agent step:

1. `SkillLoader.get_for_agent(agent_name)` is called.
2. Matching skills are concatenated and prepended to the agent's system prompt.
3. Each skill contributes its body (the markdown below the frontmatter).

The `when_to_use` / `description` field is NOT injected into the prompt — it is used internally to decide *whether* to load the skill in future (L1 metadata phase). Currently all matched skills are always loaded (L2).

---

## Skills vs. Agent Instructions

| | Agent instructions (`agents/*.md`) | Skills (`skills/*/SKILL.md`) |
|---|---|---|
| **Purpose** | Define an agent's role, rules, and fixed tool guidance | Provide domain-specific workflows and checklists |
| **Loading** | Always loaded for their specific agent | Selectively injected per agent per step |
| **Targeting** | One agent owns the file | Can target multiple agents, or be universal |
| **Edit frequency** | Rarely — foundational behaviour | Often — add/remove domain knowledge without touching agent code |
| **Format** | Agent-specific YAML frontmatter | Anthropic SKILL.md convention |
