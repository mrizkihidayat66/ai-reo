---
name: packer-unpacking
description: >
  Packer identification, OEP recovery, memory dump, IAT reconstruction, and per-packer
  decision trees for UPX, Themida/WinLicense, LLVM obfuscation, and custom packers.
  Use when binary has packer signatures, abnormally high entropy, or stripped imports.
targets: [deobfuscator]
---

# Packer Unpacking Skill

## Step 1 — Identify the Packer

```bash
# Always run die (Detect-It-Easy) first:
die malware.exe

# Also APKiD for Android:
apkid sample.apk

# Also capa for behavioral indicators:
capa malware.exe
```

### Common Packer Identifications and Actions

| Die Output | Packer | Action |
|---|---|---|
| `UPX [+, compressed]` | UPX | `upx -d malware.exe` (1 command) |
| `Themida [2.x / 3.x]` | Themida/WinLicense | Use `unlicense` tool first (see Themida section) |
| `ASPack` | ASPack | OEP + dump method below |
| `MPRESS` | MPRESS | OEP + dump method below |
| `Enigma Protector` | Enigma | Specialized tools / debug |
| `NSPack` | NSPack | OEP + dump method below |
| `PECompact` | PE Compact | OEP + dump method below |
| LLVM bitcode / suspicious CFG | LLVM obfuscation | See LLVM section below |
| No packer detected | Custom / unknown | Debug: trace execution path |

---

## Step 2A — UPX Unpacking

UPX is the most common open-source packer. Always try automated unpack first.

```bash
# Automated:
upx -d packed.exe -o unpacked.exe

# If UPX header was modified (breaks upx -d):
# Fix first 4 bytes of UPX signature if patched, OR use dynamic method below
```

If header is patched:
1. Load in x64dbg
2. Run to OEP using the popad trick (see below)
3. Dump + Scylla (UPX usually has intact IAT)

---

## Step 3 — OEP Recovery (Generic Method)

**OEP (Original Entry Point)** is the address where the original unpacked code begins.

### The popad / jmp Trick (x86 only)
Most x86 packers near the end of the unpacking stub execute:
```asm
popad        ; restore all registers from packed stack frame
jmp eax      ; jump to OEP
; OR:
push eax
retn         ; equivalent to jmp eax
```

### Method: Hardware Breakpoint on ESP
1. Load binary in x64dbg
2. Run until entry point (EP) of packer stub
3. Note current ESP value (e.g., 0x0018FF50)
4. In x64dbg: Hardware BP → On Access → Write → Address = [ESP-4] or set Write BP on ESP
5. `F9` Run → execution will break right before the final `jmp eax` / `retn` to OEP
6. Step over (F8) once → you are now at the OEP

### Identifying OEP
Signs you are at the OEP:
- Code looks "normal" (function prologue: `push ebp; mov ebp, esp`)
- Many API references suddenly visible in disassembly
- Die/CFF Explorer shows that IP is now inside the original `.text` section range
- Entropy of current code region drops significantly

### Method: Entry-Point Breakpoint on IAT entries
Set breakpoints on `GetCommandLineA` or `__security_init_cookie` (typical MSVC startup):
- `GetCommandLineA` is called early in CRT init
- After the packer resolves imports, breaking here puts you near OEP

---

## Step 4 — Memory Dump

### Using pe-sieve (automated)
```bash
# Scan and dump the process in-memory PE:
pe-sieve.exe /pid 1234 /dump 3
# Creates dump_*.exe in current directory
```

### Using x64dbg Plugin: `OllyDumpEx` / `Scylla`
1. Pause at OEP
2. Scylla: "Dump" button — saves current memory image as PE
3. This is the raw dump (IAT may still have thunks or zeros)

### Manual dump (for manual-map scenarios)
```bash
# In x64dbg: right-click on memory region → "dump to file"
# Save the .text + .rdata + .data sections
# Reconstruct PE header manually or use PhantomOEP to fix header
```

---

## Step 5 — IAT Reconstruction

After dumping, use Scylla to fix the IAT:
(See `import-reconstruction` SKILL for detailed Scylla workflow)

### Quick Scylla steps:
1. Attach to process at OEP, open Scylla
2. IAT Autosearch → Get Imports → review red (invalid) entries
3. Fix Dump on the dumped file → produces `_SCY.exe`

