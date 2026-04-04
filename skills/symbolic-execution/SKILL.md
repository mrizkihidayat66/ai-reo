---
name: symbolic-execution
description: >
  Symbolic execution with angr for automated program analysis, vulnerability discovery,
  path exploration, and constraint solving. Covers explore(), SimProcedures, path explosion
  mitigation, and decision making when angr is and isn't appropriate.
targets: [debugger, exploit_developer]
---

# Symbolic Execution Skill

## When to Use angr (vs NOT use it)

### Use angr when:
- Binary has complex input validation with multiple nested conditions (password/serial check)
- You need to find all paths reaching a dangerous function (`system`, `execve`, memory copy)
- Manual analysis of branching is prohibitively complex (50+ conditions)
- CTF challenges with symbolic input checking
- Finding inputs that avoid anti-analysis paths

### Do NOT use angr when:
- Binary has crypto (AES/SHA-256/RSA) — path explosion guaranteed; use hook or skip
- High-loop-count operations processed per input byte — state space explodes
- Binary is a packed/obfuscated loader — symbolic execution on packed code produces noise
- Binary is highly multithreaded — angr has limited concurrency support
- You only need to understand data flow (static analysis is faster)

---

## Basic Project Setup

```python
import angr
import claripy

# Load binary
project = angr.Project('./binary', auto_load_libs=False)
# auto_load_libs=False: use angr's built-in SimProcedures for libc instead of loading real libc
# (much faster for most analyses)

# Create symbolic state at entry point
initial_state = project.factory.entry_state()

# Or start at a specific function address
initial_state = project.factory.blank_state(addr=0x401234)
```

---

## Symbolic Input

```python
# Symbolic stdin (for programs reading from stdin)
flag = claripy.BVS('flag', 8 * 32)  # 32 symbolic bytes
initial_state = project.factory.full_init_state(
    stdin=angr.SimFile('<stdin>', content=flag, size=32)
)

# Symbolic argv[1]
arg1 = claripy.BVS('arg1', 8 * 32)
initial_state = project.factory.entry_state(
    args=['./binary', arg1],
    add_options={angr.options.SYMBOLIC_WRITE_ADDRESSES}
)

# Symbolic memory region
sym_buf = claripy.BVS('buf', 8 * 64)
initial_state.memory.store(0x601000, sym_buf)  # BSS buffer
```

---

## Path Exploration (explore)

```python
# Create simulation manager
simgr = project.factory.simulation_manager(initial_state)

# Basic explore: find target, avoid bad paths
simgr.explore(
    find=0x40123f,    # address to reach (success)
    avoid=[0x401500, 0x401600],  # addresses to avoid (failure exits)
    timeout=300       # seconds
)

# Check results
if simgr.found:
    found_state = simgr.found[0]
    # Evaluate symbolic variable concretely
    solution = found_state.solver.eval(flag, cast_to=bytes)
    print(f"Solution: {solution}")
else:
    print("No path found (path explosion or unreachable)")
```

### finding/avoid via function name
```python
# If debug symbols available:
find_addr = project.loader.main_object.plt['target_function']

# If using symbols:
find_addr = project.kb.labels.lookup('check_success')
```

---

## SimProcedures (Hooking)

Use SimProcedures to replace expensive or problematic functions with simplified models.

### Replacing a crypto function (prevents path explosion)
```python
class FakeSHA256(angr.SimProcedure):
    def run(self, input_ptr, input_len, output_ptr):
        # Symbolic output: don't model SHA-256, just mark output as symbolic
        output = self.state.solver.BVS('sha256_out', 256)
        self.state.memory.store(output_ptr, output)

project.hook_symbol('SHA256', FakeSHA256())
# Or hook by address:
project.hook(0x401A00, FakeSHA256())
```

### Replacing sleep/time to avoid hangs
```python
class NoopSleep(angr.SimProcedure):
    def run(self, seconds):
        return  # do nothing

project.hook_symbol('sleep', NoopSleep())
project.hook_symbol('usleep', NoopSleep())
project.hook_symbol('nanosleep', NoopSleep())
```

