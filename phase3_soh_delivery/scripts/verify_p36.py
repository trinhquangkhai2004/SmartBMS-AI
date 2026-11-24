"""Independently check selected OOF rows, one-fold reproducibility and model contracts."""
import csv
import json

import numpy as np
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from scripts.p36_inputs import PRIMARY, ROOT, development, require, sha
from scripts.train_p36 import (
    MANIFESTS, REPORTS, RF_CONFIG, XGB_CONFIG, cv, read_config, verify_load,
)


def main():
    training = json.loads((ROOT / MANIFESTS / "p3_6_training.json").read_bytes())
    dev = development()
    _, validation = dev.split(1)
    oof_path = ROOT / REPORTS / "P3_6_OOF_DEVELOPMENT.parquet"
    require(sha(oof_path) == training["development_oof_sha256"], "OOF hash mismatch")
    table = pq.read_table(oof_path)
    for col, expected in (
        ("cell_id", dev.cells), ("cycle_id", dev.cycles), ("validation_fold", dev.folds), ("soh_ref_percent", dev.y),
    ):
        np.testing.assert_array_equal(table[col].to_pylist(), expected)
    rf, xgb = read_config(RF_CONFIG), read_config(XGB_CONFIG)
    with (ROOT / REPORTS / "P3_6_CV_VALIDATION.csv").open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    selected = {
        "train_median": "train_median", "ridge": training["ridge_selected"],
        "rf_weighted": training["rf_selected"], "rf_unweighted": "rf_unweighted",
        "xgboost": training["xgb_selected"],
    }
    with threadpool_limits(limits=1, user_api="blas"):
        for family, name in selected.items():
            mask = [r["configuration"] == name and r["level"] == "cell" for r in rows]
            per_cell = [r for r, include in zip(rows, mask) if include]
            require(len(per_cell) == 57 and sum(int(r["rows"]) for r in per_cell) == len(dev.y),
                    f"CV cell evidence mismatch for {family}")
            pred = table[family].to_numpy()
            require(np.isfinite(pred).all(), "Nonfinite OOF prediction")
            errors = np.abs(pred - dev.y)
            expected_mae = np.mean([errors[dev.cells == cell].mean() for cell in np.unique(dev.cells)])
            np.testing.assert_allclose(expected_mae, training["candidates"][name]["macro_mae_pp"], atol=1e-12, rtol=0)
            scored, reproduced, sigma = cv(dev, family, f"replay_{family}",
                                           training["candidates"][name]["params"], list(range(len(PRIMARY))),
                                           rf, xgb, count=1, sigma=family == "rf_weighted")
            np.testing.assert_allclose(reproduced[validation], pred[validation], atol=1e-10, rtol=0)
            if sigma is not None:
                np.testing.assert_allclose(sigma[validation], table["rf_sigma_trees_pp"].to_numpy()[validation],
                                           atol=1e-10, rtol=0)
    for name, info in training["artifacts"].items():
        model = verify_load(ROOT / info["path"], info["sha256"])
        if name != "train_median":
            require(model.n_features_in_ == len(info.get("features", PRIMARY)), "Model schema width mismatch")
        if name == "xgb":
            require(model.get_params()["early_stopping_rounds"] is None
                    and model.get_booster().num_boosted_rounds() == training["xgb_n_estimators_final"],
                    "XGB refit violates fixed tree-count contract")
    print("PASS: five primary OOF keyed predictions and macro-MAE, fold-1 prediction replay, RF sigma replay, model contracts")


if __name__ == "__main__":
    main()
