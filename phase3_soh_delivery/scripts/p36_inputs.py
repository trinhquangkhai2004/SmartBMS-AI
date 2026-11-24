"""Validate frozen P3.6 inputs and construct the keyed development-only matrix."""
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np
import pyarrow.parquet as pq
import yaml

from scripts.build_p35_features import FOLD_HASH, REVIEW, SPLIT_HASH


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ("delta_q_350_358_ah", "q_cc_ah", "q_cv_ah", "q_cv_over_q_cc")
FOLD_COUNTS = (20858, 21986, 20879, 22135, 20875)
CHECKSUM_LIST_HASH = "3202f671b12d5dad6c40d44ca6645790883abd15ea27643fa34a80e80cd0f12e"
CONVERSION_HASH = "e5148ccbef65b968b784a3729e03a1589a96f33ccd50e244dca7b2ea14d66f3e"
STAGING = Path("data/staging/rt_batt_v2")
LEDGER = Path("reports/test_exposure_ledger.md")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_bytes(root, path, expected):
    raw = (root / path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, f"Frozen input changed: {path}")
    return raw


def dump_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


@dataclass(frozen=True)
class Development:
    x: np.ndarray
    y: np.ndarray
    cells: np.ndarray
    cycles: np.ndarray
    folds: np.ndarray
    evidence: dict

    def split(self, fold):
        validation = self.folds == fold
        return ~validation, validation


def labels_from_summary(cell, summary):
    require(summary["cell_id"] == cell, f"Unexpected cell in staging summary: {cell}")
    rows = summary["dq_by_cycle_raw"]
    observed = {row["cycle_id"]: row["value"] / 1000 for row in rows}
    require(len(observed) == len(rows), f"Duplicate label keys: {cell}")
    reference = median(observed[cycle] for cycle in range(1, 6))
    require(np.isfinite(reference) and reference > 0, f"Invalid Q_ref: {cell}")
    labels = {cycle: 100 * capacity / reference for cycle, capacity in observed.items()
              if cycle > 5 and (cell, cycle) not in REVIEW}
    require(np.isfinite(list(labels.values())).all() and min(labels.values()) > 0,
            f"Invalid reconstructed label: {cell}")
    return labels


def cell_weights(groups):
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    weight = len(groups) / (len(counts) * counts[inverse])
    np.testing.assert_allclose(np.bincount(inverse, weights=weight), len(groups) / len(counts), rtol=1e-12)
    return weight


