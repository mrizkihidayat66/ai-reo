---
name: string-decryption
description: >
  Techniques for identifying and decrypting obfuscated strings in malware and packed binaries.
  Covers stack strings, XOR loops, RC4 PRGA, Base64, custom alphabets, and IC-based cipher
  identification. Use when `strings` output shows few/no meaningful ASCII strings.
targets: [static_analyst, deobfuscator]
---

# String Decryption Skill

## Triage: Why Are Strings Missing?

When `strings` or FLOSS produce minimal output:

1. **Packed/encrypted**: Entire binary is compressed or encrypted — unpack first
2. **Stack strings**: Strings built byte-by-byte on the stack at runtime
3. **Encrypted string table**: Strings stored encrypted, decrypted by a routine before use
4. **Wide-char only**: Compiled with Unicode — use `strings -el` for UTF-16LE
5. **Heap-constructed**: Strings assembled dynamically using memcpy/strcat routines

---

## Step 1 — Always Run FLOSS First

**FLOSS** (FireEye/Mandiant) automatically recovers:
- Stack strings (emulation-based)
- Tight encoding loops (XOR/ROL/ADD)
- Simple decryption stubs

```bash
floss --no-static-strings malware.exe     # skip static strings, focus on decoded
floss -o floss_output.json malware.exe    # full JSON output
floss --functions 0x401000 malware.exe   # target specific function
```

If FLOSS recovers readable strings → proceed to analysis.
If FLOSS recovers nothing useful → use manual techniques below.

---

## Stack Strings (Assembly Pattern)

### x86 — byte at a time
```asm
; "cmd.exe" built on stack
mov byte ptr [ebp-8], 0x63   ; 'c'
mov byte ptr [ebp-7], 0x6D   ; 'm'
mov byte ptr [ebp-6], 0x64   ; 'd'
mov byte ptr [ebp-5], 0x2E   ; '.'
mov byte ptr [ebp-4], 0x65   ; 'e'
mov byte ptr [ebp-3], 0x78   ; 'x'
mov byte ptr [ebp-2], 0x65   ; 'e'
mov byte ptr [ebp-1], 0x00   ; NUL
```

### x64 — dword packing
```asm
; "cmd.exe" packed into two 32-bit moves
mov dword ptr [rsp+0h], 646D63h      ; "cmd"
mov dword ptr [rsp+3h], 6578652Eh   ; ".exe"
```

**Identification**: Multiple consecutive `mov byte` / `mov word` to same base register, followed by a call.
**Recovery**: Extract all imm8/imm16 values, assemble as bytes.

---

## Single-Byte XOR

Most common malware string obfuscation.

### Pattern in Assembly
```asm
; Loop XOR decryption: decrypt buffer at [esi] with key in dl
xor_loop:
  mov al, [esi]
  xor al, 0x41          ; fixed key byte
  mov [esi], al
  inc esi
  dec ecx
  jnz xor_loop
```

### Detection in Radare2
```
# Search for XOR with small immediate (key usually 1 byte)
/ xor; near immediate
# Search for XOR reg, imm8 patterns
/x 30??        # XOR r/m8, r8 (approximate)
```

### Brute-force all 255 keys (Python)
```python
data = bytes.fromhex("3d2b3a2c3b...")  # encrypted bytes
for key in range(1, 256):
    dec = bytes(b ^ key for b in data)
    printable = sum(0x20 <= c < 0x7f for c in dec)
    if printable / len(dec) > 0.8:
        print(f"key=0x{key:02x}: {dec.decode('latin1', errors='replace')}")
```

---

## Multi-byte / Rolling XOR

Key is 2+ bytes, or each byte of a multi-byte key is applied cyclically.

### Pattern (xor with key array)
```python
key = b"\xDE\xAD\xBE\xEF"
data = bytes([...])
dec = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
```

### Identification
- IC (Index of Coincidence) analysis — see below
- Key length: Kasiski / Keyspace analysis; try all key lengths 1–16
- radare2: look for loop accessing two arrays simultaneously

