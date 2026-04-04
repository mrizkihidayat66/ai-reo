---
name: firmware-analysis
description: >
  Workflow for analyzing embedded firmware images and IoT binaries — extraction, credential
  hunting, architecture identification, and string analysis. Use when the user uploads a
  firmware image (.bin, .img, .trx) or an IoT/embedded binary.
targets: [static_analyst, dynamic_analyst]
---

# Firmware Analysis Skill

This skill provides guidance for analyzing embedded firmware images and IoT binaries.

## Recommended Tool Order

1. **Initial Triage**
   - `file_type` + `binary_info` — detect compression or archive wrapping.
   - `binwalk` (no extract) — identify embedded file signatures, compression boundaries, entropy profile.

2. **Extraction**
   - `binwalk extract=true` — attempt recursive extraction of embedded filesystems.
   - Common firmware structures: SquashFS, JFFS2, CRAMFS, ext2/4, YAFFS2, gzip/lzma streams.

3. **String Analysis**
   - `strings_extract` or `floss` — search for:
     - Hardcoded credentials (passwords, API keys, private keys)
     - Debug backdoor strings ("admin", "password", "debug", "shell")
     - URL patterns for update servers or C2
     - Build paths revealing OS/SDK version

4. **Binary Identification**
   - `die` — detect OS/compiler/SDK (e.g., uClibc, Busybox).
   - For ELF binaries inside the firmware: use `readelf`, `nm`, `radare2`.

## Common Firmware Findings

| Finding | Where to Look |
|---|---|
| Hardcoded credentials | `/etc/passwd`, `/etc/shadow`, init scripts, web server configs |
| Telnet/SSH backdoors | Init scripts for persistent listeners; setuid binaries |
| Weak crypto | Hardcoded AES/DES keys in `.data` section, static IV patterns |
| Update mechanism | Executable scripts calling `wget`/`curl` with hardcoded endpoints |
| Debug interfaces | UART console init, JTAG pin configurations |

## Architecture Notes

- Most IoT firmware is MIPS, ARM, or RISC-V 32-bit little-endian.
- Radare2 auto-detects architecture; confirm with `binary_info` or `file_type` first.
- uClibc and Busybox binaries are heavily stripped; symbol recovery via strings is more reliable than nm.

## Encrypted Firmware Handling

When `binwalk --entropy` shows uniform high entropy (≥ 0.95 across entire image):
1. Check older firmware versions from vendor — encryption may be absent or key embedded in companion app
2. Use UART/JTAG extraction on a physical device to dump post-decryption memory
3. Analyze the bootloader (U-Boot) to find decryption routine and key material
4. Search Android/iOS companion app APK/IPA for device firmware key constants

See `firmware-extraction` skill for full filesystem type identification (squashfs/JFFS2/UBI/cramfs), U-Boot header parsing, vmlinux extraction, and post-extraction credential checklist.

## Post-Extraction Security Checklist

After successful extraction (see `firmware-extraction` skill):

```bash
# SUID binaries (privilege escalation):
find rootfs/ -perm /6000 -type f 2>/dev/null

# Private keys / certs:
find rootfs/ -name "*.pem" -o -name "*.key" | xargs grep "PRIVATE KEY"

# Hardcoded passwords:
grep -r "password\|passwd\|secret" rootfs/etc/ rootfs/www/ --include="*.conf" --include="*.cfg"

# Unauthenticated update mechanism:
grep -r "wget\|curl" rootfs/etc/init* rootfs/usr/share/scripts/ 2>/dev/null | grep -v "https"
```

## Emulation with QEMU

For dynamic analysis without physical hardware:
```bash
# MIPS little-endian system emulation:
qemu-mips -L squashfs-root/ squashfs-root/usr/sbin/httpd

# ARM full-system emulation:
qemu-system-arm -M virt -kernel vmlinux -append "root=/dev/sda console=ttyAMA0" -hda rootfs.img

# Use firmwalker for automated credential hunting in extracted FS:
firmwalker squashfs-root/ firmwalker_output.txt
```
