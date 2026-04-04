---
name: anti-analysis-bypass
description: >
  Techniques for detecting and bypassing anti-debugging, anti-VM, anti-emulation, and
  timing/environment checks in malware and obfuscated binaries. Use when dynamic analysis
  fails silently, process terminates early, or behavior only appears in limited environments.
targets: [deobfuscator, dynamic_analyst]
---

# Anti-Analysis Bypass Skill

## Detection Hierarchy (check in order)

1. **Standard debugger checks** (most common — found in ~70% of malware)
2. **Process/environment enumeration** (often combined with #1)
3. **Timing checks** (RDTSC, GetTickCount, clock_gettime)
4. **VM / sandbox detection** (CPUID, registry, hardware, process lists)
5. **Emulation detection** (unsupported instruction abuse, I/O port reads)

---

## Windows Debugger Detection Techniques

### IsDebuggerPresent / CheckRemoteDebuggerPresent
```asm
; PEB.BeingDebugged == 1 when debugged
mov eax, fs:[0x30]        ; PEB pointer (x86) / gs:[0x60] (x64)
movzx eax, byte [eax+2]   ; BeingDebugged byte
test eax, eax
jnz detected
```
**Bypass**: ScyllaHide / x64dbg plugin → patches PEB.BeingDebugged to 0.
**Manual**: Use `WriteProcessMemory` or debugger's memory write to set PEB+2 = 0.

### NtQueryInformationProcess
```c
// ProcessDebugPort (0x7) returns non-null when debugged
NtQueryInformationProcess(GetCurrentProcess(), 7, &debug_port, 4, NULL);
// ProcessDebugFlags (0x1f) returns 0 when debugged
NtQueryInformationProcess(GetCurrentProcess(), 0x1f, &flags, 4, NULL);
```
**Bypass**: ScyllaHide hooks these; manually hook ntdll.dll with Frida.

### Heap Flags (PEB.NtGlobalFlag)
```asm
; PEB.NtGlobalFlag offset: 0x68 (x86) / 0xBC (x64)
; Under debugger: flags 0x70 = HEAP_TAIL_CHECKING | HEAP_FREE_CHECKING | HEAP_VALIDATE_PARAMETERS
; Normal: 0x00
mov eax, fs:[0x30]
mov eax, [eax + 0x68]   ; x86
and eax, 0x70
jnz detected
```
**Bypass**: ScyllaHide patches NtGlobalFlag; manual memory write to PEB+0xBC = 0.

### Heap Header Flags
```c
// Under debugger, heap block header at offset 0x0C uses different flag set
PROCESS_HEAP_ENTRY phe;
HeapWalk(GetProcessHeap(), &phe);
if ((phe.wFlags & PROCESS_HEAP_ENTRY_BUSY) && *(WORD*)((BYTE*)&phe + 0x22) == 0xABCD)
    detected;
```

---

## Windows Timing Checks

### RDTSC (timestamp counter)
```asm
; Execute RDTSC twice; delta > ~1000 cycles indicates debugger break
rdtsc
push eax
; ... small computation ...
rdtsc
sub eax, [prev_tsc]
cmp eax, 0x3E8          ; 1000 threshold (varies)
ja detected
```
**Bypass**: 
- ScyllaHide can handle some RDTSC checks
- Frida: hook `__rdtsc` or intercept RDTSC via VMware/Hyper-V TSC intercept
- Manually trace to the comparison and NOP/patch the branch

### GetTickCount / QueryPerformanceCounter
```c
DWORD t1 = GetTickCount();
// ... operation ...
DWORD t2 = GetTickCount();
if (t2 - t1 > 1000) exit(1);
```
**Bypass**: Frida hook `GetTickCount` → return constant or fixed increment

---

## Linux Debugger Detection

### TracerPid in /proc/self/status
```c
FILE *f = fopen("/proc/self/status", "r");
// Line: "TracerPid:\t1234" (non-zero = debugger attached)
```
**Bypass**: 
```bash
# LD_PRELOAD hook replacing fopen/fgets
# Or use gdb's 'handle SIGTRAP stop' + patch the branch
```

### ptrace self-attach
```c
// Only one process can ptrace another; if ptrace returns -1, we're already being traced
if (ptrace(PTRACE_TRACEME, 0, 0, 0) == -1) { exit(1); }
```
**Bypass**: 
```bash
# LD_PRELOAD wrapper:
long ptrace(int req, ...) { return 0; }
# Compile: gcc -shared -fPIC ptrace_hook.c -o ptrace_hook.so
# Run: LD_PRELOAD=./ptrace_hook.so ./binary
```

---

## VM / Sandbox Detection

### CPUID Vendor Check
```asm
; EBX:ECX:EDX should spell "GenuineIntel" or "AuthenticAMD"
; Known VM vendors:
;   VMware:    "VMwareVMware"
;   VirtualBox: "VBoxVBoxVBox"
;   Hyper-V:   "Microsoft Hv"
;   QEMU:      "TCGTCGTCGTCG"
xor eax, eax
cpuid
; compare EBX:ECX:EDX against known strings
```
**Bypass**: 
- VirtualBox: Guest Additions allow CPU masking via VBoxManage modifyvm
- VMware: Add `CPUID.1.ECX = "----:----:----:----:----:----:--0-:----"` to .vmx to hide hypervisor bit
- Frida: Hook CPUID handler in hardware-accelerated VMs is complex; use bare-metal or custom kernel

### Registry Checks (Windows)
Malware queries well-known VM artifacts:
```
HKLM\SOFTWARE\VMware, Inc.\VMware Tools
HKLM\HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\... (disk = "VBOX HARDDISK")
HKLM\SOFTWARE\Oracle\VirtualBox Guest Additions
```
**Bypass**: Registry editor to delete/rename keys; or use Cuckoo/FlareVM bare-metal agent.

### Process/Module Enumeration
Malware enumerates running processes for sandbox/AV artifacts:
```
vmtoolsd.exe, vboxservice.exe, wireshark.exe, procmon.exe, cuckoo.py, etc.
```
**Bypass**: Rename/hide monitor processes; use kernel-level process hiding via rootkit DBT.

### Hardware Fingerprinting
```c
// Low disk size (< 60GB) → VM
// Single CPU core → sandbox
// Display adapter: "VGA" or "SVGA" → VM  
// MAC address: 00:0C:29, 00:50:56 (VMware), 08:00:27 (VirtualBox)
```
**Bypass**: Configure VM with 2+ CPUs, 100+ GB disk, correct MAC prefix for real brand.

---

## Frida Bypass Scripts

### Hook IsDebuggerPresent
```javascript
const IsDebuggerPresent = Module.getExportByName('kernel32.dll', 'IsDebuggerPresent');
Interceptor.replace(IsDebuggerPresent, new NativeCallback(() => 0, 'int', []));
```

### Hook NtQueryInformationProcess
```javascript
const NtQIP = Module.getExportByName('ntdll.dll', 'NtQueryInformationProcess');
Interceptor.attach(NtQIP, {
  onLeave(retval) {
    // ProcessDebugPort = 7 → zero out result
    // ProcessDebugFlags = 0x1f → set result to 1
  }
});
```

### Hook open("/proc/self/status") on Linux
```javascript
const open = Module.getExportByName(null, 'open');
Interceptor.attach(open, {
  onEnter(args) {
    if (args[0].readUtf8String().includes('/proc/self/status')) {
      this.intercept = true;
    }
  }
});
```

---

## ScyllaHide (x64dbg plugin)

Automates most common Windows anti-debug bypasses:

| Feature | What it patches |
|---|---|
| PEB.BeingDebugged | Sets to 0 |
| NtGlobalFlag | Clears 0x70 flags |
| HeapFlags | Normalizes heap headers |
| NtQueryInformationProcess | Hooks and returns clean results |
| NtSetInformationThread | Blocks ThreadHideFromDebugger |
| OutputDebugString | Nullifies detection via error code change |
| BlockInput | Prevents AntiDebug keyboard block trick |

**Load**: x64dbg → Plugins → ScyllaHide → Options → enable all relevant hooks.

---

## Analysis Decision Flow

```
Binary terminates immediately?
├─ Check for IsDebuggerPresent/PEB checks first (most common)
├─ Add breakpoint on ExitProcess — check call stack
├─ If call from ntdll.dll RtlExitUserProcess → likely anti-debug
│   └─ Enable ScyllaHide, re-run
├─ Still exits? Check RDTSC/timing (set BP on rdtsc instruction)
├─ Check VM detection (CPUID, registry reads, process enumeration)
└─ Check network/internet connectivity checks (sometimes sandbox-specific)

Tool not executing payload?
├─ Check TracerPid (Linux) / NtQueryInformationProcess (Windows)
├─ Use LD_PRELOAD hook (Linux) or Frida (both)
└─ If Frida blocked: check if binary has Frida detection
   └─ Look for frida-agent.so, frida-server process enumeration
```
