# AI-REO - AI Reverse Engineering Orchestrator

> **Local-first, chat-driven binary analysis powered by a team of specialized AI agents.**

AI-REO lets you drop a binary into a session and talk to it - asking questions like *"what does this
binary do?"*, *"find any crypto routines"*, or *"is there an obvious vulnerability?"* - while a
coordinated swarm of agents runs real analysis tools on your behalf in isolated Docker containers,
streams findings back in real time, and builds an evolving knowledge graph of the target.

---

## How it works

```
+------------------------------------------------------------------+
|                     React / Vite Frontend                        |
|  Session Manager - Analysis Feed - Knowledge Graph - Providers   |
+----------------------------+-------------------------------------+
                             |  WebSocket + REST (port 9000)
+----------------------------v-------------------------------------+
|                       FastAPI Backend                            |
|  +----------------+   +--------------------------------------+   |
|  | LangGraph      |   | Tool Registry (15 tools)             |   |
|  | Orchestrator   +-->| radare2 - objdump - readelf - nm     |   |
|  | StaticAnalyst  |   | angr - upx - capa - yara - ghidra    |   |
|  | DynamicAnalyst |   | die - lief - floss - binwalk         |   |
|  | Deobfuscator   |   | checksec - unipacker                 |   |
|  | Debugger       |   +---------------+----------------------+   |
|  | Documenter     |                   | Docker containers        |
|  +-------+--------+                   | (isolated, per-run)      |
|          |                            +------------------------- |
|          v                                                       |
|  SQLite - Knowledge Graph - Skills - Session History             |
+------------------------------------------------------------------+
```

1. **Upload** a binary (ELF, PE, Mach-O, firmware, or raw shellcode) to a session.
2. **Ask** a natural-language goal in the chat bar.
3. The **Orchestrator** classifies intent, assigns sub-tasks, and routes to the right specialist.
4. Specialists invoke Docker-sandboxed tools - results stream instantly to the feed.
5. Findings accumulate in a **knowledge graph** that agents query on subsequent turns.
6. **Skills** inject domain-specific workflows (malware triage, vuln research, firmware analysis)
   directly into the agent context.
7. A **Documentation** agent synthesises everything into a structured report.

---

## Feature Highlights

| Feature | Details |
|---|---|
| **Multi-agent graph** | LangGraph: Orchestrator -> Static Analyst -> Dynamic Analyst -> Deobfuscator -> Debugger -> Documentation |
| **15 sandboxed tools** | radare2, objdump, readelf, nm, angr, UPX, capa, YARA, Ghidra, DIE, LIEF, FLOSS, binwalk, checksec, unipacker |
| **Native tools** | file_type, binary_info, bintropy, entropy_analysis, strings_extract, hex_dump, pefile, scripts (no Docker) |
| **Any LLM** | OpenAI, Anthropic, Google Gemini, Mistral, Ollama, LM Studio, or any OpenAI-compatible endpoint via litellm |
| **Multiple providers** | Configure different models per agent; switch or add providers live from the UI |
| **Streaming feed** | Real-time WebSocket feed with per-agent colour-coded bubbles and 3-dot typing indicator |
| **Pause / Resume** | Interrupt and continue long-running analyses, logged to session history |
| **Knowledge graph** | D3-powered live graph of discovered symbols, strings, function relations |
| **Skills system** | Domain-specific SKILL.md instruction files injected into agent context at runtime |
| **Full history** | Every agent response + user message persisted to SQLite; survives server restart |
| **Session manager** | Create, rename, switch sessions; each session keeps its own binary + history |

---

## Screenshots

