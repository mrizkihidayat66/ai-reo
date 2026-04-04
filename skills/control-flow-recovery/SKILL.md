---
name: control-flow-recovery
description: >
  Techniques for reconstructing high-level control flow from compiled binaries: loop
  identification, switch/jump table resolution, control flow flattening (CFF) detection and
  simplification, and opaque predicate removal. Use when disassembly shows complex branching,
  dispatcher patterns, or when you need to rebuild CFG from obfuscated code.
targets: [static_analyst, deobfuscator]
---

# Control Flow Recovery Skill

## Loop Pattern Recognition

### x86-64 Canonical Loop Forms
- **`for` loop**: `mov ecx, N` (init) → `cmp ecx, 0` (cond) → body → `dec ecx; jnz body` (back-edge)
- **`while` loop**: `jmp cond_block` → body → `cond_block: cmp; jle body` back-edge
- **`do-while` loop**: body executes first, back-edge at bottom — `cmp; jnz body`
- **Key signal**: a `jmp` (conditional or unconditional) whose target is a lower address than the instruction itself is a loop back-edge.

### ARM Loop Forms
- `CBZ`/`CBNZ` at loop bottom for zero/non-zero checks
- `SUBS; BNE` pattern for counted loops

### radare2 Loop Discovery
```
# Full CFG in ASCII (shows back-edges visually)
agf @sym.target_function

# CFG in JSON (parse programmatically)
agfd @sym.target_function

# Pseudo-C decompilation (shows loops as while/for)
pdc @sym.target_function
```

---

## Switch / Jump Table Resolution

### Indirect Jump Pattern (x86-64)
```asm
; Case selector in rax
lea    rcx, [rip + table]      ; load table address
movsxd rax, dword [rcx + rax*4] ; load signed 32-bit offset from table
add    rax, rcx                 ; compute absolute target
jmp    rax                      ; indirect jump
```

### radare2 Resolution
```
# Tag all indirect branches in function
aht @sym.target_function

# Inspect jump table entries
pxw 40 @ <table_address>

# List all basic block start addresses in function
afbj @sym.target_function
```

### IDA/Ghidra Handling
- Ghidra: right-click unresolved indirect jump → "Override Jump Table" → specify table address + entry count
- Use `set switch table` if auto-analysis failed

---

## Control Flow Flattening (CFF) Detection

### Characteristics
1. A single large function containing many `case_N:` blocks all at the same nesting level
2. A **dispatcher block** near the top containing: `cmp eax, CONSTANT; je case_N` chains
3. Every basic block ends with `mov eax, NEXT_STATE; jmp dispatcher`
4. A single **state variable** (often in `eax`/`edi`) controls all transitions
5. All blocks have the same CFG nesting depth — no natural loop structure visible

### Detection with radare2
```
# High basic-block count with many cross-edges → CFF
afij @sym.target_function | python -c "import sys,json; d=json.load(sys.stdin); print(d['nbbs'], 'blocks,', d['nindegree'], 'in-degree')"

# Look for repeated state-variable pattern
pd 200 @sym.target_function | grep -E "mov (eax|edi|esi), 0x[0-9a-f]+"
```

### CFF Simplification Strategy
1. Identify the state variable register (most-written register before `jmp dispatcher`)
2. Map state value → block address by logging all `cmp eax, N` comparisons
3. Trace state transitions: each block's exit assignment reveals the next state
4. Reconstruct linear flow by ordering blocks by state-transition sequence
5. Use angr `simgr.explore()` to symbolically enumerate all reachable states if manual mapping is infeasible

---

## Opaque Predicates (Bogus Control Flow)

### Common Patterns
| Pattern | Always evaluates to | Example |
|---|---|---|
| `x * (x - 1)` is always even | `jz dead_branch` (dead) | `mov eax, x; imul eax, eax; dec eax; test eax, 1; jz dead` |
| `(x & 0xFFFF0000)` on byte value | `jnz dead_branch` (dead) | `movzx eax, byte [rbp-1]; test eax, 0xFFFF0000; jnz dead` |
| `7 * y - 1` mod arithmetic | Constant parity | Used in OLLVM BCF passes |
| Constant comparison | Dead path obvious | `cmp eax, eax; jne dead` |

### Detection
- Opaque predicates involve computations on values that can be statically resolved
- angr `solver.eval(cond, n=2)` returning only 1 unique value confirms opaque predicate
- Pattern: `test reg, constant_mask` where mask has no bits in common with register's known range

### Removal
- Patch dead branch: change `jne dead` → `jmp live` (NOP the condition, force the live path)
- Use radare2: `wa jmp 0xLIVE_ADDR @ <opaque_jmp_addr>`

---

## Useful radare2 CFG Commands Reference

| Command | Effect |
|---|---|
| `agf @func` | ASCII CFG of function |
| `agfd @func` | JSON CFG dump |
| `agft @func` | Tree-based CFG |
| `pdc @func` | Pseudo-C decompilation |
| `afbj @func` | List all basic blocks as JSON |
| `afij @func` | Function info JSON (nbbs, size, complexity) |
| `aht @func` | Resolve indirect jump tables |
| `/R/ pop rdi; ret` | Search for ROP gadgets |
| `axf @addr` | List all x-refs FROM address |
| `axt @addr` | List all x-refs TO address |
