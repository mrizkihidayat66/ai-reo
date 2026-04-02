# Tool Integration Guide

AI-REO tools fall into two categories:

- **Docker-based tools** — run in isolated containers; each has its own `Dockerfile` under `docker/<tool>/`
- **Native tools** — pure-Python; run in the FastAPI process; no Docker required

---

## Tool List

### Docker-Based Tools

| Tool name | Docker image | Source directory | What it does |
|---|---|---|---|
| `radare2` | `radare2/radare2` | (pulled from Docker Hub) | Disassembly, CFG, strings, function list, cross-refs |
| `objdump` | `ai-reo/objdump:latest` | `docker/objdump/` | Section headers, raw disassembly (GNU binutils) |
| `readelf` | `ai-reo/objdump:latest` | (shares objdump image) | ELF structure, dynamic symbols, segment info |
| `nm` | `ai-reo/objdump:latest` | (shares objdump image) | Symbol table extraction |
| `angr` | `ai-reo/angr:latest` | `docker/angr/` | Symbolic execution, CFG, function discovery |
| `upx` | `ai-reo/upx:latest` | `docker/upx/` | UPX packer detection and decompression |
| `capa` | `ai-reo/capa:latest` | `docker/capa/` | MITRE ATT&CK / MBC capability detection (FLARE) |
| `yara` | `ai-reo/yara:latest` | `docker/yara/` | Rule-based pattern matching |
| `ghidra_headless` | `blacktop/ghidra` | (pulled from Docker Hub) | Deep pseudo-C decompilation via Ghidra headless |
| `die` | `ai-reo/die:latest` | `docker/die/` | Detect-It-Easy packer/compiler identification |
| `lief` | `ai-reo/lief:latest` | `docker/lief/` | PE/ELF/Mach-O structure parser |
| `floss` | `ai-reo/floss:latest` | `docker/floss/` | Obfuscated string solver (FLARE FLOSS) |
| `binwalk` | `ai-reo/binwalk:latest` | `docker/binwalk/` | Firmware signature scan + embedded file extraction |
| `checksec` | `ai-reo/checksec:latest` | `docker/checksec/` | Binary hardening audit (checksec.sh) |
| `unipacker` | `ai-reo/unipacker:latest` | `docker/unipacker/` | Emulation-based PE unpacker |

### Native Tools (No Docker)

| Tool name | Module | What it does |
|---|---|---|
| `file_type` | `tools/basic.py` | Magic-byte and extension-based file format ID |
| `binary_info` | `tools/basic.py` | Size, SHA256, entropy summary, MZ/ELF quick parse |
| `bintropy` | `tools/basic.py` | Per-section entropy + packer probability (bintropy) |
| `entropy_analysis` | `tools/basic.py` | Block-level entropy heatmap |
| `strings_extract` | `tools/basic.py` | UTF-8/UTF-16 string extraction |
| `hex_dump` | `tools/basic.py` | Hex + ASCII dump of arbitrary byte ranges |
| `pefile` | `tools/basic.py` | PE header, imports, exports, TLS (Windows only dep) |
| `fs_read` | `tools/basic.py` | Read session files (decompiled output, tool results) |
| `fs_write` | `tools/basic.py` | Write session files (intermediate artefacts) |
| `scripts_write` | `tools/basic.py` | Persist reusable scripts to `tmp/.ai-reo/scripts/` |
| `scripts_list` | `tools/basic.py` | List all persisted scripts |

---

## Docker Image Lifecycle

### First use ("Build" button on Tools page)

When a tool's button is clicked for the first time, the backend calls `ToolHealthService._build_local_image_if_supported()`, which:

1. Looks up the tool's `docker_image` tag in `local_image_map` inside `health.py`.
2. Finds the matching directory under `docker/<tool>/`.
3. Calls `docker images.build(path=docker/<tool>/, tag=<image>)`.
4. Streams build progress to the frontend.

Images tagged `ai-reo/*:latest` are built locally. Images without an entry in `local_image_map` (e.g. `radare2/radare2`, `blacktop/ghidra`) are pulled from Docker Hub on first use.

### Re-building

