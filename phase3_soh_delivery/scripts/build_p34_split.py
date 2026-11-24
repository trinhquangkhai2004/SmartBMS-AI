"""Prepare a static cell universe, select once, then audit grouped cross-validation."""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform
import random
import re

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sklearn
from sklearn.model_selection import GroupKFold
import yaml


ID = re.compile(r"[1-9][0-9]*-[1-9][0-9]*")
EXCLUDED = "7-5"
STAGES = ("stage_1_c","stage_2_c","stage_3_c")
DRAFT = "CANDIDATE_FROZEN_PENDING_D05"


def canonical_ids(values):
    ids = list(values)
    if any(not isinstance(value,str) or not ID.fullmatch(value) for value in ids) or len(set(ids))!=len(ids):
        raise ValueError("Noncanonical or duplicate physical cell ID")
    return sorted(ids,key=lambda value:tuple(map(int,value.split("-"))))


def allocate(metadata,quotas,seed):
    ids = canonical_ids(metadata)
    strata = {}
    for cell in ids:
        strata.setdefault(metadata[cell][0],[]).append(cell)
    if set(strata)!=set(quotas) or any(type(q) is not int or not 0<q<len(strata[rate]) for rate,q in quotas.items()):
        raise ValueError("Invalid held-out quota or unrepresented stratum")
    rng = random.Random(seed)
    selected = []
    for rate in sorted(strata):
        ids_in_rate = strata[rate].copy()
        rng.shuffle(ids_in_rate)
        selected.extend(ids_in_rate[:quotas[rate]])
    held_out = set(selected)
    return canonical_ids(set(ids)-held_out),canonical_ids(held_out)


def reconcile_counts(counts,development,held_out):
    all_ids = canonical_ids([*development,*held_out])
    if set(all_ids)!=set(counts) or any(type(count) is not int or count<=0 for count in counts.values()):
        raise ValueError("Split or counts differ from eligible keys")
    return sum(counts[c] for c in development),sum(counts[c] for c in held_out)


def build_folds(counts,n_splits):
    ids = canonical_ids(counts)
    if len(ids)<n_splits or any(type(n) is not int or n<=0 for n in counts.values()):
        raise ValueError("GroupKFold needs at least five labeled development cells")
    groups = np.repeat(np.array(ids),[counts[cell] for cell in ids])
    splitter = GroupKFold(n_splits=n_splits,shuffle=False)
    folds = []
    for number,(train,validation) in enumerate(splitter.split(np.zeros((len(groups),1),dtype=np.uint8),groups=groups),1):
        train_cells = canonical_ids(set(groups[train].tolist()))
        val_cells = canonical_ids(set(groups[validation].tolist()))
        folds.append({"fold":number,"train_cell_ids":train_cells,"validation_cell_ids":val_cells,
                      "train_cells":len(train_cells),"validation_cells":len(val_cells),
                      "train_labels":len(train),"validation_labels":len(validation)})
    return folds


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file,"sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path,value):
    with path.open("x",encoding="utf-8",newline="\n") as file:
        json.dump(value,file,ensure_ascii=False,indent=2,allow_nan=False)
        file.write("\n")


def check_hash(path,expected):
    if digest(path)!=expected or not re.fullmatch("[0-9a-f]{64}",expected):
        raise ValueError(f"Input hash does not match policy: {path.name}")


def read_policy(path):
    policy = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if (
        policy["status"]!="CANDIDATE_PENDING_D05"
        or policy["outer"]["seed"]!=42
        or policy["outer"]["held_out_quotas"]!={2:1,3:6,4:6,5:6}
        or policy["outer"]["expected_per_stratum"]!={2:5,3:24,4:23,5:24}
        or policy["inner"]["n_splits"]!=5
        or policy["excluded_cells"]!={EXCLUDED:"QREF_COMMISSIONING_BLOCKED"}
        or policy["engine"]["python"]!=platform.python_version()
        or policy["engine"]["scikit_learn"]!=sklearn.__version__
        or policy["engine"]["numpy"]!=np.__version__
        or policy["engine"]["pyarrow"]!=pa.__version__
    ):
        raise ValueError("Split execution differs from the predeclared policy")
    return policy


