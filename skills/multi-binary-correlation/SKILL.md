---
name: multi-binary-correlation
version: "1.0"
description: Methodology for analyzing multiple related binaries in a single session
applies_to:
  - static_analyst
  - crypto_analyst
  - dynamic_analyst
---

# Multi-Binary Correlation Skill

## When Multiple Binaries Are Present

Sessions may contain multiple related binaries (e.g., a main executable + a loader, a game client +
a patcher, a malware dropper + a payload, or a server binary + a client binary).

## Triage Order

1. **Identify all binaries** using `fs_read` or `binary_info` on each file in the session workspace.
2. **Triage each binary** with at minimum `file_type` + `entropy_analysis` before deep analysis on any single file.
3. **Classify relationships** — look for:
   - Matching import/export names between binaries
   - Shared string literals (same encryption key or config string)
   - Same compiler signature or build timestamp
   - Cross-binary function calls (loader → main executable)
   - Shared section patterns or packer signatures

## Shared Crypto Key Patterns

If two binaries share the same RC4 KSA initialization, AES key bytes, or XOR key pattern, this is
strong evidence they are from the same codebase or developer:
- Extract the key material from each binary independently
- Compare byte-for-byte — even a partial match (e.g., first 8 bytes) is significant
- Document the match in findings as a separate `correlation` finding

## Loader/Payload Relationships

A common pattern: binary A (loader) spawns binary B (payload) via:
- `CreateProcess` / `ShellExecute` with the second binary's path as a string argument
- Dropping binary B to %TEMP% and loading it
- Loading binary B as a DLL via `LoadLibrary`

Indicators:
- Binary A has `CreateProcess` or `WriteFile` + `CreateThread` imports
- Binary A contains a string matching binary B's name or path
- Binary B has very few imports (was designed to be loaded, not run standalone)

## Reporting Multi-Binary Correlation Findings

```json
{
  "finding_type": "behavior",
  "address": "N/A",
  "name": "cross_binary_correlation",
  "description": "Binary A (loader.exe) contains string 'payload.dll' and CreateProcess import matching binary B (payload.dll) which has only 3 imports consistent with injection target",
  "raw_evidence": "<relevant strings/imports output>",
  "confidence": "high"
}
```

## Analysis Prioritization

When multiple binaries exist and time is limited, prioritize in this order:
1. The binary the user's objective names explicitly
2. Binaries with fewer imports (more likely to be packed payloads worth unpacking)
3. Binaries with recognizable names (e.g., matching filenames found as strings in other binaries)
4. DLLs (usually more interesting exports than executables)
5. Remaining binaries (basic triage only)
