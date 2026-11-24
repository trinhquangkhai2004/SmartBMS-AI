"""Run preregistered P3.6 CV, dev-only selection, and full-development refits."""
import argparse
import csv
import importlib.metadata
import json
import platform
import tempfile
from pathlib import Path

import joblib
import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from xgboost import XGBRegressor

from scripts.p36_inputs import PRIMARY, ROOT, cell_weights, development, dump_json, require, sha


RF_CONFIG = "configs/p3_rf_training.yaml"
XGB_CONFIG = "configs/p3_xgb_training.yaml"
REQUIREMENTS = "configs/p3_training_requirements.txt"
ARTIFACTS = "artifacts/soh"
REPORTS = "reports"
MANIFESTS = "manifests"


def read_config(path):
    return yaml.safe_load((ROOT / path).read_bytes())


def cell_scores(y, predictions, cells):
    residual = predictions - y
    scores = {}
    for cell in np.unique(cells):
        error = residual[cells == cell]
        scores[str(cell)] = {"rows": len(error), "mae_pp": float(np.mean(np.abs(error))),
                             "rmse_pp": float(np.sqrt(np.mean(error**2)))}
    return scores


def macro(scores):
    return {f"macro_{metric}": float(np.mean([v[metric] for v in scores.values()]))
            for metric in ("mae_pp", "rmse_pp")}


def weighted_bounds(x, cells, features):
    result = {}
    for i, name in enumerate(features):
        finite = np.isfinite(x[:, i])
        values = x[finite, i]
        ids, inverse, counts = np.unique(cells[finite], return_inverse=True, return_counts=True)
        require(len(ids) > 0, f"No finite observation for {name}")
        order = np.argsort(values, kind="stable")
        values = values[order]
        weights = 1 / counts[inverse[order]]
        cdf = np.cumsum(weights)
        # Search first empirical CDF step; tolerance absorbs cumulative float rounding at ties.
        indices = np.searchsorted(cdf, len(ids) * np.array([.01, .99]) - 2e-10, side="left")
        unweighted = np.ceil(len(values) * np.array([.01, .99])).astype(int) - 1
        result[name] = dict(weighted=values[indices].tolist(), unweighted=values[unweighted].tolist(),
                            cells_with_finite=len(ids), rows_finite=len(values), missing=int((~finite).sum()),
                            min_finite_rows_per_cell=int(min(counts)))
    return result


def dispersion(model, x):
    # Streaming Welford accumulation gives population standard deviation without allocating T x N.
    mean = np.zeros(len(x))
    second = np.zeros(len(x))
    for k, tree in enumerate(model.estimators_, 1):
        p = tree.predict(x, check_input=False)
        delta = p - mean
        mean += delta / k
        second += delta * (p - mean)
    return np.sqrt(np.maximum(second / len(model.estimators_), 0))


def fit(family, params, x, y, weights, rf, xgb):
    if family == "train_median":
        return DummyRegressor(strategy="median").fit(x, y)
    if family == "ridge":
        model = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(**params))])
        return model.fit(x, y, scale__sample_weight=weights, ridge__sample_weight=weights)
    if family.startswith("rf"):
        model = RandomForestRegressor(random_state=rf["seed"], n_jobs=rf["n_jobs"], **params)
        return model.fit(x, y, sample_weight=None if family == "rf_unweighted" else weights)
    if family == "xgboost":
        model = XGBRegressor(random_state=xgb["seed"], n_jobs=xgb["n_jobs"],
                             **xgb["fixed_parameters"], **params)
        return model.fit(x, y, sample_weight=weights)
    raise ValueError(f"Unknown model family {family}")


def validate_configs(rf, xgb):
    search = rf["hyperparameter_search"]
    require(len(search["candidates"]) == search["max_candidates"]
            and 5 * len(search["candidates"]) == search["weighted_cv_max_fits"], "RF CV budget mismatch")
    allowed = {"n_estimators": {100, 200, 300}, "max_depth": {8, 12, 16},
               "min_samples_leaf": {5, 10, 20}, "max_features": {"sqrt", .5, .7}}
    for params in search["candidates"]:
        require(params.keys() == allowed.keys()
                and all(value in allowed[key] for key, value in params.items()), "RF search outside bounds")
    require(xgb["refit_strategy"] == "FIXED_CV_N_ESTIMATORS" and not xgb["early_stopping"]
            and xgb["eval_set"] is None, "Unexpected XGB refit policy")


def versions():
    packages = [line.split("==")[0] for line in (ROOT / REQUIREMENTS).read_text().splitlines() if line]
    return {name: importlib.metadata.version(name) for name in packages}