def prepare(policy_path,inputs,data,approved_policy,out):
    policy = read_policy(policy_path)
    hashes = policy["input_sha256"]
    labels = data/"soh_labels.parquet"
    protocols = inputs/"protocol_inventory.csv"
    history = inputs/"p3_4_presplit_milestone_snapshot.json"
    if not history.is_file():
        history = inputs/"p3_milestone_status.json"
    for path,name in ((labels,"labels"),(protocols,"protocol_inventory"),(approved_policy,"label_policy"),
                      (history,"p3_milestone_status_before_p34")):
        check_hash(path,hashes[name])
    approved = yaml.safe_load(approved_policy.read_text(encoding="utf-8-sig"))
    milestone = next(m for m in read_json(history)["milestones"] if m["milestone_id"]=="P3.3")
    decisions = {d["id"]:d["status"] for d in milestone["decisions"]}
    if (milestone["status"]!="PASS" or approved["release_status"]!="APPROVED_V1" or
            set(approved["approved_decisions"])!={"D02","D03"} or any(decisions.get(d)!="APPROVED" for d in ("D02","D03"))
            or not approved["downstream_split_allowed"]
            or approved["approved_labels_sha256"]!=hashes["labels"]
            or EXCLUDED not in approved["d02"]["excluded_cells_v1"]):
        raise ValueError("P3.3 v1 release and its 7-5 exclusion must be approved")
    eligible = set()
    with pq.ParquetFile(labels) as parquet:
        for batch in parquet.iter_batches(columns=["cell_id"]):
            eligible.update(pc.unique(batch.column(0)).to_pylist())
    ids = canonical_ids(eligible)
    if len(ids)!=76 or EXCLUDED in eligible:
        raise ValueError("Expected 76 approved physical cells excluding 7-5")
    metadata = {}
    with protocols.open(encoding="utf-8",newline="") as file:
        for row in csv.DictReader(file):
            cell = canonical_ids([row["cell_id"]])[0]
            if cell in metadata:
                raise ValueError(f"Duplicate protocol cell {cell}")
            reference,measured = (json.loads(row[field]) for field in ("reference_rates_c","measured_rates_c"))
            if not isinstance(reference,list) or not isinstance(measured,list) or min(len(reference),len(measured))<3:
                raise ValueError(f"Incomplete static protocol {cell}")
            if any(type(rate) is not int or rate<=0 for rate in reference[:3]) or any(
                not np.isfinite(actual) or abs(ref-actual)>.15 for ref,actual in zip(reference[:3],measured[:3])
            ):
                raise ValueError(f"Unverified first three static discharge rates: {cell}")
            metadata[cell] = tuple(reference[:3])
    if set(metadata)!=(eligible|{EXCLUDED}):
        raise ValueError("Protocol keys differ from approved and excluded cells")
    counts = Counter(metadata[cell][0] for cell in ids)
    if counts!=policy["outer"]["expected_per_stratum"]:
        raise ValueError("Static stratum counts differ from declared quotas")
    with out.open("x",encoding="utf-8",newline="") as file:
        writer = csv.writer(file,lineterminator="\n")
        writer.writerow(("cell_id",*STAGES))
        writer.writerows((cell,*metadata[cell]) for cell in ids)
    print(f"Prepared {len(ids)} canonical IDs using only cell identity and three static reference rates.",flush=True)


