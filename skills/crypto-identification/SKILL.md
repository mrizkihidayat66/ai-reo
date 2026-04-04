---
name: crypto-identification
description: >
  Identify cryptographic algorithms in compiled binaries by constant-matching, structural
  analysis, and function signature recognition. Use when strings/imports suggest encryption
  is present, when capa reports crypto-related techniques, or when a binary communicates
  over a network and its cipher is unknown.
targets: [static_analyst, crypto_analyst]
---

# Crypto Identification Skill

## Quick Reference: Known Crypto Constants

### AES
- **S-box first row**: `63 7c 77 7b f2 6b 6f c5 30 01 67 2b fe d7 ab 76`
- **radare2 search**: `/x 637c777bf26b6fc5`
- **KeyExpansion**: look for RCON table `01 02 04 08 10 20 40 80 1b 36`
- **AES-NI**: `aesenc`, `aesenclast`, `aesdec`, `aesdeclast`, `aeskeygenassist` instructions — immediate giveaway

### SHA-256
- **K constants (first 4)**: `0x428a2f98 0x71374491 0xb5c0fbcf 0xe9b5dba5`
- **radare2 search (little-endian)**: `/x 982f8a42`
- **H0 initial values**: `0x6a09e667 0xbb67ae85 0x3c6ef372 0xa54ff53a`
- **Round loop**: 64 iterations with `ror`/`shr`/`add` on 8 working variables

### SHA-1
- **H0**: `0x67452301`, **H1**: `0xefcdab89`, **H2**: `0x98badcfe`
- **K constants**: `0x5a827999`, `0x6ed9eba1`, `0x8f1bbcdc`, `0xca62c1d6`
- **Round loop**: 80 iterations

### MD5
- **Round 0 constant**: `0xd76aa478` (derived from `abs(sin(1)) * 2^32`)
- **radare2 search**: `/x 78a46ad7`
- **Init state**: `0x67452301 0xefcdab89 0x98badcfe 0x10325476`

### RC4
- **Key schedule**: tight loop `for i in 0..255: S[i] = i` — look for `mov [rcx+rax], al; inc rax; cmp rax, 0x100`
- **PRGA (keystream)**: two-index pattern `i++; j = (j + S[i]) & 0xFF; swap(S[i], S[j]); out ^= S[(S[i]+S[j])&0xFF]`
- **Key identification**: short byte array (4-256 bytes) used in key schedule

### Chacha20 / Salsa20
- **Magic constant**: `"expa"+"nd 3"+"2-by"+"te k"` = `0x61707865 0x3320646e 0x79622d32 0x6b206574`
- **radare2 search**: `/x 6578706133206465`

### CRC32
- **Polynomial**: `0xEDB88320` (reflected) or `0x04C11DB7` (normal)
- **Table**: 1024-byte lookup table near usage site

---

## Search Workflow

### Step 1 — Scan all readable sections for constants
```
# Search for AES S-box
/x 637c777bf26b6fc5

# Search for SHA-256 K[0]
/x 982f8a42

# Search for MD5 init
/x 01234567

# Search for Chacha20 magic
/x 65787061
```

### Step 2 — Check xrefs to confirm context
```
# Who references the constant's address?
axt @ <constant_addr>

# Inspect the referencing function
pdc @ <referencing_func>
```

### Step 3 — Identify init/update/final triad
Professional crypto implementations follow a three-function pattern:
- `_Init(ctx, key, iv)` — sets up state
- `_Update(ctx, plaintext, len)` — processes data block
- `_Final(ctx, ciphertext)` — produces output / cleans up

Look for all three. If only one function is found, check callers.

### Step 4 — Extract hardcoded key / IV
- Key often immediately precedes or follows the cipher context struct
- Look for: short byte array in `.rodata` near the constant table
- IV: 12-16 byte array; often `0x00` bytes or a static nonce pattern
- Check function parameters of `_Init`: second argument is commonly the key pointer

---

## Custom / Non-Standard Crypto Detection

### Indicators of Custom Crypto (Suspicious)
| Signal | What it Means |
|---|---|
| XOR loop over entire buffer with single-byte key | Simple XOR cipher — trivially breakable |
| Multiple `rol`/`ror` + `xor` on same value | Feistel-like structure or obfuscated cipher |
| Small lookup table (16-256 bytes) used in permutation loop | Substitution cipher (S-box) |
| No standard constants found but data is high-entropy | Custom block cipher or stream cipher |
| `imul eax, eax; xor eax, CONST` pattern | Linear congruential generator (PRNG, not crypto) |

