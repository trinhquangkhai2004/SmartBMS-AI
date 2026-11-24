"""P3.7 metrics and the preregistered FULL_ELIGIBLE acceptance calculation."""
from collections import Counter

import numpy as np


def band(reference, cutoff):
    return "SOH_GE_80" if reference >= cutoff else "SOH_LT_80"


def metric_pack(errors, prefix):
    if len(errors):
        e = np.asarray(errors, dtype=float)
        scores = [np.abs(e).mean(), np.sqrt(np.mean(e**2)),
                  np.percentile(np.abs(e), 95), np.abs(e).max()]
    else:
        scores = [None] * 4
    return {f"{prefix}_{key}_pp": float(value) if value is not None else None
            for key, value in zip(("mae", "rmse", "p95", "max"), scores)}


def errors_for(rows, field):
    return [r[field] - r["soh_ref_percent"] for r in rows if r[field] is not None]


def describe(rows):
    n = len(rows)
    raw = errors_for(rows, "rf_raw")
    valid = errors_for([r for r in rows if r["status"] == "VALID"], "soh_percent")
    counts = Counter(r["status"] for r in rows)
    if len(valid) != counts["VALID"]:
        raise ValueError("A VALID row must contain a guarded prediction")
    return dict(eligible=n, cells=len({r["cell_id"] for r in rows}), raw_count=len(raw),
                valid_count=len(valid), raw_missing=n-len(raw),
                raw_coverage=len(raw)/n if n else None, valid_coverage=len(valid)/n if n else None,
                n_valid=counts["VALID"], n_out_of_domain=counts["OUT_OF_DOMAIN"],
                n_model_uncertain=counts["MODEL_UNCERTAIN"], n_jump=counts["SOH_JUMP_ANOMALY"],
                n_missing_feature=counts["MISSING_FEATURE"], n_stale=counts["STALE_INPUT"],
                n_insufficient_history=counts["INSUFFICIENT_HISTORY"],
                n_other=n-sum(counts[key] for key in ("VALID", "OUT_OF_DOMAIN", "MODEL_UNCERTAIN",
                   "SOH_JUMP_ANOMALY", "MISSING_FEATURE", "STALE_INPUT", "INSUFFICIENT_HISTORY")),
                n_resync=sum(r.get("reason") == "SOH_BASELINE_RESYNCED" for r in rows),
                **metric_pack(raw, "raw"), **metric_pack(valid, "valid"))


def acceptance(global_metrics, cells, criteria):
    failed, unassessable = [], []

    def check(label, value, threshold, maximum=False):
        if value is None:
            unassessable.append(label)
        elif (maximum and value > threshold) or (not maximum and value < threshold):
            failed.append(label)

    check("global.raw_coverage", global_metrics["raw_coverage"], criteria["raw_coverage_global_min"])
    check("global.valid_coverage", global_metrics["valid_coverage"], criteria["valid_coverage_global_min"])
    for cell, values in cells.items():
        check(f"{cell}.raw_coverage", values["raw_coverage"], criteria["raw_coverage_per_cell_min"])
        for key in ("raw_max_pp", "valid_max_pp"):
            check(f"{cell}.{key}", values[key], criteria["max_abs_error_pp"], maximum=True)
    status = "ER5_NOT_MET" if failed else "ER5_NOT_ASSESSABLE" if unassessable else "ER5_PASS"
    return dict(status=status, failures=failed, unassessable=unassessable)
