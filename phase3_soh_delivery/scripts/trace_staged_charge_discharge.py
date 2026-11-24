"""Trace an observed charge followed by discharge using staged RT-Batt data only."""

import argparse
from collections import Counter
from itertools import groupby
import json
from pathlib import Path

import pyarrow.parquet as pq


def classify(status):
    text = (status or "").strip().casefold()
    if "discharge" in text:
        return "discharge"
    if "charge" in text:
        return "charge"
    if any(word in text for word in ("rest", "pause", "sleep")):
        return "rest"
    return "unclassified"


def read_initial_rows(parquet, max_cycles):
    with pq.ParquetFile(parquet) as traces:
        for batch in traces.iter_batches(batch_size=8192):
            for row in batch.to_pylist():
                if row["cycle_source_order"] >= max_cycles:
                    return
                yield row


def segment(rows):
    time = [row["time_s_raw"] for row in rows]
    current = [row["current_ma_raw"] for row in rows]
    pairs = [(a, b) for a, b in zip(time, time[1:]) if a is not None and b is not None]
    return {
        "rows": len(rows),
        "raw_status_values": dict(Counter(row["raw_status"] for row in rows)),
        "first": rows[0],
        "last": rows[-1],
        "time_duplicates": sum(a == b for a, b in pairs),
        "time_reversals": sum(a > b for a, b in pairs),
        "time_missing": time.count(None),
        "signed_current_integral_mah": (
            sum((first + second) * 0.5 * (end - start) for first, second, (start, end) in zip(current, current[1:], pairs)) / 3600
            if len(pairs) == len(time) - 1 and None not in current and all(start <= end for start, end in pairs)
            else None
        ),
        "current_sign_counts": {
            "positive": sum(value is not None and value > 0 for value in current),
            "negative": sum(value is not None and value < 0 for value in current),
            "zero": current.count(0),
            "missing": current.count(None),
        },
    }


def segment_key(row):
    return row["cycle_source_order"], row["cycle_id"], classify(row["raw_status"])


def charge_discharge_example(rows, dq_by_cycle):
    runs = [(key, segment(list(group))) for key, group in groupby(rows, segment_key)]
    for index, (key, charge) in enumerate(runs):
        if key[2] != "charge" or charge["rows"] < 2:
            continue
        for offset, (following, discharge) in enumerate(runs[index + 1:], start=index + 1):
            classification = following[2]
            if classification == "rest":
                continue
            if classification == "discharge" and discharge["rows"] > 1 and dq_by_cycle.get(following[1]) is not None:
                intervening = [run for _, run in runs[index + 1:offset]]
                return {
                    "charge": charge,
                    "discharge": discharge,
                    "intervening": intervening,
                    "same_raw_cycle": key[1] == following[1],
                    "discharge_cycle_dq_raw": dq_by_cycle[following[1]],
                    "nearby_runs": [
                        {
                            "cycle_id": run_key[1], "cycle_source_order": run_key[0], "phase": run_key[2],
                            "statuses": run["raw_status_values"], "rows": run["rows"],
                            "first_sample": run["first"]["sample_index"], "last_sample": run["last"]["sample_index"],
                        }
                        for run_key, run in runs[max(0, index - 2):offset + 3]
                    ],
                }
            break
    counts = Counter(row["raw_status"] for row in rows)
    raise ValueError(f"No explicitly labeled charge-discharge pair with dq in first cycles: {dict(counts)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--max-cycles", type=int, default=16)
    args = parser.parse_args()
    if args.max_cycles < 1:
        parser.error("--max-cycles must be positive")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    rows = list(read_initial_rows(args.traces, args.max_cycles))
    if not rows or {row["cell_id"] for row in rows} != {summary["cell_id"]}:
        raise ValueError("Trace rows and summary must refer to the same cell")
    positions = [(row["cycle_source_order"], row["sample_index"]) for row in rows]
    if any(a >= b for a, b in zip(positions, positions[1:])):
        raise ValueError("Staging sample order is not strictly increasing")
    dq_by_cycle = {record["cycle_id"]: record["value"] for record in summary["dq_by_cycle_raw"]}
    example = charge_discharge_example(rows, dq_by_cycle)
    payload = {
        "source_member": summary["source_member"],
        "cell_id": summary["cell_id"],
        "scanned_rows": len(rows),
        "scanned_cycles": len({row["cycle_id"] for row in rows}),
        "observed_status_values": dict(Counter(row["raw_status"] for row in rows)),
        **example,
    }
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
