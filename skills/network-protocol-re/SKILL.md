---
name: network-protocol-re
description: >
  Network protocol reverse engineering: C2 traffic analysis, TLV/magic-byte identification,
  command parsing, Scapy-based dissection, Wireshark Lua dissector creation, and mitmproxy
  HTTPS interception. Use when analyzing network communications of malware or unknown protocols.
targets: [network_analyst, dynamic_analyst]
---

# Network Protocol Reverse Engineering Skill

## Triage Priority

1. Capture traffic (if not already captured)
2. Identify transport (TCP/UDP/ICMP/DNS)
3. Identify framing (TLV / length-prefixed / fixed-header / text-based)
4. Identify encoding (raw binary / Base64 / hex / custom)
5. Map to known protocol or define new structure
6. Write Scapy dissector or Wireshark Lua plugin

---

## Traffic Capture

### Wireshark / tshark (live or from PCAP)
```bash
# Capture on interface, filter by port:
tshark -i eth0 -f "tcp port 4444" -w capture.pcap

# Read existing capture:
tshark -r capture.pcap -Y "tcp" -T fields -e frame.number -e ip.dst -e tcp.port -e data.data
```

### Frida (in-process TLS interception — before encryption)
```javascript
// Hook SSL_write / SSL_read in libssl:
const SSL_write = Module.getExportByName('libssl.so', 'SSL_write');
Interceptor.attach(SSL_write, {
  onEnter(args) {
    const buf = args[1];
    const len = args[2].toInt32();
    console.log('[SSL_write] ' + buf.readByteArray(len).toString('hex'));
  }
});
```

### mitmproxy HTTPS intercept
```bash
# Start mitmproxy transparent proxy:
mitmproxy --mode transparent --showhost

# Route target traffic through proxy (on router/iptables):
iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 8080

# For mobile: install mitmproxy cert on device, set proxy to host:8080
# SSL pinning bypass needed (see Frida ObjC/Android SSL-kill-switch)
```

---

## Protocol Framing Identification

### Magic Bytes (Protocol Header)
```python
# Read first 16 bytes of first session packet
import struct
with open('session.bin', 'rb') as f:
    header = f.read(16)
print(header.hex())
# Look for:
# - Consistent bytes at offset 0-4 across sessions (magic)
# - 2-4 byte length field (try all offsets, validate against packet size)
# - Command/opcode field (byte array with small range of values)
```

### Length Prefix Detection
For each candidate length field offset L (0..8), field width W (1/2/4 bytes), and endianness:
```python
import struct
def try_length_field(data, offset, width, big_endian=True):
    fmt = '>' if big_endian else '<'
    fmt += {1:'B', 2:'H', 4:'I'}[width]
    claimed = struct.unpack_from(fmt, data, offset)[0]
    rest_len = len(data) - offset - width
    return abs(claimed - rest_len) < 4   # allow small slack
```

### TLV (Type-Length-Value)
Very common in custom protocols and C2 frameworks:
```
[TYPE: 1-2 bytes] [LENGTH: 2-4 bytes] [VALUE: LENGTH bytes]
[TYPE: 1-2 bytes] [LENGTH: 2-4 bytes] [VALUE: LENGTH bytes]
...
```
To verify TLV: parse first type+length, jump by length bytes, check next type is in expected range.

### Text-Based Protocols
- HTTP-like: headers separated by `\r\n`, body after `\r\n\r\n`
- JSON over TCP: look for `{` at start, complete JSON object
- Custom text protocol: line-oriented (`\n` delimited), first token is command

---

## C2 Beacon Pattern Recognition

### Common C2 Indicators

| Indicator | Pattern | Framework |
|---|---|---|
| Regular interval with jitter | Connections every 60±5s | Cobalt Strike / Metasploit |
| HTTP User-Agent anomaly | Fake browser UA but non-browser behavior | Almost all HTTP C2s |
| HTTP GET with base64 path | `/search?q=dGhpcyBpcyBhIHRlc3Q=` | Various |
| DNS TXT queries | Repeated TXT lookups for unusual domain | DNS C2 (DNScat2, Cobalt Strike DNS) |
| ICMP with payload | ICMP echo with non-zero data | ICMP tunneling |
| Large HTTP response to GET | First heartbeat returns config/payload | Beacon check-in |

### Timing Analysis
```python
import pandas as pd
df = pd.read_csv('connections.csv')   # tshark output with timestamps
df['time'] = pd.to_datetime(df['time'])
df['delta'] = df['time'].diff().dt.total_seconds()
print(df['delta'].describe())
# Regular mean + low std dev = periodic beacon
```