![LLM Provider Configuration](docs/screenshots/providers.png)
![Analysis Tools](docs/screenshots/tools.png)
![AI-REO Sessions](docs/screenshots/sessions.png)
![Session Chat](docs/screenshots/chat.png)
![Result](docs/screenshots/result.png)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Lucide icons |
| API | FastAPI, WebSockets, REST |
| Agent workflow | LangGraph + LangChain-core |
| LLM routing | litellm (OpenAI / Anthropic / Google / Ollama / LM Studio / generic) |
| Database | SQLite via SQLAlchemy 2 |
| Analysis tools | Docker containers (per-tool Dockerfiles in `docker/`) |
| Python | 3.11+ |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend dev server)
- Docker Engine with internet access (to build or pull tool images on first run)

### 1 - Backend

```bash
# Clone
git clone https://github.com/mrizkihidayat66/ai-reo.git
cd ai-reo

# Virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux / macOS

# Install (editable mode)
pip install -e ".[dev]"

# Configure
copy .env.example .env     # Windows
# cp .env.example .env     # Linux / macOS

# Start backend (default: http://localhost:9000)
ai-reo
# or: uvicorn ai_reo.main:app --reload --port 9000
```

### 2 - Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### 3 - Verify

```bash
# Liveness
curl http://localhost:9000/health

# Readiness (DB + Docker daemon)
curl http://localhost:9000/ready
```

### 4 - Set up analysis tools

Open the web UI -> **Tools** page -> click **Build** for each tool you want.

This compiles the tool's Docker image from `docker/<tool>/Dockerfile`. Only required once; images
persist in the local Docker daemon.

---

## Environment Variables

```ini
# Server
AI_REO_HOST=127.0.0.1
AI_REO_PORT=9000
AI_REO_LOG_LEVEL=info

# Database
AI_REO_DATABASE_URL=sqlite:///~/.ai-reo/sessions.db

# Tool Integration & Storage
AI_REO_SESSIONS_DIR=tmp/.ai-reo/sessions
AI_REO_DOCKER_NETWORK=ai-reo-tools
AI_REO_MAX_TOOL_ROUNDS=32

# Reusable scripts directory (created on first script save)
# AI_REO_SCRIPTS_DIR=tmp/.ai-reo/scripts

# Production overrides (not needed for local development)
# AI_REO_SKILLS_DIR=~/.ai-reo/skills   # override bundled skills/
# AI_REO_AGENTS_DIR=~/.ai-reo/agents   # override bundled agents/
```

LLM provider credentials (API keys, base URLs, model names) are configured entirely at runtime
via the **Providers** page - not in `.env`.

---

## Project Structure

```
ai-reo/
+-- agents/                  # Per-agent system prompt .md files (source of truth)
|   +-- orchestrator.md
|   +-- static_analyst.md
|   +-- dynamic_analyst.md
|   +-- deobfuscator.md
|   +-- debugger.md
|   +-- documentation.md
|   \-- chat.md
+-- skills/                  # SKILL.md domain knowledge files (Anthropic SKILL.md spec)
|   +-- malware-analysis/
|   +-- vulnerability-research/
|   \-- firmware-analysis/
+-- docker/                  # One Dockerfile per sandboxed tool
|   +-- angr/
|   +-- binwalk/
|   +-- capa/
|   +-- checksec/
|   +-- die/
|   +-- floss/
|   +-- lief/
|   +-- objdump/
|   +-- unipacker/
|   +-- upx/
|   \-- yara/
+-- src/ai_reo/
|   +-- agents/              # LangGraph agent nodes and graph definition
|   +-- api/                 # FastAPI routes, WebSocket manager, schemas
|   +-- db/                  # SQLAlchemy models, repositories, services
|   +-- llm/                 # litellm provider abstraction, prompt loader
|   +-- skills/              # SkillLoader - scans skills/ dir at runtime
|   +-- tools/               # Tool registry, Docker executor, native tools
|   +-- config.py            # Pydantic-Settings configuration
|   +-- exceptions.py        # Domain exception hierarchy
|   \-- main.py              # FastAPI app + Uvicorn entry point
+-- frontend/                # React / Vite SPA
|   \-- src/
|       +-- components/      # AnalysisDashboard, SessionManager, GraphPanel, ...
|       \-- context/         # WebSocketContext, ProvidersContext
+-- docs/                    # Integration guides
|   +-- agents.md            # How to customise / add agents
|   +-- skills.md            # How to write SKILL.md skill files
|   \-- tools.md             # How to add new Docker or native tools
+-- tests/
|   \-- unit/
+-- tmp/                     # Runtime data (sessions, scripts) - git-ignored
+-- pyproject.toml
+-- requirements.txt
\-- .env.example
```

