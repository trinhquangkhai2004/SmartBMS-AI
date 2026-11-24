"""Build p35-r1 using only the per-cell files named by the frozen development list."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pyarrow.compute as pc
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.soh.feature_extractor import FAST, TOP, FEATURE_NAMES, extract_charge


def manifest(name, sha=None):
    content = (ROOT/"manifests"/name).read_bytes()
    if sha is not None and hashlib.sha256(content).hexdigest() != sha:
        raise ValueError(f"Frozen input changed: {name}")
    return json.loads(content)


SPLIT_HASH = "a364c48d2903bcdb42794502aff1facdd01de4d5b0322417fc3a721c8a66ef7a"
FOLD_HASH = "45305db16fdf8efb29f52a1a0b3b4c7fb39d6416b356cab9a15b0e36998cd274"
# Four P3.2 excluded cycle keys. Apply only to cells already admitted for development.
REVIEW = {("4-5",341),("9-5",185),("9-5",1188),("9-7",1323)}
SCHEMA = pa.schema([("cell_id",pa.string()), ("cycle_id",pa.int64()),
                    ("end_charge_sample_index",pa.int32()), ("validation_fold",pa.int8()),
                    *((name,pa.float64()) for name in FEATURE_NAMES), ("missing_reasons",pa.string())])


def process_cell(job):
    cell, fold, expected, temp = job
    allowed = manifest("p3_split_manifest.json", SPLIT_HASH)["development_cell_ids"]
    if cell not in allowed or not re.fullmatch(r"[1-9][0-9]*-[1-9][0-9]*", cell):
        raise ValueError("Cell outside frozen development set")
    path = ROOT/"data/staging/rt_batt_v2"/f"{cell}.parquet"
    cols = ["cell_id","cycle_id","sample_index","raw_status","time_s_raw","voltage_v_raw","current_ma_raw"]
    # Exactly one physical file; projected signals; no capacity, discharge or label input to extractor.
    tab = pq.read_table(path, columns=cols, filters=[("raw_status","in",[FAST,TOP])], use_threads=False)
    if tab["cell_id"].unique().to_pylist() != [cell]:
        raise ValueError("Mislabeled cell file")
    cycles=tab["cycle_id"].to_numpy()
    samples=tab["sample_index"].to_numpy()
    fast=pc.equal(tab["raw_status"], FAST).to_numpy(zero_copy_only=False)
    stages=np.array([TOP,FAST])[fast.astype(np.int8)]
    t,v,raw=[tab[col].to_numpy() for col in cols[-3:]]
    current=-raw/1000.
    boundaries=np.r_[0,np.flatnonzero(np.diff(cycles))+1,len(cycles)]
    records=[]
    seen=set()
    reasons=Counter()
    nonmissing=Counter()
    for start,stop in zip(boundaries[:-1],boundaries[1:]):
        cycle=int(cycles[start])
        if cycle <= 5 or (cell,cycle) in REVIEW:
            continue
        if cycle in seen or not np.all(np.diff(samples[start:stop])==1):
            raise ValueError(f"Ambiguous charge {cell} {cycle}")
        seen.add(cycle)
        ix=slice(start,stop)
        out,why=extract_charge(t[ix],v[ix],current[ix],stages[ix])
        nonmissing.update(k for k,val in out.items() if val is not None)
        reasons.update(why.values())
        records.append(dict(cell_id=cell,cycle_id=cycle,end_charge_sample_index=int(samples[stop-1]),
                            validation_fold=fold,**out,missing_reasons=json.dumps(why,sort_keys=True)))
    if len(records)!=expected: raise ValueError(f"Eligibility mismatch: {cell}, {len(records)}, expected {expected}")
    pq.write_table(pa.Table.from_pylist(records,schema=SCHEMA),Path(temp)/f"{cell}.parquet")
    return dict(cell=cell,fold=fold,rows=len(records),available=dict(nonmissing),reasons=dict(reasons))


def main():
    import tempfile
    parser=argparse.ArgumentParser()
    parser.add_argument("--workers",type=int,default=2)
    args=parser.parse_args()
    split=manifest("p3_split_manifest.json",SPLIT_HASH)
    dev=split["development_cell_ids"]
    status=manifest("p3_milestone_status.json")
    gate=next(x for x in status["milestones"] if x["milestone_id"]=="P3.4")
    if gate["status"]!="PASS" or len(set(dev))!=57 or "7-5" in dev:
        raise ValueError("P3.4 approval / development allowlist mismatch")
    folds=manifest("p3_cv_fold_manifest.json",FOLD_HASH)
    foldmap={cell:f["fold"] for f in folds["folds"] for cell in f["validation_cell_ids"]}
    counts={c["cell_id"]:c["labels"] for c in manifest("p3_4_audit_summary.json")["per_cell_counts"] if c["cell_id"] in dev}
    if set(foldmap)!=set(dev) or sum(counts.values())!=106733: raise ValueError("Fold/row reconciliation failed")
    dest=ROOT/"data/features";dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as temp:
        jobs=[(cell,foldmap[cell],counts[cell],temp) for cell in dev]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            result=list(pool.map(process_cell,jobs))
        merged=Path(temp)/"merged.parquet"
        with pq.ParquetWriter(merged,SCHEMA) as writer:
            for cell in dev: writer.write_table(pq.read_table(Path(temp)/f"{cell}.parquet",schema=SCHEMA))
        if pq.ParquetFile(merged).metadata.num_rows!=106733: raise ValueError("Final row count mismatch")
        os.replace(merged,dest/"soh_feature_table.parquet")
    data={"split_sha256":SPLIT_HASH,"fold_sha256":FOLD_HASH,"cells":result}
    (ROOT/"manifests/p3_5_development_audit.json").write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":
    main()
