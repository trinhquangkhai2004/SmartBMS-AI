"""Verify saved development observations, independent of the runtime loop."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.cc import score_populations


def read(path):
    return json.loads(path.read_bytes())


def verify():
    folder = ROOT/"results/p25"
    result = read(folder/"metrics.json")
    p24 = read(ROOT/"results/p24/metrics.json")
    config = read(folder/"ekf_config.json")
    registration = read(folder/"development_registration.json")
    plan = read(ROOT/"configs/p25_development_search.json")
    assert result["gate"] == "PASS" and result["test_exposed"] is False
    assert config["selected"] in registration["candidate_grid"]
    assert len(registration["candidate_grid"]) == len(read(folder/"candidate_selection.json"))
    for name, path in (("runtime_sha256",ROOT/"src/ekf.py"),("driver_sha256",ROOT/"run_ekf.py"),
                       ("plan_sha256",ROOT/"configs/p25_development_search.json")):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == config[name] == registration[name]
    nfiles = nrows = nominal = na = 0
    for run,scenarios in result["runs"].items():
        assert set(scenarios) == set(plan["scenarios"])
        for name,metrics in scenarios.items():
            if metrics["status"] == "INAPPLICABLE":
                initial = p24["runs"][run]["prior_soc_fraction"] + plan["scenarios"][name]["prior_offset_pp"]/100
                assert not 0 <= initial <= 1
                na += 1
                continue
            path = folder/metrics["trajectory"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == metrics["trajectory_sha256"]
            with gzip.open(path,"rt",encoding="utf-8",newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == metrics["raw_rows"] == p24["runs"][run]["raw_rows"]
            start = p24["runs"][run]["start_row"]
            assert all(int(row["source_row_0based"]) == start+j for j,row in enumerate(rows))
            voltage = np.array([float(row["runtime_voltage_v"]) for row in rows])
            flags = np.array([row["LOW_SOC_MODEL_UNCERTAIN"] == "True" for row in rows])
            assert np.array_equal(flags,voltage<3.2976)
            ref = np.array([float(row["soc_ref_fraction_evaluation_only"]) for row in rows])
            for model,key in (("CC","soc_cc_fraction"),("EKF","soc_ekf_fraction")):
                z = np.array([float(row[key]) if row[key] else np.nan for row in rows])
                measured = score_populations(z,ref,voltage)
                assert measured == metrics[model]
            assert sum(row["corrected"] == "True" for row in rows) == metrics["voltage_corrections"]
            nfiles += 1
            nrows += len(rows)
            nominal += len(rows) if name == "nominal" else 0
    notebook = read(ROOT/"notebooks/05_ekf.ipynb")
    cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert [c["execution_count"] for c in cells] == list(range(1,len(cells)+1))
    assert all(c["outputs"] and all(o["output_type"] != "error" for o in c["outputs"]) for c in cells)
    summary = dict(status="PASS",trajectory_sha256_checks=nfiles,trajectory_rows_rechecked=nrows,
                   nominal_rows_rechecked=nominal, inapplicable_scenarios_rechecked=na,
                   notebook_code_cells_executed=len(cells),frozen_source_hashes_verified=True,
                   heldout_files_read=0)
    (folder/"verification.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    verify()