### Replacing anti-debug checks
```python
class FakePtrace(angr.SimProcedure):
    def run(self, request, pid, addr, data):
        return self.state.solver.BVV(0, 64)  # return 0 = "not being debugged"

project.hook_symbol('ptrace', FakePtrace())
```

---

## Path Explosion Mitigation

### Symptom: explore() runs forever, thousands of states, no result

### Technique 1: Limit active states
```python
simgr.explore(
    find=target_addr,
    avoid=avoid_addrs,
    step_func=lambda sm: sm.drop(stash='active', filter_func=lambda s: len(sm.active) > 300)
)
```

### Technique 2: Use DFS instead of BFS
```python
# Default is BFS; switch to DFS (fewer simultaneous states)
simgr = project.factory.simulation_manager(state)
simgr.use_technique(angr.exploration_techniques.DFS())
simgr.explore(find=target_addr)
```

### Technique 3: Avoid loops via Loopbound veritesting
```python
simgr.use_technique(angr.exploration_techniques.LoopSeer(bound=5))
simgr.use_technique(angr.exploration_techniques.Veritesting())
```

### Technique 4: Add manual path pruning
```python
# Hook a function that causes explosion (e.g., printf) with a noop returning 0
class Noop(angr.SimProcedure):
    def run(self, *args): return self.state.solver.BVV(0, 64)

for sym in ['printf', 'fprintf', 'sprintf', 'snprintf', '__printf_chk']:
    if project.loader.find_symbol(sym):
        project.hook_symbol(sym, Noop())
```

---

## Password / Serial Key Bypass

Classic CTF/crackme use case:

```python
project = angr.Project('./crackme', auto_load_libs=False)

# Symbolic argv[1]
password = claripy.BVS('password', 8 * 16)  # 16-char password
state = project.factory.entry_state(args=['./crackme', password])

# Find success message, avoid failure
simgr = project.factory.simulation_manager(state)
simgr.explore(find=lambda s: b'Correct' in s.posix.dumps(1),
              avoid=lambda s: b'Wrong' in s.posix.dumps(1))

if simgr.found:
    sol_state = simgr.found[0]
    # Get concrete value
    passwd = sol_state.solver.eval(password, cast_to=bytes)
    print(f'Password: {passwd.rstrip(b"\\x00")}')
```

---

## Constraint Solving (Manual)

For when you know the constraints and just need a solution:

```python
import angr, claripy

solver = claripy.Solver()
x = claripy.BVS('x', 32)
y = claripy.BVS('y', 32)

# Add constraints reflecting program logic
solver.add(x + y == 100)
solver.add(x * 3 == y - 10)

if solver.satisfiable():
    print(f"x = {solver.eval(x)}, y = {solver.eval(y)}")
```

---

## Vulnerability Discovery

Find all paths reaching a dangerous function:

```python
# Find all states that reach system() or execve()
dangerous = project.loader.main_object.plt.get('system', None)
if dangerous is None:
    dangerous = project.loader.min_addr  # or find by pattern

simgr = project.factory.simulation_manager(initial_state)
simgr.explore(find=dangerous)

for s in simgr.found:
    # Dump all symbolic inputs that lead there
    if s.solver.satisfiable():
        inp = s.posix.dumps(0)  # stdin
        print(f"Dangerous path reached with input: {inp.hex()}")
```

---

## angr Quick Reference

| Task | Code |
|---|---|
| Explore to address | `simgr.explore(find=addr)` |
| Avoid addresses | `simgr.explore(avoid=[a1, a2])` |
| Symbolic stdin | `angr.SimFile('<stdin>', content=sym, size=N)` |
| Symbolic argv | `factory.entry_state(args=['prog', sym_val])` |
| Hook by name | `project.hook_symbol('func', MySimProc())` |
| Evaluate result | `state.solver.eval(sym_var, cast_to=bytes)` |
| Check satisfiable | `state.solver.satisfiable()` |
| Add constraint | `state.solver.add(sym_var == value)` |
| Get stdout | `state.posix.dumps(1)` |
| Get stdin | `state.posix.dumps(0)` |