---

## Themida / WinLicense Unpacking

Themida is a strong commercial protector. Options in order of effort:

### Option 1: unlicense (automated, recommended first try)
```bash
# unlicense runs via Wine in Docker:
docker run --rm -v /path/to/binary:/work ai-reo/unlicense:latest
unlicense /work/themida_sample.exe
# Output: unpacked PE in current directory
```

### Option 2: Titanhide + x64dbg anti-anti-debug
1. Install Titanhide (kernel driver — hides debugger presence)
2. Load in x64dbg + ScyllaHide → configure all anti-debug bypasses
3. Step through Themida init (very slow — ~5 min)
4. Dump when original code is mapped

### Option 3: API Monitor approach
1. Use API Monitor to log calls without full debugging
2. When important APIs are first called (loading protected code), capture memory snapshot
3. Use pe-sieve on the process

---

## LLVM Obfuscation Analysis

LLVM-based obfuscation (ollvm, hikari, goron) applies transforms at the IR level:

### Identifying LLVM Obfuscation

| Technique | Indicators |
|---|---|
| Control Flow Flattening (CFF) | Large switch dispatch loop, single `main_switch`, all blocks at same nesting level |
| Bogus Control Flow (BCF) | Opaque predicates (`x*x - x` % 2 == 0`, always-true conditions) creating fake branches |
| Instruction Substitution | `a+b` replaced with `a-(-b)` or `a ^ b ^ (a&b<<1)` |
| String Encryption | String XOR/RC4 decrypt called before each use |
| MBA (Mixed Boolean Arith.) | Complex arithmetic identity expressions in conditions |
| VM Protection | Function replaced by bytecode interpreter |

### CFF De-obfuscation Workflow

See `control-flow-recovery` SKILL for detailed CFF analysis.

Quick checklist:
1. Identify the dispatcher switch in Ghidra/IDA (large switch statements, all cases same nesting)
2. Trace which case leads to which case (the `state_var` assignment at end of each block)
3. Reconstruct the true CFG by ordering cases by their determined successor state

### BCF Removal
```python
# radare2: find opaque predicates
# Pattern: condition always evaluates to true/false
# x * (x-1) is always even → (x*(x-1)) % 2 == 0 always true
# x*x + x always divisible by 2

# Replace always-true branches with unconditional jump:
# In radare2: wx <jmp_opcode_bytes> @ <address>
```

### String Decryption for LLVM-obfuscated binaries
Each string has an inline decryption call. Use FLOSS (emulation) or:
1. Find all `call decrypt_string` instructions
2. Breakpoint each, run, capture output argument
3. Or: extract all encrypted string buffers + key, write batch decryptor

---

## Custom Packer Debugging Flow

When packer is unknown/custom:

```
1. PE entry point → view first instructions
2. Is there a decryption loop?
   YES → step over loop → memory at destination should show valid PE (MZ header)
3. Is there a new PE mapped at runtime?
   YES → pe-sieve to dump it
4. Is execution transferred to new region after unpacking?
   YES → set BP on VirtualAlloc return → then set hardware execute BP at returned address
5. Run → break at first instruction of unpacked code → dump
6. Use Scylla to fix IAT
```

### Watching for PE mapping
```
// In x64dbg conditional BP:
bp VirtualAlloc
log "VirtualAlloc: size={rdx}, protect={r9}"
// When protection = PAGE_EXECUTE_READWRITE (0x40) → likely unpacking stub allocating executable region
```

---

## Quick Decision Matrix

```
Entropy > 0.85 for >80% of binary?
├─ YES: Packed/encrypted
│   ├─ Die says UPX?  → upx -d
│   ├─ Die says Themida?  → unlicense first
│   ├─ Die says LLVM?  → CFF analysis (see control-flow-recovery skill)
│   └─ Unknown?  → Debug OEP (ESP hardware BP method)
├─ NO: Not packed OR partially obfuscated
│   ├─ Code regions high entropy?  → String/import encryption
│   ├─ Imports = only LoadLibraryA + GetProcAddress?  → IAT hidden (see import-reconstruction skill)
│   └─ Weird CFG (CFF)?  → LLVM obfuscation
```