---

## Analysis Tools

### Docker Tools (built locally from `docker/<tool>/Dockerfile`)

| Tool | Image | Notes |
|---|---|---|
| **radare2** | `radare2/radare2` | Pulled from Docker Hub |
| **objdump / readelf / nm** | `ai-reo/objdump:latest` | GNU binutils; three tools share one image |
| **angr** | `ai-reo/angr:latest` | Symbolic execution + CFG |
| **UPX** | `ai-reo/upx:latest` | Packer detection + decompression |
| **capa** | `ai-reo/capa:latest` | MITRE ATT&CK/MBC capability detection |
| **YARA** | `ai-reo/yara:latest` | Rule-based pattern matching |
| **Ghidra headless** | `blacktop/ghidra` | Pulled from Docker Hub; deep decompilation |
| **DIE** | `ai-reo/die:latest` | Detect-It-Easy packer/compiler ID |
| **LIEF** | `ai-reo/lief:latest` | Deep PE/ELF/Mach-O structural parser |
| **FLOSS** | `ai-reo/floss:latest` | FLARE obfuscated string solver |
| **binwalk** | `ai-reo/binwalk:latest` | Firmware signature scan + embedded file extraction |
| **checksec** | `ai-reo/checksec:latest` | Binary hardening audit (PIE, NX, canary, RELRO) |
| **unipacker** | `ai-reo/unipacker:latest` | Emulation-based PE unpacker |

All containers mount the session binary directory at `/mnt/staging` and are torn down after
each command.

See [docs/tools.md](docs/tools.md) for full integration documentation.

---

## Docs

| Guide | Description |
|---|---|
| [docs/agents.md](docs/agents.md) | Agent graph, instruction file format, how to add a new agent |
| [docs/skills.md](docs/skills.md) | SKILL.md format, how skills are injected, how to write new skills |
| [docs/tools.md](docs/tools.md) | Tool architecture, Docker lifecycle, how to add new tools |

---

## Running Tests

```bash
pytest tests/unit/ -q
```

Expected: **5 passed**.

---

## Roadmap / Known Limitations

- [ ] Persistent Neo4j knowledge graph (currently in-process D3 only)
- [ ] Agent-to-agent memory across sessions
- [ ] WASM / macOS Mach-O tool coverage
- [ ] Automated skill triggering via L1 metadata matching (currently all matched skills always loaded)

## Known Issues

- Some tools still fail during real analysis runs (for example: `angr`, `unipacker`, `capa`, `binwalk`, `bintropy`) even though they pass the current tool-health checks. The tool test flow needs deeper validation so readiness checks better reflect real execution conditions.
- In some runs, the session state moves to `completed` before the Orchestrator-to-Documentation handoff actually produces a final documentation response.
- The `/documentation` command does not always summarize only the delta since the last documentation step; it may repeat previously completed analysis and can stall without returning a documentation response.
- The Orchestrator and chat interaction flow still need improvements for routing consistency, response quality, and smoother user-facing session behavior.

---

## Experimental Project

This is an **experimental, work-in-progress** project. The architecture, APIs, and database schema
may change without notice between commits. It is intended for local use and security research in
controlled environments only.

**Suggestions, bug reports, and pull requests are warmly welcome!**

---

## License

MIT - see [LICENSE](LICENSE) for details.