### Analysis Approach for Custom Crypto
1. Find the encryption function: search for large loops that write to output buffer
2. Identify inputs: key argument, plaintext buffer, length
3. Trace the algorithm: use `pdc @func` to get pseudo-C; map to operations
4. Check for key schedule: fixed transforms on key before use → block cipher; direct key use → stream cipher
5. Test with known plaintext in Qiling emulator to observe output

---

## YARA Template for Crypto Constant Detection

```yara
rule CryptoAES {
    strings:
        $aes_sbox = { 63 7c 77 7b f2 6b 6f c5 }
        $aes_rcon = { 01 02 04 08 10 20 40 80 1b 36 }
    condition:
        ($aes_sbox or $aes_rcon) and filesize < 10MB
}

rule CryptoSHA256 {
    strings:
        $sha256_k0 = { 98 2f 8a 42 }  // 0x428a2f98 little-endian
        $sha256_h0 = { 67 e6 09 6a }  // 0x6a09e667 little-endian
    condition:
        2 of them
}

rule CryptoRC4_KSA {
    strings:
        // S[i]=i loop: mov [rcx+rax], al pattern near 256-count loop
        $rc4_init = { 88 04 01 48 FF C0 48 3D 00 01 00 00 }
    condition:
        $rc4_init
}
```

---

## Confidence Guidelines

| Evidence | Confidence |
|---|---|
| Multiple constants match + AES-NI instructions | high |
| Constants match + init/update/final triad identified | high |
| Single constant match + loop structure consistent | medium |
| Single constant match, no structural confirmation | low |
| No constants found, behavior-only inference | low |

---

## Region-Gated Ciphers and Keydat Patterns

Some game/DRM binaries implement **region-selective cryptography** — a cipher that uses a different
key or algorithm depending on a region or country code embedded in the binary or protocol data.

### Identifying a Region-Selector Pattern

| Signal | Description |
|---|---|
| String `keydat` in the binary | Direct indicator — keydat is the name of a region key file used by some Korean games |
| Array of 2-byte country codes near a switch/lookup table | `SE`, `TH`, `VN`, `KR`, `TW`, `MY`, `PH` (Southeast Asia region codes) |
| Comparison against 2-byte value before KSA initialization | RC4/XOR key selected based on country/region code |
| Multiple RC4 KSA patterns with different key pointers | Different keys per region |
| Array of struct `{country_code: u16, key_ptr: u32}` | Direct key table |

### Common Region Codes (Korean game context)

| Code | Region | Hex (ASCII) |
|------|--------|-------------|
| `VN` | Vietnam | `56 4E` |
| `TH` | Thailand | `54 48` |
| `KR` | Korea | `4B 52` |
| `TW` | Taiwan | `54 57` |
| `JP` | Japan | `4A 50` |
| `MY` | Malaysia | `4D 59` |
| `PH` | Philippines | `50 48` |
| `SG` | Singapore | `53 47` |

### radare2 Search for Region Codes
```
# Search for "VN" region tag
/x 564e

# Search for "TH" region tag
/x 5448

# Search for "KR" region tag
/x 4b52

# After finding a hit, check the function that uses it:
axt @<addr_of_hit>
pdfj @<referencing_function>
```

### Analysis Workflow
1. Search for known region codes using `/x` patterns
2. If found near a switch or comparison, disassemble the containing function
3. Trace the key selection logic: which key is used for which region code
4. Extract all keys and their corresponding region codes as separate findings
5. Note that the binary may behave differently depending on the game server's region flag

---

## Custom Base64 Alphabet Detection

Some binaries use a modified base64 alphabet for string obfuscation or encoding.

### Standard Base64 Alphabet
```
ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=
```

### Detection Method
1. In strings output, look for any 64-character string containing letters + digits + symbols
2. If the string differs from the standard alphabet but has a similar character class distribution, it is likely a custom alphabet
3. Use YARA to scan for the custom alphabet:
```yara
rule CustomBase64Alphabet {
    strings:
        // A 64-char string that could be a base64 alphabet (all printable, no spaces)
        $alphabet = /[A-Za-z0-9+\/=!\@\#\$\%\^\&\*\(\)\-\_]{64}/
    condition:
        $alphabet
}
```
4. Decode any base64-like strings found in the binary using the custom alphabet

