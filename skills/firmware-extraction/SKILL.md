---
name: firmware-extraction
description: >
  Firmware image extraction, filesystem identification, encrypted firmware detection, and
  post-extraction analysis. Covers binwalk, squashfs/JFFS2/UBI/cramfs, U-Boot headers,
  kernel extraction, and post-extraction security checks. Use for IoT/embedded firmware RE.
targets: [firmware_analyst, static_analyst]
---

# Firmware Extraction Skill

## Quick Start: binwalk Full Extraction

```bash
# Initial analysis (no extraction)
binwalk firmware.bin

# Recursive extraction to directory
binwalk -eM --run-as=root -C fw_extracted/ firmware.bin
# -e  = extract known file types
# -M  = recursive (matryoshka) — recurse into extracted archives
# -C  = output directory

# With verbose output + entropy analysis
binwalk -eM -v --entropy firmware.bin
```

---

## Encrypted Firmware Detection

### Entropy Analysis
High-entropy regions (entropy > 0.95 across entire image) indicate encryption or compression:

```bash
binwalk --entropy firmware.bin
# Plot: flat line near 1.0 = encrypted (compressed shows varying entropy)
# Normal firmware: low-entropy header, high-entropy compressed payload, clear filesystem
```

### Distinguishing Encrypted vs Compressed
- **Compressed (zlib/lzma/lz4)**: binwalk finds `LZMA compressed data` or `zlib` signatures at known offsets
- **Encrypted**: No file signatures found; entropy is uniformly ~0.99; binwalk shows nothing
- **Test**: Try `strings firmware.bin | head -30` — if no readable strings, likely encrypted

### Encrypted Firmware Approaches
1. **Find decryption key in older firmware version** (manufacturers often ship update script with key)
2. **UART/JTAG extraction** from running device — bypass encryption by dumping post-decryption flash
3. **Find decryption routine** in bootloader (U-Boot) via UART console or emulated U-Boot analysis
4. **Check companion app** (Android/iOS) for embedded firmware decrypt key (Base64 or hex constant)
5. **Vendor FTP/GitHub** — some vendors leak keys or old unencrypted versions

---

## Filesystem Type Identification

```bash
# After binwalk extracts, look for filesystem magic:
file fw_extracted/_firmware.bin.extracted/*

# Manual check of common filesystem offsets:
xxd firmware.bin | head -20
```

### Magic Signatures

| Filesystem | Magic Bytes (hex) | Notes |
|---|---|---|
| squashfs | `68 73 71 73` / `73 71 73 68` (SQSH/sqsh) | Most common in Linux-based IoT |
| JFFS2 | `85 19 03 20` | MTD flash (NAND) |
| UBIFS | `31 18 10 06` | MTD flash (NAND) |
| cramfs | `45 3D CD 28` | Older embedded Linux |
| ext2/3/4 | `53 EF` at offset 0x438 | Less common in IoT |
| yaffs2 | No single magic; NAND-specific | Often mixed with JFFS2 partitions |

---

## squashfs Extraction

```bash
# Most binwalk versions extract squashfs automatically.
# Manual if needed:
unsquashfs -d squashfs-root/ filesystem.squashfs

# For non-standard compression (LZMA/LZ4/XZ/ZSTD):
# Some vendors use custom squashfs compressors not in distro package
# Build sasquatch (supports more compression types):
# git clone https://github.com/devttys0/sasquatch && cd sasquatch && ./build.sh
unsquashfs-lzma -d squashfs-root/ filesystem.squashfs
```

---

## JFFS2 and UBI Extraction

### JFFS2
```bash
# Mount JFFS2 image (requires Linux with mtdram):
modprobe mtdram total_size=16384 erase_size=256
modprobe mtdblock
dd if=jffs2.img of=/dev/mtdblock0
mount -t jffs2 /dev/mtdblock0 /mnt/jffs2/

# Alternative: jefferson tool (no kernel module needed)
jefferson jffs2.img -d jffs2_extracted/
```

### UBI / UBIFS
```bash
# Unpack UBI image:
ubireader_extract_images firmware_ubi.bin
ubireader_extract_files firmware_ubi.bin -o ubi_extracted/

# If volume is UBIFS:
# ubireader handles it automatically; mount option:
ubiattach -m 0 -d 2
mount -t ubifs ubi2:rootfs /mnt/ubifs/
```

---

## U-Boot Header Identification

