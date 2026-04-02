#!/usr/bin/env python3
"""LIEF-based binary parser — invoked by LiefTool inside the Docker container.

Usage:
    python3 /app/lief_parse.py [--sections-only] <binary_path>
"""
import json
import sys

try:
    import lief
except ImportError:
    print(json.dumps({"error": "lief not installed in this image"}))
    sys.exit(1)


def _section_info(s) -> dict:
    return {
        "name": s.name,
        "size": s.size,
        "virtual_address": hex(s.virtual_address),
        "characteristics": hex(int(getattr(s, "characteristics", 0))),
    }


def _format_name(binary) -> str:
    if isinstance(binary, lief.PE.Binary):
        return "PE"
    if isinstance(binary, lief.ELF.Binary):
        return "ELF"
    if isinstance(binary, lief.MachO.Binary):
        return "MACHO"
    return type(binary).__name__


def parse(binary_path: str, sections_only: bool = False) -> dict:
    binary = lief.parse(binary_path)
    if binary is None:
        return {"error": f"LIEF could not parse '{binary_path}'"}

    result = {"path": binary_path, "format": _format_name(binary)}
    result["sections"] = [_section_info(s) for s in binary.sections]

    if sections_only:
        return result

    # Imports (PE and ELF share this attribute)
    try:
        if hasattr(binary, "imports") and binary.imports:
            result["imports"] = [
                {"library": imp.name, "functions": [e.name for e in imp.entries]}
                for imp in binary.imports
            ]
    except Exception:
        pass

    # Exports — try lief 0.14+ API first, then fall back to older API
    try:
        if hasattr(binary, "get_export"):
            exp = binary.get_export()
            if exp is not None:
                result["exports"] = [e.name for e in exp.entries if e.name]
        elif hasattr(binary, "exported_functions"):
            result["exports"] = [f.name for f in binary.exported_functions]
    except Exception:
        pass

    # PE-specific fields
    try:
        if isinstance(binary, lief.PE.Binary):
            hdr = binary.header
            opt = binary.optional_header
            result["pe"] = {
                "machine": str(hdr.machine).split(".")[-1],
                "entry_point": hex(opt.addressof_entrypoint),
                "image_base": hex(opt.imagebase),
                "timestamp": hdr.time_date_stamps,
                "subsystem": str(opt.subsystem).split(".")[-1],
                "dll": binary.is_dll,
            }
            if binary.has_tls:
                result["tls_callbacks"] = [hex(c) for c in binary.tls.callbacks]
            if binary.has_signatures:
                result["signed"] = True
                result["signature_count"] = len(binary.signatures)
    except Exception:
        pass

    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    sections_only = "--sections-only" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print(json.dumps({"error": "No binary path provided"}))
        sys.exit(1)
    print(json.dumps(parse(args[0], sections_only=sections_only), default=str))