---

## RC4 PRGA Identification

RC4 is extremely common (no crypto library needed, <30 lines of C).

### KSA Loop Pattern
```asm
; i=256 iterations, j accumulated from key
; Look for: 256-byte S-box swap pattern
xchg [esi+eax], al     ; swap S[i] with S[j]
```

### PRGA Loop Pattern
```asm
; Two indices incrementing, XOR against output buffer
; S-box lookup → XOR plaintext byte
```

### Identifying RC4 Automatically
- FLOSS may catch it
- Look for 256-byte array initialization (S-box setup)
- FindCrypt IDA plugin / capa rule: RULE "RC4 via KSA"
- byte array initialized 0..255 sequentially = S-box

### Decryption (Python)
```python
from Crypto.Cipher import ARC4
key = bytes.fromhex("aabbccdd")
encrypted = bytes.fromhex("...")
cipher = ARC4.new(key)
print(cipher.decrypt(encrypted))
```

---

## Base64 Detection and Decoding

### Standard Base64 indicators
- Character set: `A-Z a-z 0-9 + / =`  
- Length multiple of 4 (with padding) or 4n±0..3 (without)
- Lookup table constant: `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/`

### Custom Base64
Malware often replaces `+/` with other chars. Look for:
- 64-character lookup table as a string constant
- Table access indexed by 6-bit chunks of input

### Finding the table in radare2
```
# Search for "ABCDEFGHIJKLMNOP" prefix of standard table
/ ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop
```

### Decoding custom Base64 (Python)
```python
import base64
STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
CUSTOM   = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
table = str.maketrans(CUSTOM, STANDARD)
result = base64.b64decode(encoded.translate(table))
```

---

## Index of Coincidence (IC) — Cipher Identification

IC measures letter frequency distribution. Plaintext English text: IC ≈ 0.065. Random: IC ≈ 0.038.

### Interpretation Table

| IC value | Likely cipher |
|---|---|
| ~0.065 | Plaintext or monoalphabetic substitution |
| ~0.052 | Vigenère with short key (key length = 2–5) |
| ~0.038–0.045 | Polyalphabetic / XOR with long key |
| ~0.038 | Stream cipher (RC4, ChaCha20) or block cipher (truly random-looking) |

### Purpose in RE
- IC ~0.038–0.040 on extracted buffer → XOR with key > 1 byte, or strong cipher
- If known key length exists, slice buffer at key-length intervals → IC per slice → if IC ~0.065, XOR key found
- Very low IC on short string (< 16 bytes) → too short to be meaningful

### Python IC Calculation
```python
def ic(data: bytes) -> float:
    n = len(data)
    if n < 2: return 0.0
    freq = [0] * 256
    for b in data: freq[b] += 1
    return sum(f * (f-1) for f in freq) / (n * (n-1))
```

---

## String Table Recovery Workflow (Full Process)

```
1. strings -a -n 5 binary                      # quick triage
2. floss binary                                 # FLOSS emulation
3. If FLOSS partial: radare2 /R / xor loops    # find decryption functions
4. Identify: stack-string / XOR / RC4 / B64    # based on pattern above
5. If XOR: brute-force key (see above)          # Python script
6. If RC4: find key in binary (hardcoded near decryption call or in config block)
7. If unknown: collect encrypted buffer + key from dynamic trace
   - Breakpoint on decryption routine call
   - Capture input args (buffer ptr, key ptr, length)
8. Cross-reference decrypted strings with:
   - Known C2 indicators (IP:port, domain patterns)
   - API function names (LoadLibraryA, GetProcAddress)
   - Registry paths, file paths
```

---

## Common Mistakes to Avoid

- Assuming XOR key = 1 byte when IC is still low after 1-byte brute force (try multi-byte)
- Treating all null-looking buffers as encoded (verify length > 4 first)
- Ignoring wide-char strings (`strings -el` or FLOSS with `--wide`)
- Stopping after FLOSS if a custom decrypt stub is used (FLOSS emulation depth is limited)