U-Boot images have a specific magic header:

```bash
# Magic at offset 0: 27 05 19 56 (0x27051956)
xxd firmware.bin | head -4
# Output: 27051956 ...

# Parse U-Boot header fields:
mkimage -l uboot_image.bin
# Shows: Image Type, Compression, Load Address, Entry Point, OS/Arch
```

### U-Boot Compression Types
Most U-Boot kernels wrap a compressed payload:
```
0x27051956  [header 64 bytes]  → compressed kernel (gzip/lzma/lz4)
```
```bash
# Skip 64-byte header, extract compressed kernel:
dd if=uboot_image.bin of=kernel_compressed.bin bs=1 skip=64
file kernel_compressed.bin   # identifies compression
zcat kernel_compressed.bin > kernel.elf  # for gzip
```

---

## vmlinux / Kernel Extraction

Compressed kernel images contain an embedded `vmlinux` ELF:

```bash
# Tool: extract-vmlinux from kernel scripts
extract-vmlinux bzImage > vmlinux.elf
file vmlinux.elf   # should be ELF 64-bit ARM/x86

# Alternative: vmlinux-to-elf
pip install vmlinux-to-elf
vmlinux-to-elf vmlinuz vmlinux.elf

# Analyze extracted ELF:
strings vmlinux.elf | grep -E "module_name|kernel version"
readelf -S vmlinux.elf
```

---

## Post-Extraction Analysis Checklist

After successfully extracting the root filesystem:

### 1. Find SUID/SGID executables
```bash
find squashfs-root/ -perm /6000 -type f 2>/dev/null
# Any SUID binary = potential privilege escalation vector
```

### 2. Find hardcoded credentials
```bash
# Default passwords in passwd/shadow:
cat squashfs-root/etc/passwd
cat squashfs-root/etc/shadow

# HTTP admin credentials:
find squashfs-root/ -name "*.conf" -o -name "*.cfg" -o -name "*.ini" | xargs grep -i "password\|passwd\|secret\|key" 2>/dev/null

# Hardcoded in binaries:
find squashfs-root/bin squashfs-root/usr/bin squashfs-root/sbin -type f | xargs strings 2>/dev/null | grep -E "admin|password|root|secret" | sort -u
```

### 3. Find private keys / certificates
```bash
find squashfs-root/ -name "*.pem" -o -name "*.key" -o -name "*.crt" -o -name "*.p12" 2>/dev/null
grep -r "BEGIN.*PRIVATE KEY\|BEGIN CERTIFICATE" squashfs-root/ 2>/dev/null
```

### 4. Identify network services
```bash
# init scripts showing started services:
find squashfs-root/etc/init* -name "*.sh" | xargs grep -l "listen\|bind\|daemon" 2>/dev/null
find squashfs-root/ -name "inetd.conf" | xargs cat 2>/dev/null

# Check for busybox apps serving network services:
strings squashfs-root/bin/busybox | grep -E "httpd|telnetd|ftpd|tftpd|sshd"
```

### 5. Identify vulnerable versions
```bash
# Version strings in binaries:
strings squashfs-root/usr/lib/libssl.so* | grep "OpenSSL"
strings squashfs-root/usr/lib/libc.so* | grep "GNU C Library"
find squashfs-root/ -name "*.so*" | xargs strings 2>/dev/null | grep -E "version [0-9]"
```

### 6. Check update mechanism
```bash
find squashfs-root/ -name "*update*" -o -name "*ota*" | xargs file 2>/dev/null
# Look for: wget/curl URL patterns, RSA public key for verification
# If no signature check: firmware update = unauthenticated code execution
```

---

## Common Vendor Patterns

| Vendor | Filesystem | Extraction Notes |
|---|---|---|
| TP-Link | squashfs | Standard binwalk; sometimes custom squashfs LZMA |
| Netgear | squashfs / cramfs | `binwalk -eM` usually sufficient |
| D-Link | squashfs | Sometimes uses `shoehorn` obfuscation: add magic bytes |
| Asus | squashfs | Standard binwalk handles Wi-Fi router firmware |
| Huawei | Mixed / encrypted | NAND dump often needed; newer firmware encrypted |
| Mikrotik | Custom `routeros.img` | Proprietary; yealink dissectors exist |
| Hikvision | cramfs + gzip | binwalk extracts correctly |
| Ubiquiti | squashfs | Standard binwalk |