def select(policy_path,eligible,out):
    policy = read_policy(policy_path)
    with eligible.open(encoding="utf-8",newline="") as file:
        source = csv.DictReader(file)
        if tuple(source.fieldnames or ())!=("cell_id",*STAGES):
            raise ValueError("Outer selection accepts only cell ID and the static rate columns")
        rows = list(source)
    ids = canonical_ids(row["cell_id"] for row in rows)
    static = {row["cell_id"]: tuple(int(row[stage]) for stage in STAGES) for row in rows}
    outer = policy["outer"]
    if len(ids)!=76 or EXCLUDED in ids or Counter(rates[0] for rates in static.values())!=outer["expected_per_stratum"]:
        raise ValueError("Invalid eligible cell set")
    dev, test = allocate(static,outer["held_out_quotas"],outer["seed"])
    if (len(dev),len(test))!=(57,19):
        raise ValueError("Allocation differs from 57/19")
    write_json(out,{
        "revision":"p34-r1","status":DRAFT,"label_release":"APPROVED_V1",
        "policy_sha256":digest(policy_path),"eligibility_table_sha256":digest(eligible),"input_sha256":policy["input_sha256"],
        "seed":outer["seed"],"algorithm":"Python random.Random(42).shuffle; one generator shared across ascending strata",
        "python_version":platform.python_version(),"stratum":"stage_1_c","strata_order_c":sorted(outer["held_out_quotas"]),
        "held_out_quotas":outer["held_out_quotas"],"excluded_cells":policy["excluded_cells"],
        "development_cell_ids":dev,"held_out_cell_ids":test,
        "cell_metadata":[{"cell_id":cell,**dict(zip(STAGES,static[cell])),"partition":"development" if cell in dev else "held_out"} for cell in ids],
    })
    print("Frozen candidate 57 development / 19 held-out using only the static eligibility table.",flush=True)



def count_label_keys(path):
    counts, keys = Counter(),set()
    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(columns=["cell_id","cycle_id"]):
            for cell,cycle in zip(batch.column(0).to_pylist(),batch.column(1).to_pylist()):
                key = cell,cycle
                if key in keys or not isinstance(cycle,int) or cycle<=0:
                    raise ValueError(f"Duplicate or invalid label key: {key}")
                keys.add(key)
                counts[cell] += 1
    canonical_ids(counts)
    return counts


def count_signal_ids(path):
    counts = Counter()
    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(columns=["cell_id"],batch_size=131072):
            for entry in pc.value_counts(batch.column(0)).to_pylist():
                counts[entry["values"]] += entry["counts"]
    canonical_ids(counts)
    return counts


def check_folds(folds,dev,test,counts):
    dev_set,test_set = set(dev),set(test)
    validation_frequency = Counter()
    for fold in folds:
        train, val = set(fold["train_cell_ids"]),set(fold["validation_cell_ids"])
        if train & val or (train | val)!=dev_set or (train | val)&test_set:
            raise ValueError(f"Leaking or incomplete fold: {fold['fold']}")
        if fold["train_labels"]!=sum(counts[cell] for cell in train) or fold["validation_labels"]!=sum(counts[cell] for cell in val):
            raise ValueError("Fold label totals differ from cell mapping")
        validation_frequency.update(val)
    if len(folds)!=5 or validation_frequency!=dict.fromkeys(dev,1):
        raise ValueError("Every development cell must appear in validation once")


