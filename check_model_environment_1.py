"""Collect Python/runtime versions without installing packages or loading models.
Run on Windows training host and Raspberry Pi using their intended Python interpreter.
"""
import argparse
import importlib.metadata as metadata
import json
import os
import platform
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

PACKAGES = ("numpy", "scipy", "pandas", "scikit-learn", "joblib", "threadpoolctl")


def collect():
    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "architecture_bits": struct.calcsize("P") * 8,
        "byteorder": sys.byteorder,
        "venv_active": sys.prefix != sys.base_prefix,
        "packages": packages,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", help="Write report to JSON file")
    p.add_argument("--compare", help="Compare with another environment report JSON")
    args = p.parse_args()
    info = collect()
    if args.out:
        out = Path(args.out)
        if out.exists():
            p.error("Refusing to overwrite existing report")
        out.write_text(json.dumps(info, indent=2), encoding="utf-8")
    if args.compare:
        other = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        differences = {}
        for key in ("python_version", "python_implementation"):
            if info[key] != other.get(key):
                differences[key] = {"local": info[key], "other": other.get(key)}
        for package in PACKAGES:
            if info["packages"][package] != other.get("packages", {}).get(package):
                differences[package] = {
                    "local": info["packages"][package],
                    "other": other.get("packages", {}).get(package)
                }
        info["comparison"] = {
            "runtime_versions_match": not bool(differences),
            "differences": differences,
            "note": "A match does not prove Pi load/inference compatibility. "
                    "OS/CPU architectures can differ; test on Pi separately."
        }
    print(json.dumps(info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
