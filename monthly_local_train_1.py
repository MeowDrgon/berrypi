"""Manual monthly LOCAL candidate training; never deploys or changes fatigue.db.
Run: py -m pip install pandas scikit-learn joblib
     py monthly_local_train_1.py --db fatigue.db
Use a copy of the production database on the offline training machine.
"""
import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import GroupShuffleSplit

FEATURES = ["ear", "mar", "blink", "blink_rate_10s", "nod_ratio"]
# OTHER-only raw measurements: retained in storage, excluded from fatigue training.
OTHER_FEATURES = ["head_ratio", "head_motion"]
MIN_TRAIN_PER_CLASS = 20
MIN_VALID_PER_CLASS = 10
MIN_RECALL = 0.80
MIN_PRECISION = 0.80


def run(db_path, output_dir):
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise RuntimeError(f"Database not found: {db_path}")
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(fatigue_data)")}
        needed = set(FEATURES + ["user_id", "time", "label", "label_source"])
        if not needed.issubset(cols):
            raise RuntimeError(f"Missing fatigue_data columns: {sorted(needed - cols)}")
        data = pd.read_sql_query(
            "SELECT " + ", ".join(sorted(needed)) + " FROM fatigue_data "
            "WHERE label IN (0,1) AND label_source IN ('human_review','auto_expired')", conn
        )
    for name in FEATURES:
        data[name] = pd.to_numeric(data[name], errors="coerce")
    data = data.dropna(subset=FEATURES + ["user_id", "time", "label"])
    data = data[np.isfinite(data[FEATURES]).all(axis=1)].copy()
    data["label"] = data["label"].astype(int)
    # Group adjacent records by driver and day to avoid random per-second leakage.
    dates = pd.to_datetime(data["time"], errors="coerce")
    data = data.loc[dates.notna()].copy()
    dates = dates.loc[data.index]
    data["group"] = data["user_id"].astype(str) + "|" + dates.dt.strftime("%Y-%m-%d")
    human = data[data["label_source"] == "human_review"].copy()
    if human["group"].nunique() < 3:
        raise RuntimeError("Need human-reviewed data across at least 3 driver-days for holdout.")
    # Holdout is exclusively human-reviewed, never auto-labeled.
    # Find a deterministic split containing both classes and adequate validation samples.
    chosen = None
    for seed in range(100):
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
        _, valid_idx = next(splitter.split(human, groups=human["group"]))
        valid = human.iloc[valid_idx]
        counts = valid["label"].value_counts()
        if all(counts.get(k, 0) >= MIN_VALID_PER_CLASS for k in (0, 1)):
            chosen = valid
            break
    if chosen is None:
        raise RuntimeError("Not enough diverse human-reviewed NORMAL and FATIGUE driver-days for validation.")
    # Entire driver-days in validation are excluded from ALL training sources.
    train = data[~data["group"].isin(chosen["group"])].copy()
    train_counts = train["label"].value_counts()
    if any(train_counts.get(k, 0) < MIN_TRAIN_PER_CLASS for k in (0, 1)):
        raise RuntimeError(f"Insufficient training data per class: {train_counts.to_dict()}")
    model = RandomForestClassifier(n_estimators=200, min_samples_leaf=3,
                                   class_weight="balanced", random_state=42, n_jobs=-1)
    model.fit(train[FEATURES], train["label"])
    pred = model.predict(chosen[FEATURES])
    precision, recall, f1, support = precision_recall_fscore_support(
        chosen["label"], pred, labels=[0, 1], zero_division=0
    )
    passed = bool(precision[1] >= MIN_PRECISION and recall[1] >= MIN_RECALL)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "db": str(db_path), "candidate_only": True, "approved_for_deployment": False,
        "passed_initial_gate": passed,
        "thresholds": {"fatigue_precision": MIN_PRECISION, "fatigue_recall": MIN_RECALL},
        "features": FEATURES,
        "train_rows": len(train), "validation_rows": len(chosen),
        "train_labels": {str(k): int(v) for k,v in Counter(train["label"]).items()},
        "validation_labels": {str(k): int(v) for k,v in Counter(chosen["label"]).items()},
        "validation_source": "human_review_only",
        "grouping": "user_id + calendar_day",
        "accuracy": float(accuracy_score(chosen["label"], pred)),
        "confusion_matrix_labels_0_1": confusion_matrix(chosen["label"], pred, labels=[0,1]).tolist(),
        "per_class": {
            str(k): {"precision": float(precision[i]), "recall": float(recall[i]),
                     "f1": float(f1[i]), "support": int(support[i])}
            for i,k in enumerate((0,1))
        }
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"validation_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Save only candidates passing the preliminary gate, never overwrite an active model.
    if passed:
        joblib.dump({"model": model, "features": FEATURES, "labels": [0, 1]},
                    output_dir / f"candidate_{stamp}.joblib")
    print(json.dumps({"report": str(report_path), "passed_initial_gate": passed,
                      "candidate_saved": passed, "validation_rows": len(chosen)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fatigue.db")
    parser.add_argument("--out", default="local_training_runs")
    args = parser.parse_args()
    try:
        run(args.db, args.out)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"Training stopped safely: {exc}\n")
