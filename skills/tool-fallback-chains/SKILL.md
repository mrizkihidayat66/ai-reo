---
name: tool-fallback-chains
version: "1.0"
description: Universal fallback chains for when primary tools fail or are unavailable
applies_to:
  - static_analyst
  - crypto_analyst
  - deobfuscator
  - dynamic_analyst
  - network_analyst
---

# Tool Fallback Chains

When a primary tool fails (TOOL_NOT_READY, exit_code != 0, FILE_TOO_LARGE, or exit 12), apply
the fallback chain for that tool rather than reporting a blocked state.

## Static Analysis Fallbacks

| Primary Tool | Failure Condition | Fallback(s) in Order |
|---|---|---|
| `ghidra_headless` | TOOL_NOT_READY, exit_code != 0 | 1. `angr` (CFG + function list) → 2. `radare2` with `pdfj @<addr>` (disassembly), `axtj @<addr>` (xrefs), `afl` (function list) |
| `floss` | FILE_TOO_LARGE (exit_code=1) | `strings_extract` with min_length=6 |
| `capa` | exit_code=12 (packed binary) | Route to `deobfuscator` first, then retry `capa` on the output file |
| `angr` | TOOL_NOT_READY, timeout | `radare2` with `afl` + `pdfj @fcn.XXXX` for function analysis |
| `die` | TOOL_NOT_READY | Manual entropy scan via `pefile` section entropy + `lief` imports check |
| `lief` | TOOL_NOT_READY | `pefile mode=full` for PE; `readelf -a` for ELF |
| `pefile` | error | `lief` — equivalent PE parsing with similar field coverage |
| `checksec` | TOOL_NOT_READY | `readelf -l` (inspect PT_GNU_STACK, PT_GNU_RELRO for NX/RELRO) |
| `objdump` | error | `radare2` with `pd` command |

## Unpacking/Deobfuscation Fallbacks

| Primary Tool | Failure Condition | Fallback(s) in Order |
|---|---|---|
| `upx` (decompress) | exit_code != 0 | Try `unpacker` tool; then use `radare2` OEP tracing manually |
| `unlicense` | exit_code != 0 | `pe_sieve` to scan for unpacked pages; `hollows_hunter` for process state |
| `unpacker` | TOOL_NOT_READY | `angr` symbolic execution from entry point to find OEP |

## Crypto Analysis Fallbacks

| Primary Tool | Failure Condition | Fallback(s) in Order |
|---|---|---|
| `ghidra_headless` | unavailable | `angr` for symbolic execution of key derivation; `radare2 pdfj` for manual inspection |
| `capa` | exit_code=12 | Note packing; fall back to manual constant search via `radare2 /x <pattern>` and `yara` |

## Dynamic Analysis Fallbacks

| Primary Tool | Failure Condition | Fallback(s) in Order |
|---|---|---|
| `frida` | TOOL_NOT_READY | `qiling` for full emulation without process spawn |
| `qiling` | TOOL_NOT_READY | `cape_analysis` for sandbox execution |
| `cape_analysis` | unavailable | `dynamic_analyst` should note this and use static heuristics only |

## Key Principle
A tool failure is a routing decision point, NOT a terminal condition.
- If the fallback succeeds → continue analysis with the fallback output.
- If ALL fallbacks fail → include a specific `blocked_reason` in findings listing exactly which tools failed and what was tried.
- NEVER set `goal_completed: false` and `blocked_reason: "tool unavailable"` without first attempting at least one fallback from this table.