def development(root=ROOT):
    milestones = {m["milestone_id"]: m for m in json.loads(
        (root / "manifests/p3_milestone_status.json").read_bytes())["milestones"]}
    require(all(milestones[f"P3.{i}"]["status"] == "PASS" for i in range(1, 6)),
            "P3.1 through P3.5 must pass before fitting")
    p35 = milestones["P3.5"]
    require(p35["release_status"] == "FEATURES_LOCKED"
            and p35["decisions"][0]["status"] == "APPROVED", "D04 release required")
    require("UNOPENED" in (root / LEDGER).read_text(encoding="utf-8")
            and milestones["P3.6"]["heldout_evaluation"] == "UNOPENED", "Held-out gate changed")
    split_path = "manifests/p3_split_manifest.json"
    fold_path = "manifests/p3_cv_fold_manifest.json"
    split = json.loads(checked_bytes(root, split_path, SPLIT_HASH))
    folds = json.loads(checked_bytes(root, fold_path, FOLD_HASH))
    ids = set(split["development_cell_ids"])
    heldout = set(split["held_out_cell_ids"])
    require(split["revision"] == "p34-r1" and len(ids) == 57 and len(heldout) == 19
            and not ids & heldout and all(re.fullmatch(r"\d+-\d+", cell) for cell in ids),
            "Unexpected p34-r1 development roster")
    require(folds["split_manifest_sha256"] == SPLIT_HASH, "Fold split hash mismatch")
    fold_by_cell = {}
    require([f["fold"] for f in folds["folds"]] == list(range(1, 6)), "Invalid fold sequence")
    for entry, expected_count in zip(folds["folds"], FOLD_COUNTS):
        validation = set(entry["validation_cell_ids"])
        require(validation <= ids and not validation & fold_by_cell.keys()
                and set(entry["train_cell_ids"]) == ids - validation
                and entry["validation_labels"] == expected_count, "Invalid locked fold partition")
        fold_by_cell.update(dict.fromkeys(validation, entry["fold"]))
    require(fold_by_cell.keys() == ids, "Each development cell must validate once")
    checksum = checked_bytes(root, "manifests/p3_5_SHA256SUMS.txt", CHECKSUM_LIST_HASH)
    frozen = dict(reversed(line.split()) for line in checksum.decode().splitlines())
    schema_path = "artifacts/soh/feature_schema.json"
    schema = json.loads(checked_bytes(root, schema_path, frozen[schema_path]))
    require(tuple(schema["primary_features"]) == PRIMARY
            and tuple(p35["decisions"][0]["primary_features"]) == PRIMARY, "D04 feature order")
    policy_path = "configs/p3_soh_reference_policy.yaml"
    approved_inputs = {i["path"]: i["sha256"] for i in milestones["P3.6"]["inputs"]}
    policy = yaml.safe_load(checked_bytes(root, policy_path, approved_inputs[policy_path]))
    require(policy["approved_decisions"] == ["D02", "D03"] and policy["d02"]["method"] == "median"
            and policy["d02"]["first_source_cycle_ids"] == [1, 2, 3, 4, 5]
            and policy["d03"]["geometry"] == "same_cell_same_cycle_next_discharge_from_p32"
            and not policy["clip_above_100_percent"], "Unexpected D02/D03 label policy")
    feature_path = "data/features/soh_feature_table.parquet"
    require(sha(root / feature_path) == frozen[feature_path], "Frozen feature table changed")
    tab = pq.read_table(root / feature_path, columns=["cell_id", "cycle_id", "validation_fold", *PRIMARY])
    cells = np.asarray(tab["cell_id"].to_pylist())
    cycles = tab["cycle_id"].to_numpy()
    observed_folds = tab["validation_fold"].to_numpy()
    x = np.column_stack([tab[name].to_numpy() for name in PRIMARY])
    require(tab.num_rows == sum(FOLD_COUNTS) and set(cells) == ids and np.isfinite(x).all(),
            "P3.5 development features incomplete")
    require(tuple(Counter(observed_folds)[k] for k in range(1, 6)) == FOLD_COUNTS,
            "Validation row counts differ from locked manifest")
    require(len(set(zip(cells, cycles))) == tab.num_rows, "Feature join keys must be unique")
    conversion = json.loads(checked_bytes(root, STAGING / "conversion_manifest.json", CONVERSION_HASH))
    inventory = {m["cell_id"]: m["summary"] for m in conversion["data_members"] if m["cell_id"] in ids}
    require(inventory.keys() == ids, "Missing signed staging summaries")
    y = np.empty(len(cells))
    for cell in sorted(ids):
        position = np.flatnonzero(cells == cell)
        meta = inventory[cell]
        require(meta["path"] == f"{cell}.json", f"Unexpected staging filename: {cell}")
        summary = json.loads(checked_bytes(root, STAGING / meta["path"], meta["sha256"]))
        labels = labels_from_summary(cell, summary)
        require(set(cycles[position]) == labels.keys() and np.all(observed_folds[position] == fold_by_cell[cell]),
                f"Label join must be 1:1 and match fold for cell {cell}")
        y[position] = [labels[cycle] for cycle in cycles[position]]
    evidence = dict(development_rows=len(cells), development_cells=len(ids), heldout_cells=len(heldout),
                    validation_rows=dict(zip(range(1, 6), FOLD_COUNTS)), split_sha256=SPLIT_HASH,
                    fold_sha256=FOLD_HASH, feature_sha256=frozen[feature_path],
                    feature_schema_sha256=frozen[schema_path], p35_checksums_sha256=CHECKSUM_LIST_HASH,
                    label_policy_sha256=approved_inputs[policy_path], label_source_manifest_sha256=CONVERSION_HASH,
                    label_source="Signed development per-cell JSON; reconstruct D02/D03 in Ah",
                    checked_development_cell_summary_files=inventory, heldout_value_files_read=0,
                    primary_features=list(PRIMARY), target="soh_ref_percent", join="one_to_one_cell_id_cycle_id")
    return Development(x, y, cells, cycles, observed_folds, evidence)