def audit(policy_path,split_path,inputs,data,out,folds_only=False):
    policy = read_policy(policy_path)
    split = read_json(split_path)
    if split["policy_sha256"]!=digest(policy_path) or split["status"]!=DRAFT:
        raise ValueError("Candidate split does not match policy predeclared for P3.4")
    dev,test = split["development_cell_ids"],split["held_out_cell_ids"]
    if (len(dev),len(test))!=(57,19) or EXCLUDED in dev or EXCLUDED in test:
        raise ValueError("Invalid outer split")
    labels = data/"soh_labels.parquet"
    check_hash(labels,policy["input_sha256"]["labels"])
    counts = count_label_keys(labels)
    development_total,held_out_total = reconcile_counts(counts,dev,test)
    if development_total+held_out_total!=143863 or counts["1-1"]!=1499:
        raise ValueError("Released label total or reference cell count differs")
    dev_counts = {cell:counts[cell] for cell in dev}
    folds = build_folds(dev_counts,policy["inner"]["n_splits"])
    check_folds(folds,dev,test,dev_counts)
    out.mkdir(parents=True,exist_ok=False)
    write_json(out/"p3_cv_fold_manifest.json",{
        "revision":"p34-r1","status":DRAFT,"split_manifest_sha256":digest(split_path),
        "label_sha256":policy["input_sha256"]["labels"],"label_columns_read":["cell_id","cycle_id"],
        "algorithm":"sklearn.model_selection.GroupKFold(n_splits=5, shuffle=False)",
        "versions":{"python":platform.python_version(),"scikit_learn":sklearn.__version__,"numpy":np.__version__},
        "fold_number_origin":1,"group_key":"cell_id","policy_sha256":digest(policy_path),
        "development_label_count":development_total,"folds":folds,
    })
    if folds_only:
        return

    canonical = data/"canonical_cycles.parquet"
    check_hash(canonical,policy["input_sha256"]["canonical_signals"])
    signals = count_signal_ids(canonical)
    p32 = read_json(inputs/"p3_2_readback.json")
    if set(signals)!=(set(counts)|{EXCLUDED}) or sum(signals.values())!=p32["canonical_rows"]:
        raise ValueError("Canonical signal IDs or row count differ from verified P3.2 coverage")
    group_by_id = {cell:"development" for cell in dev} | {cell:"held_out" for cell in test} | {EXCLUDED:"excluded_v1"}
    if len(group_by_id)!=77:
        raise ValueError("Signal membership is not unique by physical cell")
    signal_totals = Counter()
    for cell,n in signals.items():
        signal_totals[group_by_id[cell]]+=n
    groups = [row for row in split["cell_metadata"]]
    profiles_by_partition = {
        name:{tuple(row[stage] for stage in STAGES) for row in groups if row["partition"]==name}
        for name in ("development","held_out")
    }
    write_json(out/"p3_4_audit_summary.json",{
        "status":"PASS_STRUCTURAL_AUDIT_PENDING_D05",
        "split_manifest_sha256":digest(split_path),
        "cv_fold_manifest_sha256":digest(out/"p3_cv_fold_manifest.json"),
        "metadata_columns_for_draw":["cell_id",*STAGES],
        "label_columns_for_post_split_audit":["cell_id","cycle_id"],
        "canonical_columns_for_post_split_audit":["cell_id"],
        "counts":{"eligible_cells":len(counts),"development_cells":len(dev),"held_out_cells":len(test),
                  "excluded_cells":1,"development_labels":development_total,"held_out_labels":held_out_total,
                  "labels_total":sum(counts.values()),"signal_rows":dict(signal_totals)},
        "overlap":{"cell_ids":len(set(dev)&set(test)),"labeled_keys":0,"canonical_rows":0,"held_out_cells_in_cv":0},
        "validation_frequency":dict.fromkeys(dev,1),
        "reference_cell_1_1":{"partition":group_by_id["1-1"],"labels":counts["1-1"]},
        "per_cell_counts":[{"cell_id":cell,"partition":group_by_id[cell],"labels":counts.get(cell,0),
                           "canonical_rows":signals[cell]} for cell in canonical_ids(signals)],
        "shared_profile_first_three_c":[list(t) for t in sorted(profiles_by_partition["development"]&profiles_by_partition["held_out"])],
    })
    print(f"Audit: {development_total} development + {held_out_total} held-out label keys; zero overlap.",flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_subparsers(dest="stage",required=True)
    prep = stage.add_parser("prepare")
    for flag in ("policy","inputs","data","approved-policy","out"):
        prep.add_argument("--"+flag,type=Path,required=True)
    draw = stage.add_parser("select")
    for flag in ("policy","eligible","out"):
        draw.add_argument("--"+flag,type=Path,required=True)
    inspect = stage.add_parser("audit")
    for flag in ("policy","split","inputs","data","out"):
        inspect.add_argument("--"+flag,type=Path,required=True)
    inspect.add_argument("--folds-only",action="store_true")
    args = parser.parse_args()
    if args.stage=="prepare":
        prepare(args.policy,args.inputs,args.data,args.approved_policy,args.out)
    elif args.stage=="select":
        select(args.policy,args.eligible,args.out)
    else:
        audit(args.policy,args.split,args.inputs,args.data,args.out,args.folds_only)


if __name__=="__main__":
    main()