Delete the image manually (`docker rmi ai-reo/floss:latest`) and click **Build** again. The server will rebuild from the Dockerfile.

---

## Adding a New Docker Tool

### Step 1 — Write the Dockerfile

Create `docker/<toolname>/Dockerfile`:

```dockerfile
FROM python:3.11-slim
# or debian:bookworm-slim, etc.

LABEL org.opencontainers.image.title="ai-reo/<toolname>" \
      org.opencontainers.image.description="<tool description> for AI-REO"

RUN apt-get update \
    && apt-get install -y --no-install-recommends <system-deps> \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir <python-package>

WORKDIR /mnt/staging
VOLUME ["/mnt/staging"]
CMD ["/bin/sh"]
```

**Important**: Always mount `/mnt/staging` as a volume — the Docker executor mounts the shared staging directory here. All tool commands reference binaries as `/mnt/staging/<session_id>/binary/<filename>`.

### Step 2 — Implement the tool class

Add a new `DockerBasedTool` subclass in `src/ai_reo/tools/re_tools.py`:

```python
class MyTool(DockerBasedTool):
    """One-line description."""

    @property
    def name(self) -> str:
        return "my_tool"              # must be unique, lowercase, underscores

    @property
    def docker_image(self) -> str:
        return "ai-reo/my_tool:latest"   # must start with ai-reo/ for local build

    @property
    def description(self) -> str:
        return "What this tool does and when to use it."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path to the target binary",
                },
                # ... extra params
            },
            "required": ["filepath"],
            "additionalProperties": False,
        }

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        filepath = kwargs["filepath"]

        resolved = _resolve_binary_path(session_id, filepath)
        if isinstance(resolved, dict):
            return resolved

        if not self.is_ready():
            return {
                "error": "TOOL_NOT_READY",
                "message": f"Docker image '{self.docker_image}' not available.",
            }

        cmd = f"my-cli-command /mnt/staging/{session_id}/binary/{filepath}"
        res = docker_executor.execute(self.docker_image, cmd, timeout=60)

        output = res["output"].strip()
        if res["exit_code"] != 0:
            return {"error": output, "exit_code": res["exit_code"]}

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"output": output}
```

### Step 3 — Register the tool

Add the instance to the registry at the bottom of `re_tools.py`:

```python
tool_registry.register(MyTool())
```

Or, if registrations live in `registry.py`, follow the pattern there.

### Step 4 — Register the local image

Add the image tag → directory mapping in `src/ai_reo/tools/health.py` inside `local_image_map`:

```python
local_image_map = {
    ...
    "ai-reo/my_tool:latest": "my_tool",   # maps to docker/my_tool/
}
```

### Step 5 — Tell agents about the tool

Add the tool to the relevant agent instruction file(s) under `agents/`:

```markdown
## Tools Available
...
- my_tool: Brief description of what it does and suggested invocation.
```

---

## Adding a Native (Non-Docker) Tool

Native tools inherit from `BaseTool` in `src/ai_reo/tools/interface.py`:

```python
class MyNativeTool(BaseTool):

    @property
    def name(self) -> str: return "my_native"

    @property
    def description(self) -> str: return "..."

    def get_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {...}, "required": [...]}

    async def execute(self, session_id: str, **kwargs: Any) -> Any:
        # no Docker — run Python code directly
        ...
        return {"result": ...}
```

Register with `tool_registry.register(MyNativeTool())`.

---

## Staging Directory Layout

Each session gets an isolated working directory:

```
tmp/.ai-reo/sessions/
└── <session_uuid>/
    ├── binary/
    │   └── <uploaded-filename>     ← mounted read-only into containers
    └── <tool-output-files>         ← written by tools, readable via fs_read
```

Containers receive the staging root at `/mnt/staging` via Docker volume mount. The executor binds `sessions_dir` to this mount point.

---

## Persistent Scripts

Agent-generated reusable scripts are saved to `tmp/.ai-reo/scripts/` (configurable via `AI_REO_SCRIPTS_DIR`). This directory is **not** mounted into tool containers — it is only accessible via the `scripts_write` / `scripts_list` / `fs_read` native tools. Scripts here persist across sessions.
