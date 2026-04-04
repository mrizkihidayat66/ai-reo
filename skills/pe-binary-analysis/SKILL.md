---
name: pe-binary-analysis
version: "1.0"
description: Methodology and reference for Windows PE binary static analysis
applies_to:
  - static_analyst
  - crypto_analyst
  - deobfuscator
---

# PE Binary Analysis Skill

## Standard PE Section Names and Meanings

| Section | Purpose | High Entropy Meaning |
|---------|---------|---------------------|
| `.text` | Executable code | Likely packed/encrypted |
| `.data` | Initialized globals | Unusual — may contain config blobs |
| `.rdata` | Read-only data, strings, import descriptors | Unusual — may hide crypto keys |
| `.rsrc` | Resources (icons, dialogs, version info) | May contain embedded payloads |
| `.reloc` | Base relocation table | Rarely packed |
| `UPX0`, `UPX1` | UPX packer sections | Always high entropy — use `upx` tool |
| `.themida`, `.winlice` | Themida/WinLicense protector sections | Very high entropy — use `unlicense` |
| `.vmp0`, `.vmp1` | VMProtect sections | Very high entropy — VM bytecode inside |

## CLI Tool Disambiguation

| Tool | Best For | Limitations |
|------|----------|-------------|
| `pefile` | PE IAT/EAT, sections, COFF header, TLS — structured JSON | Windows PE only |
| `radare2` | Disassembly, xrefs (`axtj`), function list (`afl`), string search (`iz`) | Slower on large binaries |
| `lief` | Deep PE/ELF/Mach-O parsing, signatures, TLS callbacks, auth attributes | No disassembly |
| `readelf` | ELF-specific — dynamic section, symbol table | Linux ELF only |
| `nm` | ELF export symbols | Linux ELF only |
| `objdump` | GNU disassembly — simpler than radare2 | Less structured output |
| `ghidra_headless` | Pseudo-C decompilation | High latency; requires Docker |
| `angr` | CFG construction, symbolic execution | Very slow for large binaries |
| `checksec` | Security mitigation flags | Output only, no disassembly |

## Radare2 Key Commands for PE Analysis

```
# Function list (JSON)
afl

# Disassemble function (JSON)
pdfj @<addr>
pdfj @main

# Cross-references to an address
axtj @<addr>

# Imports
iij

# Exports
iEj

# Strings
izj

# Search hex pattern
/x <hex>

# Search instruction
/ai xor

# Filter function list by name
afl~<keyword>
```

## PE Analysis Workflow (Recommended Order)

1. `file_type` — confirm PE format, bitness
2. `binary_info` — size, hash
3. `die` — packer/compiler/protector detection
4. `entropy_analysis` — identify high-entropy sections
5. `pefile mode=summary` — PE headers, imports, exports, sections
6. `floss` — obfuscated strings (or `strings_extract` if floss fails FILE_TOO_LARGE)
7. `radare2` — disassembly of entry point and key functions
8. `capa` — capability detection (skip if binary is packed — capa will return exit 12)
9. `lief` — deep structural inspection if needed (TLS callbacks, signatures)
10. `checksec` — security mitigations

## Compiler/Linker Fingerprinting

| Signature | Compiler/Linker |
|-----------|----------------|
| `MSVCP*.dll` in imports | MSVC C++ runtime |
| `_CRT_INIT` in `.text` | MSVC C runtime |
| `CreateThread` + `_beginthreadex` | MSVC multithreaded |
| `gcc_` symbols in ELF | GCC |
| `LIBCMT.lib` string | Static MSVC CRT |
| Section named `.idata` | MSVC default |
| Section named `.plt` | GCC/LLVM/ELF |
