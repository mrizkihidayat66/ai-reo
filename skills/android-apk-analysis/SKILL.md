---
name: android-apk-analysis
description: >
  Android APK reverse engineering workflow: identification, decompilation, manifest audit,
  native library analysis, malware indicator detection, and crypto/network extraction.
  Use for all Android APK analysis tasks.
targets: [mobile_analyst]
---

# Android APK Analysis Skill

## Analysis Order (Always Follow This Sequence)

1. **APKiD** — packer/protector/compiler fingerprinting
2. **Manifest audit** — permissions, exported components, backup flag
3. **Apktool** — smali decompile for code-level analysis
4. **JADX** — Java decompile for readable code review
5. **Native libraries** — .so files from lib/
6. **Secrets extraction** — hardcoded keys, credentials, URLs
7. **Dynamic analysis** — Frida hooks, network traffic

---

## Step 1 — APKiD Fingerprinting

Always run APKiD first to understand what you're dealing with.

```bash
apkid target.apk
```

### APKiD Output Interpretation

| Result | Meaning |
|---|---|
| `[COMPILER] dx` | Standard Android DEX compiler |
| `[COMPILER] dexlib 2.x` | ApkTool or custom compiled |
| `[PACKER] Bangcle` | Chinese packer — DEX encrypted; need dynamic unpack |
| `[PACKER] Qihoo 360` | Chinese packer — encrypted native loader |
| `[PACKER] DexGuard` | Commercial protector |
| `[PROTECTOR] DashO` | Obfuscated but not packed |
| `[ANTI_VM] emulator check` | Contains VM/emulator detection |
| `[ANTI_DISASSEMBLY] ...` | Uses disassembly-confusing techniques |

If packer detected → use dynamic unpack before smali analysis.

---

## Step 2 — Manifest Audit

```bash
# Extract and decode manifest:
apktool d target.apk -o unpacked/
cat unpacked/AndroidManifest.xml
```

### Critical Flags to Check

| Flag | What it Means | Risk |
|---|---|---|
| `android:debuggable="true"` | Allows ADB debugging on all devices | HIGH — enables Frida attachment, memory dumps |
| `android:allowBackup="true"` | App data can be extracted via ADB backup | MED — data exposure |
| `android:exported="true"` on Activity/Service/Receiver | Component accessible from other apps | HIGH if no permission check |
| `android:sharedUserId` | Shared UID with other apps (old pattern) | Trust boundary risk |
| `WRITE_EXTERNAL_STORAGE` | Can write to SD card | Data leakage risk |
| `READ_CONTACTS` | Accesses contacts | Privacy risk |
| `RECEIVE_BOOT_COMPLETED` | Starts at boot | Persistence |

### Verify Exported Components
```bash
grep -E 'exported="true"' unpacked/AndroidManifest.xml
# Check each exported component for missing permission check
```

---

## Step 3 — Apktool Smali Analysis

Smali is Dalvik bytecode disassembly. More reliable than JADX for obfuscated code.

```bash
apktool d target.apk -o unpacked/ --no-res   # --no-res skips resource decoding (faster)
```

### DexClassLoader Pattern (dynamic code loading)
```smali
# Look for DexClassLoader constructor:
invoke-direct {v0, v1, v2, v3, v4}, Ldalvik/system/DexClassLoader;-><init>(
    Ljava/lang/String;   # dex path (often /sdcard/ or cache)
    Ljava/lang/String;   # optimized dir
    Ljava/lang/String;   # library path
    Ljava/lang/ClassLoader;)-><V>

# Also: PathClassLoader, InMemoryDexClassLoader (API 26+)
```

### Reflection-Based API Calls
```smali
# Strings loaded then called via reflection:
const-string v1, "loadLibrary"
invoke-virtual {v0, v1}, Ljava/lang/Class;->getMethod(Ljava/lang/String;...)
invoke-virtual {v0, v1, v2}, Ljava/lang/reflect/Method;->invoke(...)
```

### JNI Native Method Registration
```smali
# Native method: declared in smali as:
.method public native sensitiveMethod()Ljava/lang/String;
.end method

# grep for them:
grep -r "native " unpacked/smali/ | grep ".method"
```

---

## Step 4 — JADX Java Decompilation

```bash
jadx -d jadx_out/ target.apk
# or GUI:
jadx-gui target.apk
```

