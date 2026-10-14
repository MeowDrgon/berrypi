"""Local model release registry and SAFE simulated activation/rollback.

Only operate on locally created trusted joblib files. Never load untrusted joblib.
This tool does NOT push models to Raspberry Pi, restart inference, or touch live models.
"""
import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, value):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def store(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "versions").mkdir(exist_ok=True)
    return root


def version_path(root, version):
    if not version or not all(c.isascii() and (c.isalnum() or c in "-_.") for c in version):
        raise ValueError("Version must contain only letters, digits, hyphens or underscores")
    return root / "versions" / version


def register(args, root):
    candidate, report = Path(args.candidate).resolve(), Path(args.report).resolve()
    if not candidate.is_file() or not report.is_file():
        raise ValueError("Candidate model and validation report must exist")
    meta = read_json(report)
    if not meta.get("passed_initial_gate") or not meta.get("candidate_only"):
        raise ValueError("Report is not an eligible candidate report")
    if meta.get("validation_source") != "human_review_only":
        raise ValueError("Validation must use human-reviewed holdout")
    if meta.get("approved_for_deployment") is not False:
        raise ValueError("Report approval flag is not false")
    if candidate.stem.removeprefix("candidate_") != report.stem.removeprefix("validation_"):
        raise ValueError("Candidate and report timestamps do not match")
    path = version_path(root, args.version)
    if path.exists():
        raise ValueError("Version already registered")
    path.mkdir()
    try:
        shutil.copy2(candidate, path / "model.joblib")
        shutil.copy2(report, path / "validation.json")
        record = {
            "version": args.version, "status": "candidate",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approved_by": None, "approved_at_utc": None,
            "synthetic_test_only": bool(args.synthetic),
            "model_sha256": sha256(path / "model.joblib"),
            "report_sha256": sha256(path / "validation.json"),
            "training_created_at_utc": meta.get("created_at_utc"),
            "accuracy": meta.get("accuracy"),
            "fatigue_precision": meta.get("per_class", {}).get("1", {}).get("precision"),
            "fatigue_recall": meta.get("per_class", {}).get("1", {}).get("recall"),
        }
        save_json(path / "metadata.json", record)
    except Exception:
        shutil.rmtree(path)
        raise
    print(f"Registered candidate: {args.version}")


def get_checked(root, version):
    path = version_path(root, version)
    record = read_json(path / "metadata.json")
    if record.get("version") != version:
        raise ValueError("Metadata version mismatch")
    if sha256(path / "model.joblib") != record["model_sha256"]:
        raise ValueError("Model SHA256 mismatch")
    if sha256(path / "validation.json") != record["report_sha256"]:
        raise ValueError("Validation report SHA256 mismatch")
    return path, record


def approve(args, root):
    path, record = get_checked(root, args.version)
    if record["synthetic_test_only"]:
        raise ValueError("Synthetic model cannot be approved for deployment")
    if record["status"] not in ("candidate", "approved"):
        raise ValueError("Version is not eligible for approval")
    if not args.reviewer.strip():
        raise ValueError("Reviewer name required")
    record["status"] = "approved"
    record["approved_by"] = args.reviewer.strip()
    record["approved_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(path / "metadata.json", record)
    print(f"Approved: {args.version} by {record['approved_by']}")


def activate(args, root):
    path, record = get_checked(root, args.version)
    if record["status"] != "approved" or not record["approved_by"]:
        raise ValueError("Only manually approved versions can be activated")
    if record["synthetic_test_only"]:
        raise ValueError("Synthetic model cannot be activated")
    active_file = root / "active.json"
    old = read_json(active_file)["version"] if active_file.exists() else None
    if old:
        get_checked(root, old)
    save_json(root / "previous.json", {"version": old})
    save_json(active_file, {"version": args.version,
                            "activated_at_utc": datetime.now(timezone.utc).isoformat()})
    print(f"SIMULATED activation: {args.version}; previous: {old}")


def rollback(args, root):
    previous_file, active_file = root / "previous.json", root / "active.json"
    if not previous_file.exists() or not active_file.exists():
        raise ValueError("No rollback history")
    previous = read_json(previous_file)["version"]
    current = read_json(active_file)["version"]
    if not previous:
        raise ValueError("No previous active version")
    _, record = get_checked(root, previous)
    if record["status"] != "approved" or record["synthetic_test_only"]:
        raise ValueError("Previous version is not approved")
    get_checked(root, current)
    save_json(active_file, {"version": previous,
                            "activated_at_utc": datetime.now(timezone.utc).isoformat(),
                            "rollback_from": current})
    save_json(previous_file, {"version": current})
    print(f"SIMULATED rollback: {current} -> {previous}")


def status(args, root):
    result = {"active": None, "previous": None, "versions": []}
    for key in ("active", "previous"):
        p = root / (key + ".json")
        if p.exists():
            result[key] = read_json(p).get("version")
    for p in sorted((root / "versions").iterdir()):
        if p.is_dir() and (p / "metadata.json").exists():
            _, record = get_checked(root, p.name)
            result["versions"].append(record)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="model_registry_test")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("register")
    p.add_argument("--candidate", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--synthetic", action="store_true",
                   help="Mandatory for synthetic-data candidates; blocks approval and activation")
    p = commands.add_parser("approve")
    p.add_argument("--version", required=True)
    p.add_argument("--reviewer", required=True)
    p = commands.add_parser("activate")
    p.add_argument("--version", required=True)
    commands.add_parser("rollback")
    commands.add_parser("status")
    args = parser.parse_args()
    try:
        globals()[args.command](args, store(args.registry))
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Stopped safely: {exc}\n")


if __name__ == "__main__":
    main()