def cv(dev, family, name, params, cols, rf, xgb, count=5, sigma=False):
    x = np.asarray(dev.x[:, cols], dtype=np.float32 if family.startswith("rf") else np.float64,
                   order="C")
    oof = np.full(len(dev.y), np.nan)
    oof_sigma = np.full(len(dev.y), np.nan) if sigma else None
    results = []
    for k in range(1, count + 1):
        train, val = dev.split(k)
        weights = cell_weights(dev.cells[train])
        model = fit(family, params, x[train], dev.y[train], weights, rf, xgb)
        require(np.isnan(oof[val]).all(), "Duplicate OOF rows")
        oof[val] = model.predict(x[val])
        require(np.isfinite(oof[val]).all(), "Model returned nonfinite OOF predictions")
        if sigma:
            oof_sigma[val] = dispersion(model, x[val])
        scores = cell_scores(dev.y[val], oof[val], dev.cells[val])
        results.append(dict(fold=k, train_rows=int(train.sum()), validation_rows=int(val.sum()),
                            train_cells=len(np.unique(dev.cells[train])),
                            validation_cells=len(scores), training_weight_total=float(weights.sum()),
                            per_cell=scores, **macro(scores)))
    valid = np.isfinite(oof)
    if count == 5:
        require(valid.all(), "Missing OOF prediction")
    scores = cell_scores(dev.y[valid], oof[valid], dev.cells[valid])
    worst = max(scores, key=lambda cell: scores[cell]["mae_pp"])
    result = dict(name=name, family=family, params=params, features=[PRIMARY[i] for i in cols],
                  per_fold=results, per_cell=scores, worst_cell=worst,
                  worst_cell_mae_pp=scores[worst]["mae_pp"], **macro(scores))
    print(f"{name}: {result['macro_mae_pp']:.6f} pp ({count} fold)", flush=True)
    return result, oof, oof_sigma


def model_path(name):
    return ROOT / ARTIFACTS / f"{name}_model.joblib"


def verify_load(path, expected_hash):
    require(sha(path) == expected_hash, f"Model hash mismatch: {path}")
    return joblib.load(path)


def package(dev, family, name, result, cols, rf, xgb, max_bytes=None):
    x = np.asarray(dev.x[:, cols], dtype=np.float32 if family.startswith("rf") else np.float64,
                   order="C")
    weights = cell_weights(dev.cells)
    model = fit(family, result["params"], x, dev.y, weights, rf, xgb)
    dest = model_path(name)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix="p36-") as tmp:
        path = Path(tmp) / dest.name
        joblib.dump(model, path, compress=rf["artifact"]["joblib_compression_level"])
        size = path.stat().st_size
        exponent = dict(model=name, candidate=result["name"], bytes=size)
        if max_bytes is not None and size > max_bytes:
            return None, exponent
        digest = sha(path)
        loaded = verify_load(path, digest)
        before = model.predict(x)
        after = loaded.predict(x)
        # RF parallel tree summation varies in floating point reduction order.
        np.testing.assert_allclose(before, after, rtol=0, atol=1e-10)
        path.replace(dest)
    info = dict(path=dest.relative_to(ROOT).as_posix(), sha256=digest, bytes=size,
                refit_rows=len(x), refit_cells=len(np.unique(dev.cells)),
                maximum_reload_absolute_difference_pp=float(max(np.abs(before-after))),
                **result["params"])
    return (info, model), exponent


def csv_scores(results, selected):
    path = ROOT / REPORTS / "P3_6_CV_VALIDATION.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        fields = ("configuration", "family", "selected", "parameters", "features", "level", "fold",
                  "cell", "rows", "cell_count", "mae_pp", "rmse_pp", "worst_cell", "worst_cell_mae_pp")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in results:
            common = dict(configuration=r["name"], family=r["family"], selected=r["name"] in selected,
                          parameters=json.dumps(r["params"], sort_keys=True), features="|".join(r["features"]))
            writer.writerow(dict(**common, level="oof_macro", rows=sum(c["rows"] for c in r["per_cell"].values()),
                                 cell_count=len(r["per_cell"]), mae_pp=r["macro_mae_pp"], rmse_pp=r["macro_rmse_pp"],
                                 worst_cell=r["worst_cell"], worst_cell_mae_pp=r["worst_cell_mae_pp"]))
            for f in r["per_fold"]:
                writer.writerow(dict(**common, level="fold_macro", fold=f["fold"], rows=f["validation_rows"],
                                     cell_count=f["validation_cells"], mae_pp=f["macro_mae_pp"],
                                     rmse_pp=f["macro_rmse_pp"]))
                for cell, m in f["per_cell"].items():
                    writer.writerow(dict(**common, level="cell", fold=f["fold"], cell=cell, cell_count=1, **m))


