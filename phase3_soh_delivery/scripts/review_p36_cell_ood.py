"""Rebuild the D12 per-cell development tables for the signed p36-r1 candidate."""
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.soh.evaluation_guard import EvaluationGuard

FREEZE = "76654f841054f51796b86ec22e53fda5baf4826c69bbc97c0d5baadd1f9dbc9b"
STATUSES = ("VALID", "OUT_OF_DOMAIN", "MODEL_UNCERTAIN", "SOH_JUMP_ANOMALY")
REPORTS = ROOT / "reports"


def read_json(path):
    return json.loads((ROOT / path).read_bytes())


def verify(path, expected):
    if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {path}")


def write_csv(name, rows):
    with (REPORTS / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build():
    manifest = "manifests/p3_model_freeze.json"
    verify(manifest, FREEZE)
    m = read_json(manifest)
    checks = {**m["input_hashes"], **m["artifact_hashes"]}
    oof_path = "reports/P3_6_OOF_DEVELOPMENT.parquet"
    features_path = "data/features/soh_feature_table.parquet"
    cal_path = "manifests/p3_6_guard_calibration.json"
    split_path = "manifests/p3_split_manifest.json"
    fold_path = "manifests/p3_cv_fold_manifest.json"
    for path in (oof_path, features_path, cal_path, split_path, fold_path, "src/soh/evaluation_guard.py"):
        verify(path, checks[path])
    cal = read_json(cal_path)
    split = read_json(split_path)
    dev = split["development_cell_ids"]
    assert len(set(dev)) == 57 and set(dev).isdisjoint(split["held_out_cell_ids"])
    fold_of = {c: row["fold"] for row in read_json(fold_path)["folds"] for c in row["validation_cell_ids"]}
    names = m["primary_features"]
    oof = pq.read_table(ROOT / oof_path)
    hi = pq.read_table(ROOT / features_path, columns=["cell_id", "cycle_id", "validation_fold", *names])
    for k in ("cell_id", "cycle_id", "validation_fold"):
        assert oof[k].combine_chunks().equals(hi[k].combine_chunks()), k
    cells = np.asarray(oof["cell_id"].to_pylist())
    cycles = oof["cycle_id"].to_numpy()
    assert set(cells) == set(dev) and len(set(zip(cells, cycles))) == len(cells) == 106733
    x = np.column_stack([hi[n].to_numpy() for n in names])
    pred, y, sigma = (oof[k].to_numpy() for k in ("rf_weighted", "soh_ref_percent", "rf_sigma_trees_pp"))
    assert all(np.isfinite(v).all() for v in (x, pred, y, sigma))
    fold_ids = oof["validation_fold"].to_numpy()
    summary, detail, totals = [], [], Counter()
    for cell in dev:
        idx = np.flatnonzero(cells == cell)
        idx = idx[np.argsort(cycles[idx])]
        fold = fold_of[cell]
        assert np.all(fold_ids[idx] == fold)
        bounds = cal["fold_weighted_and_unweighted_bounds"][str(fold)]
        policy = dict(m["policy"], feature_bounds=bounds)
        guard = EvaluationGuard(policy)
        status = np.array([guard.evaluate(cell, "p36-r1-oof", int(cycles[j]), x[j], pred[j], sigma[j],
                                          stale=False)["status"] for j in idx])
        lo, hi_bound = np.array([bounds[n]["weighted"] for n in names]).T
        below, above = x[idx] < lo, x[idx] > hi_bound
        violations = (below | above).sum(axis=1)
        ood = violations >= policy["min_feature_violations"]
        assert np.array_equal(ood, status == "OUT_OF_DOMAIN")
        assert np.array_equal((~ood) & (sigma[idx] > policy["sigma_threshold_pp"]), status == "MODEL_UNCERTAIN")
        errors = np.abs(pred[idx] - y[idx])
        assert set(status) <= set(STATUSES)
        totals.update(status)
        counts = {s: int((status == s).sum()) for s in STATUSES}
        row = dict(cell_id=cell, validation_fold=fold, total=len(idx), **counts,
                   valid_pct=100 * counts["VALID"] / len(idx))
        groups = {"ALL": np.ones(len(idx), dtype=bool), **{s: status == s for s in STATUSES},
                  "OOD_OR_UNCERTAIN": np.isin(status, ["OUT_OF_DOMAIN", "MODEL_UNCERTAIN"])}
        for group, mask in groups.items():
            selected = errors[mask]
            row[f"{group}_n"] = len(selected)
            for metric, val in zip(("mae_pp", "p95_abs_pp", "max_abs_pp", "abs_gt_10pp_n"),
                                   (selected.mean(), np.quantile(selected, .95), selected.max(),
                                    int((selected > 10).sum())) if len(selected) else (None,) * 4):
                row[f"{group}_{metric}"] = val
            for j, name in enumerate(names):
                detail.append(dict(cell_id=cell, validation_fold=fold, group=group, n=len(selected), feature=name,
                                   p01_fit_fold=lo[j], p99_fit_fold=hi_bound[j],
                                   below_p01=int(below[mask, j].sum()), above_p99=int(above[mask, j].sum())))
        patterns = Counter(tuple((n, "LOW" if below[i,j] else "HIGH") for j,n in enumerate(names)
                                 if below[i,j] or above[i,j]) for i in np.flatnonzero(ood))
        row["ood_combinations_counts"] = json.dumps(
            {" + ".join(f"{n}:{side}" for n,side in combo): num for combo,num in patterns.most_common()},
            sort_keys=True)
        summary.append(row)
    assert dict(totals) == cal["guarded_counts"]
    write_csv("P3_6_D12_CELL_OOF.csv", sorted(summary, key=lambda r: r["valid_pct"]))
    write_csv("P3_6_D12_FEATURE_BREACHES.csv", detail)


if __name__ == "__main__":
    build()