### Useful JADX Flags
```bash
jadx -d out/ --no-res --show-bad-code --deobf target.apk
# --deobf: renames single-char obfuscated identifiers
# --show-bad-code: shows failed decompilation as commented bytecode
```

### Focus Areas in JADX Output

#### Network configuration / C2 URLs
```java
// Search for:
// - String constants with http/https
// - URL() / HttpURLConnection / OkHttpClient init
grep -r "http" jadx_out/sources/ | grep -v "//.*http"
grep -r "\".*\.onion\"" jadx_out/sources/
```

#### Crypto usage
```java
// Look for:
// - SecretKeySpec / Cipher.getInstance / MessageDigest
// - Base64 decoding + cipher combo = likely encrypted config
grep -r "Cipher\|SecretKey\|KeySpec\|AES\|DES\|RC4" jadx_out/sources/
```

#### SharedPreferences / SQLite for stored data
```java
getSharedPreferences("credentials", MODE_PRIVATE)
openOrCreateDatabase("userdata.db", ...)
```

---

## Step 5 — Native Library Analysis

```bash
find unpacked/lib/ -name "*.so"
# Common: lib/arm64-v8a/libnative.so, lib/armeabi-v7a/libnative.so

# Analyze with standard RE tools:
file lib/arm64-v8a/*.so
readelf -a lib/arm64-v8a/libnative.so
strings lib/arm64-v8a/libnative.so | grep -E "http|/proc|ptrace"

# In radare2:
r2 lib/arm64-v8a/libnative.so
> aaa; afl    # analyze + list functions
> /iz          # search strings in data sections
```

### JNI_OnLoad — entry point for native library
```c
// JNI_OnLoad is called when System.loadLibrary() loads the .so
// Search for it:
nm lib/arm64-v8a/libnative.so | grep JNI_OnLoad
```

---

## Step 6 — Secrets Extraction

### Hardcoded strings
```bash
# In smali:
grep -r "const-string" unpacked/smali/ | grep -E "key|secret|password|token|api"

# In assets/resources:
find unpacked/ -name "*.json" -o -name "*.xml" -o -name "*.properties" | xargs grep -l "key\|secret\|password"

# In native .so strings:
strings lib/arm64-v8a/*.so | grep -E "([A-Za-z0-9+/]{32,}=?)" # Base64 blobs
strings lib/arm64-v8a/*.so | grep -E "[A-Z0-9]{20,}" # AWS key pattern
```

### Firebase / Cloud config
```bash
cat unpacked/res/raw/google-services.json  # Firebase project config
cat unpacked/assets/google-services.json
# Contains: project_id, api_key, app_id
```

---

## Step 7 — Frida Dynamic Analysis

```bash
# Attach to running app (device must have frida-server):
frida -U -n com.example.app -l hook_script.js

# Spawn fresh:
frida -U -f com.example.app --no-pause -l hook_script.js
```

### Hook Crypto (AES decrypt calls)
```javascript
Java.perform(function() {
  var Cipher = Java.use('javax.crypto.Cipher');
  Cipher.doFinal.overload('[B').implementation = function(data) {
    var result = this.doFinal(data);
    console.log('[Cipher.doFinal] algorithm=' + this.getAlgorithm() +
                ' input=' + bytesToHex(data) +
                ' result=' + Java.array('byte', result));
    return result;
  };
});
```

### Hook Network
```javascript
Java.perform(function() {
  var URL = Java.use('java.net.URL');
  URL.$init.overload('java.lang.String').implementation = function(url) {
    console.log('[URL] ' + url);
    return this.$init(url);
  };
});
```

---

## Malware Indicators Checklist

- [ ] `DexClassLoader` loading from external storage → dropper
- [ ] SMS reading + sending (`SmsManager.sendTextMessage`) → SMS stealer / premium dialer
- [ ] `BIND_DEVICE_ADMIN` permission → ransomware / stalkerware
- [ ] `SYSTEM_ALERT_WINDOW` + overlay drawing → phishing overlay
- [ ] `READ_CALL_LOG` + `READ_CONTACTS` + network → spyware
- [ ] Encrypted assets decoded at runtime → packed malware
- [ ] Hardcoded IP:port (non-standard ports) → C2 communication
- [ ] `android:debuggable="false"` but APKiD shows debuggable dex → repackaged legit app
- [ ] Certificate mismatch vs Play Store equivalent → trojanized version