### Cobalt Strike Beacon Fingerprinting
- Default port: 80 or 443 (not exclusive)
- HTTP GET for check-in, HTTP POST for command results
- Malleable C2 profiles change headers/URIs
- JARM fingerprint: `07d14d16d21d21d07c42d41d00041d24a458a375eef0c576d23a7bab9a9fb` (default CS HTTPS)
- `ja3` fingerprint on TLS: JA3/JA3S identifies client/server SSL config

---

## Scapy Dissector

### Simple TLV Protocol
```python
from scapy.all import *

class MyProtoHeader(Packet):
    name = "MyProto"
    fields_desc = [
        XShortField("magic", 0xDEAD),
        ByteEnumField("type", 0, {
            0x01: "heartbeat",
            0x02: "command",
            0x03: "response",
        }),
        ShortField("length", None),
    ]
    def post_build(self, pkt, pay):
        if self.length is None:
            pkt = pkt[:3] + struct.pack("!H", len(pay)) + pkt[5:]
        return pkt + pay

class MyProtoBody(Packet):
    name = "MyProtoBody"
    fields_desc = [
        StrLenField("data", b"", length_from=lambda pkt: pkt.underlayer.length)
    ]

# Associate with port:
bind_layers(TCP, MyProtoHeader, dport=4444)
bind_layers(TCP, MyProtoHeader, sport=4444)

# Read PCAP and dissect:
pkts = rdpcap('capture.pcap')
for p in pkts:
    if MyProtoHeader in p:
        p[MyProtoHeader].show()
```

---

## Wireshark Lua Dissector

For sharing dissectors with the team or integrating with Wireshark GUI:

```lua
-- myproto_dissector.lua
local myproto = Proto("myproto", "My Custom Protocol")

local f_magic  = ProtoField.uint16("myproto.magic", "Magic", base.HEX)
local f_type   = ProtoField.uint8("myproto.type", "Type", base.HEX)
local f_length = ProtoField.uint16("myproto.length", "Length", base.DEC)
local f_data   = ProtoField.bytes("myproto.data", "Data")

myproto.fields = { f_magic, f_type, f_length, f_data }

function myproto.dissector(buffer, pinfo, tree)
    if buffer:len() < 5 then return end
    
    local magic = buffer(0,2):uint()
    if magic ~= 0xDEAD then return end
    
    pinfo.cols.protocol = "MYPROTO"
    local subtree = tree:add(myproto, buffer(), "MyProto Packet")
    
    subtree:add(f_magic,  buffer(0,2))
    subtree:add(f_type,   buffer(2,1))
    subtree:add(f_length, buffer(3,2))
    local dlen = buffer(3,2):uint()
    if buffer:len() >= 5 + dlen then
        subtree:add(f_data, buffer(5, dlen))
    end
end

-- Register for TCP port reassembly:
local tcp_port = DissectorTable.get("tcp.port")
tcp_port:add(4444, myproto)
```

Place in `~/.config/wireshark/plugins/` and restart Wireshark.

---

## SSL Pinning Bypass (Android)

When target app rejects mitmproxy cert (SSL pinning):

### Using Frida + ssl-kill-switch (Android)
```bash
# Download ssl-kill-switch2 for Android:
# https://github.com/nabla-c0d3/ssl-kill-switch2

frida -U -f com.example.app --no-pause -l ssl-kill-switch2.js
```

### Universal Frida bypass (OkHttp + conscrypt)
```javascript
Java.perform(function() {
  // Bypass OkHttp CertificatePinner
  var CertificatePinner = Java.use('okhttp3.CertificatePinner');
  CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function() {
    console.log('[+] OkHttp CertificatePinner bypassed');
  };
  
  // Bypass TrustManager
  var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
  // ... implement stub trust manager
});
```

---

## Protocol Documentation Template

When a new protocol is fully analyzed, document as:

```markdown
## Protocol: [NAME] (port [PORT]/[TCP|UDP])

### Header (N bytes)
| Offset | Size | Field | Description |
|---|---|---|---|
| 0 | 2 | Magic | 0x[XX XX] — protocol identifier |
| 2 | 1 | Type | Command type (see below) |
| 3 | 4 | Length | Payload length (big-endian) |

### Command Types
| Value | Name | Direction | Description |
...

### Encryption / Encoding
[None / XOR key=VALUE / AES-256-CBC with key at offset X]

### Session Flow
[Initial handshake → beacon → command → result → keepalive diagram]
```
