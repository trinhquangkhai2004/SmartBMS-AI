"""Independently reconcile published P3.2 artifacts without opening source pickles."""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_inventory(work, summary):
    counts = {}
    ready = 0
    identities = set()
    with (work/"cell_cycle_inventory.csv").open(encoding="utf-8",newline="") as handle:
        for row in csv.DictReader(handle):
            key = row["cell_id"], int(row["cycle_id"]), int(row["cycle_source_order"])
            parts = sum(int(row[f"{phase}_samples"]) for phase in ("charge","discharge","rest","other"))
            if key[:2] in identities or parts != int(row["sample_rows"]):
                raise ValueError(f"Invalid inventory key or phase count: {key}")
            identities.add(key[:2])
            counts[key] = parts
            if row["pair_status"]=="READY_FOR_P3_3_AUDIT":
                charge = json.loads(row["feature_available_at"])
                label = json.loads(row["label_observed_at"])
                if charge["cell_id"]!=row["cell_id"] or label["cell_id"]!=row["cell_id"] or charge["time_s_raw"]>=label["time_s_raw"]:
                    raise ValueError(f"Invalid pairing chronology: {key}")
                ready += 1
    if len(counts)!=summary["totals"]["cycles"] or ready!=summary["totals"]["ready_pairs"]:
        raise ValueError("Cycle count or ready pair count differs")
    return counts


def check_canonical(work, expected, summary):
    file = work/"canonical_cycles.parquet"
    columns = ["cell_id","cycle_id","cycle_source_order","sample_index","temperature_c"]
    last_key = None
    completed = set()
    n_for_key = 0
    total = 0
    with pq.ParquetFile(file) as parquet:
        if parquet.schema_arrow.metadata[b"current_sign_convention"]!=b"DISCHARGE_POSITIVE_CHARGE_NEGATIVE":
            raise ValueError("Parquet sign convention metadata differs")
        reference = next(parquet.iter_batches(batch_size=836, columns=["cell_id","cycle_id","operation_type","current_a"]))
        if reference.num_rows != 836 or reference.column(0)[0].as_py()!="1-1" or reference.column(1)[-1].as_py()!=1:
            raise ValueError("Canonical reference cycle has unexpected length or identity")
        phases = reference.column(2).to_pylist()
        current = reference.column(3).to_numpy()
        if phases!=["charge"]*383+["discharge"]*453 or not ((current[:383]<0).all() and (current[383:]>0).all()):
            raise ValueError("Canonical reference current signs or boundaries differ")
        for batch in parquet.iter_batches(batch_size=65536,columns=columns):
            if batch.column(4).null_count!=batch.num_rows:
                raise ValueError("Unexpected measured temperature in canonical staging")
            selected = pc.dictionary_encode(batch.column(0))
            groups = selected.indices.to_numpy()
            cycles, orders, samples = (batch.column(k).to_numpy() for k in (1,2,3))
            cuts = np.r_[0,np.flatnonzero((orders[:-1]!=orders[1:])|(groups[:-1]!=groups[1:])|(cycles[:-1]!=cycles[1:]))+1,len(samples)]
            for lo,hi in zip(cuts,cuts[1:]):
                key = selected.dictionary[groups[lo]].as_py(), int(cycles[lo]), int(orders[lo])
                if key != last_key:
                    if last_key is not None:
                        if n_for_key != expected[last_key]:
                            raise ValueError(f"Canonical cycle length differs: {last_key}")
                        completed.add(last_key)
                    if key in completed or key not in expected:
                        raise ValueError(f"Canonical unexpected or repeated key: {key}")
                    last_key, n_for_key = key, 0
                if not np.array_equal(samples[lo:hi],np.arange(n_for_key,n_for_key+hi-lo)):
                    raise ValueError(f"Canonical sample order differs: {key}")
                n_for_key += hi-lo
            total += len(samples)
    if last_key is None or n_for_key!=expected[last_key]:
        raise ValueError("Last cycle does not match inventory")
    completed.add(last_key)
    if len(completed)!=len(expected) or total!=summary["totals"]["sample_rows"] or total!=sum(expected.values()):
        raise ValueError("Canonical totals differ")
    return total


def read_csv_check_issues(work, expected):
    positions = {(cell,cycle): rows for (cell,cycle,_),rows in expected.items()}
    issues = Counter()
    with (work/"rejected_records.csv").open(encoding="utf-8",newline="") as handle:
        for row in csv.DictReader(handle):
            sample = row["sample_index"]
            if sample:
                max_rows = positions.get((row["cell_id"],int(row["cycle_id"])),0)
                if not 0<=int(sample)<max_rows:
                    raise ValueError(f"Untraceable diagnostic location: {row}")
            issues[row["reason"]] += 1
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work",type=Path,required=True)
    args = parser.parse_args()
    work = args.work
    summary = json.loads((work/"p3_2_audit_summary.json").read_text(encoding="utf-8"))
    expected = check_inventory(work,summary)
    rows = check_canonical(work,expected,summary)
    issues = read_csv_check_issues(work,expected)
    with (work/"protocol_inventory.csv").open(encoding="utf-8",newline="") as handle:
        protocols = list(csv.DictReader(handle))
    cells = {record["cell_id"] for record in summary["cells"]}
    if len(protocols)!=len(cells) or {record["cell_id"] for record in protocols}!=cells:
        raise ValueError("Protocol inventory cell keys differ")
    evidence = {"status":"PASS","canonical_rows":rows,"unique_cycle_keys":len(expected),
                "protocol_cell_keys":len(cells),"candidate_pairs":summary["totals"]["ready_pairs"],
                "quality_ledger_rows":sum(issues.values()),"quality_ledger_reason_counts":dict(sorted(issues.items())),
                "output_sha256":{name:digest(work/name) for name in (
                    "canonical_cycles.parquet","cell_cycle_inventory.csv","protocol_inventory.csv",
                    "rejected_records.csv","p3_2_audit_summary.json")}}
    print(json.dumps(evidence,separators=(",",":")))


if __name__=="__main__":
    main()
