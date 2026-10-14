"""Isolated LOCAL simulation of model activation and rollback.

Never changes model_release_1.py's active.json / previous.json, model files,
approval records, or any Raspberry Pi device. Simulation state is separate.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from model_release_1 import get_checked, store


def save(path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", default="model_registry_test")
    p.add_argument("--state-dir", default="simulation_deploy_state")
    sub = p.add_subparsers(dest="command", required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("--version", required=True)
    sub.add_parser("rollback")
    sub.add_parser("status")
    args = p.parse_args()
    try:
        registry = store(args.registry)
        state = Path(args.state_dir).resolve()
        if state == registry or state.is_relative_to(registry) or registry.is_relative_to(state):
            raise ValueError("Simulation state must be separate from model registry")
        state.mkdir(parents=True, exist_ok=True)
        active_file = state / "active.json"
        previous_file = state / "previous.json"
        current = load(active_file)["version"] if active_file.exists() else None
        previous = load(previous_file)["version"] if previous_file.exists() else None

        if args.command == "activate":
            _, record = get_checked(registry, args.version)
            if not record.get("synthetic_test_only"):
                raise ValueError("Simulator accepts synthetic_test_only versions only")
            if current:
                get_checked(registry, current)
            if current == args.version:
                raise ValueError("Version already active in simulation")
            save(previous_file, {"version": current})
            save(active_file, {"version": args.version,
                               "simulated_at_utc": datetime.now(timezone.utc).isoformat()})
            print(f"SIMULATION ONLY: active={args.version}, previous={current}")
        elif args.command == "rollback":
            if not current or not previous:
                raise ValueError("No previous simulation version to restore")
            _, record = get_checked(registry, previous)
            if not record.get("synthetic_test_only"):
                raise ValueError("Previous version is not a synthetic test version")
            get_checked(registry, current)
            save(active_file, {"version": previous, "rollback_from": current,
                               "simulated_at_utc": datetime.now(timezone.utc).isoformat()})
            save(previous_file, {"version": current})
            print(f"SIMULATION ONLY: rollback {current} -> {previous}")
        else:
            if current:
                get_checked(registry, current)
            if previous:
                get_checked(registry, previous)
            print(json.dumps({"simulation_only": True, "active": current,
                              "previous": previous}, indent=2))
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        p.exit(1, f"Simulation stopped safely: {exc}\n")


if __name__ == "__main__":
    main()