def train(dev, rf, xgb, smoke):
    cols = list(range(len(PRIMARY)))
    median, median_oof, _ = cv(dev, "train_median", "train_median", {}, cols, rf, xgb, count=1 if smoke else 5)
    if smoke:
        ridge, _, _ = cv(dev, "ridge", "ridge_smoke", {"alpha": 1.0}, cols, rf, xgb, count=1)
        train_rows, validation = dev.split(1)
        _, inverse = np.unique(dev.cells[train_rows], return_inverse=True)
        cell_mass = np.bincount(inverse, weights=cell_weights(dev.cells[train_rows]))
        verify_median = float(np.median(dev.y[train_rows]))
        require(np.all(median_oof[validation] == verify_median), "Median sanity mismatch")
        dump_json(ROOT / MANIFESTS / "p3_6_input_readback.json",
                  dict(status="PASS", **dev.evidence, smoke_fold=1, median_target=verify_median,
                       expected_training_weight_per_cell=int(train_rows.sum())/len(cell_mass),
                       min_training_weight_per_cell=float(min(cell_mass)), max_training_weight_per_cell=float(max(cell_mass)),
                       train_median=median, ridge=ridge))
        return
    results = [median]
    by_model = {"train_median": median_oof}
    selected = {"train_median"}
    artifacts = {}
    attempts = []
    candidates = {}

    def search(family, grid, use_sigma=False):
        scored = [cv(dev, family, f"{family}-{i}", params, cols, rf, xgb, sigma=use_sigma)
                  for i, params in enumerate(grid, 1)]
        results.extend(r for r, _, _ in scored)
        return sorted(scored, key=lambda record: (record[0]["macro_mae_pp"], record[0]["name"]))

    med_artifact, _ = package(dev, "train_median", "train_median", median, cols, rf, xgb)
    artifacts["train_median"] = med_artifact[0]
    ridge_grid = [{"alpha": alpha} for alpha in rf["ridge_alphas"]]
    ridge, ridge_oof, _ = search("ridge", ridge_grid)[0]
    ridge_package, _ = package(dev, "ridge", "ridge", ridge, cols, rf, xgb)
    artifacts["ridge"] = ridge_package[0]
    selected.add(ridge["name"])
    by_model["ridge"] = ridge_oof

    search_rf = rf["hyperparameter_search"]
    ranks = search("rf_weighted", search_rf["candidates"], use_sigma=True)
    for candidate, candidate_oof, candidate_sigma in ranks[:search_rf["max_full_development_candidate_refits"]]:
        packed, attempt = package(dev, "rf_weighted", "rf", candidate, cols, rf, xgb,
                                  max_bytes=rf["artifact"]["max_bytes"])
        attempts.append(attempt)
        if packed is not None:
            selected_rf, rf_oof, sigma_oof = candidate, candidate_oof, candidate_sigma
            artifacts["rf"], rf_model = packed
            break
    else:
        csv_scores(results, selected)
        dump_json(ROOT / MANIFESTS / "p3_6_training.json", dict(status="DEPLOYMENT_BUDGET_BLOCKED",
                  attempts=attempts, best_scientific_rf=ranks[0][0], artifact_cap_bytes=rf["artifact"]["max_bytes"]))
        raise RuntimeError("DEPLOYMENT_BUDGET_BLOCKED")

    selected.add(selected_rf["name"])
    by_model["rf_weighted"] = rf_oof
    unweighted, unweighted_oof, _ = cv(dev, "rf_unweighted", "rf_unweighted", selected_rf["params"], cols, rf, xgb)
    packed, _ = package(dev, "rf_unweighted", "rf_unweighted", unweighted, cols, rf, xgb)
    artifacts["rf_unweighted"] = packed[0]
    selected.add(unweighted["name"])
    results.append(unweighted)
    by_model["rf_unweighted"] = unweighted_oof

    xgb_grid = [{"n_estimators": n} for n in xgb["n_estimators_grid"]]
    selected_xgb, xgb_oof, _ = search("xgboost", xgb_grid)[0]
    packed, _ = package(dev, "xgboost", "xgb", selected_xgb, cols, rf, xgb)
    artifacts["xgb"] = packed[0]
    selected.add(selected_xgb["name"])
    by_model["xgboost"] = xgb_oof

    for mode, feature_names in rf["hi_ablation"].items():
        indices = [PRIMARY.index(name) for name in feature_names]
        row, oof, _ = cv(dev, "rf_weighted", mode, selected_rf["params"], indices, rf, xgb)
        packed, _ = package(dev, "rf_weighted", mode, row, indices, rf, xgb)
        artifacts[mode] = dict(**packed[0], features=feature_names)
        by_model[mode] = oof
        selected.add(mode)
        results.append(row)

    frame = {"cell_id": dev.cells.tolist(), "cycle_id": dev.cycles,
             "validation_fold": dev.folds, "soh_ref_percent": dev.y,
             "rf_sigma_trees_pp": sigma_oof, **by_model}
    oof_path = ROOT / REPORTS / "P3_6_OOF_DEVELOPMENT.parquet"
    pq.write_table(pa.table(frame), oof_path, compression="zstd")
    csv_scores(results, selected)
    summaries = {r["name"]: {k: v for k, v in r.items() if k not in ("per_cell", "per_fold")}
                 for r in results}
    x = np.ascontiguousarray(dev.x, dtype=np.float32)
    qlevels = [.5, .9, .95, .99]
    bounds = {k: weighted_bounds(dev.x[dev.folds != k], dev.cells[dev.folds != k], PRIMARY) for k in range(1,6)}
    bindings = [RF_CONFIG, XGB_CONFIG, REQUIREMENTS]
    dump_json(ROOT / MANIFESTS / "p3_6_training.json", dict(
        status="REFIT_VERIFIED", input_gate=dev.evidence, preregistration={p: sha(ROOT / p) for p in bindings},
        candidates=summaries, selected_candidates=sorted(selected), artifacts=artifacts,
        rf_selected=selected_rf["name"], ridge_selected=ridge["name"], xgb_selected=selected_xgb["name"],
        xgb_refit_strategy=xgb["refit_strategy"], xgb_early_stopping=False, xgb_eval_set=None,
        xgb_n_estimators_final=selected_xgb["params"]["n_estimators"],
        rf_size_attempts=attempts, rf_top_cv_candidate=ranks[0][0]["name"], rf_budget_bytes=rf["artifact"]["max_bytes"],
        development_oof_sha256=sha(oof_path), model_selection_oof_SHA256=sha(ROOT / REPORTS / "P3_6_CV_VALIDATION.csv"),
        fit_count={"train_median": 5, "ridge": 5 * len(ridge_grid),
                   "rf_weighted": 5 * len(ranks), "rf_unweighted": 5,
                   "xgboost": 5 * len(xgb_grid), "rf_hi_ablation": 5 * len(rf["hi_ablation"])},
        weighted_bounds_by_fold=bounds, weighted_bounds_full=weighted_bounds(dev.x, dev.cells, PRIMARY),
        sigma_oof_quantiles=dict(zip(map(str, qlevels), np.quantile(sigma_oof, qlevels).tolist())),
        sigma_full_dev_quantiles=dict(zip(map(str, qlevels), np.quantile(dispersion(rf_model, x), qlevels).tolist())),
        runtime=dict(platform=platform.platform(), cpu=platform.processor(), logical_cores=psutil.cpu_count(),
                     physical_ram_bytes=psutil.virtual_memory().total, python=platform.python_version(),
                     libraries=versions(), rf_n_jobs=rf["n_jobs"], xgb_n_jobs=xgb["n_jobs"])))
    print("P3.6 full development models and OOF saved", flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--smoke", action="store_true")
    args = cli.parse_args()
    rf, xgb = read_config(RF_CONFIG), read_config(XGB_CONFIG)
    validate_configs(rf, xgb)
    lock = ROOT / MANIFESTS / "p3_6_preregistration.json"
    prereg = {p: sha(ROOT / p) for p in (RF_CONFIG, XGB_CONFIG, REQUIREMENTS)}
    if lock.exists():
        require(json.loads(lock.read_bytes())["sha256"] == prereg, "Preregistered configuration changed")
    else:
        require(args.smoke, "Run and preregister the smoke check first")
        from datetime import datetime
        dump_json(lock, dict(sha256=prereg, locked_at=datetime.now().astimezone().isoformat(timespec="seconds")))
    if not args.smoke:
        require(json.loads((ROOT / MANIFESTS / "p3_6_input_readback.json").read_bytes())["status"] == "PASS",
                "Input and smoke evidence required before grouped CV")
    with threadpool_limits(limits=1, user_api="blas"):
        train(development(), rf, xgb, args.smoke)


if __name__ == "__main__":
    main()
