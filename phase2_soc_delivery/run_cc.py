"""Reproduce P2.4 on the four development windows of the verified P2.2 ZIP."""
import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np

from src.cc import coulomb_count, score_populations
from src.development_data import P22_SHA256, RUN_IDS, load_development_runs


ROOT = Path(__file__).resolve().parent


def run_baseline(p22_zip):
    from src.governance import require_conditional_approval

    require_conditional_approval(ROOT, 'P2.4')
    destination = ROOT / 'results' / 'p24'
    destination.mkdir(exist_ok=True, parents=True)
    metrics = {}
    accesses = []
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary)
        tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_cc.py', '-v'],
                               cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        (stage / 'tests.log').write_bytes(tests.stdout)
        trajectories = stage / 'trajectories'
        trajectories.mkdir()
        for run, reference in load_development_runs(p22_zip, audit=accesses.append):
            tic = perf_counter()
            estimated = coulomb_count(run.time_s, run.current_a, run.capacity_ah, run.prior_soc)
            elapsed_s = perf_counter() - tic
            population = score_populations(estimated, reference, run.voltage_v)
            event_counts = dict(Counter(run.clock_event.tolist()))
            redundant = np.isin(run.clock_event, ['DUPLICATE_OBSERVATION', 'ZERO_DT_STEP_TRANSITION_SAME_SIGNAL'])
            flags = run.voltage_v < 3.2976
            path = trajectories / (run.run_id + '.csv')
            with path.open('w', newline='', encoding='utf-8') as output:
                writer = csv.writer(output)
                writer.writerow(['source_row_0based', 'time_s', 'current_a', 'voltage_v', 'clock_event',
                                 'soc_cc_fraction', 'soc_ref_fraction_evaluation_only', 'error_pp',
                                 'LOW_SOC_MODEL_UNCERTAIN'])
                writer.writerows(zip(run.row, run.time_s, run.current_a, run.voltage_v, run.clock_event,
                                     estimated, reference, 100 * (estimated - reference), flags.astype(int)))
            with path.open(encoding='utf-8', newline='') as input_file:
                check = list(csv.DictReader(input_file))
            if len(check) != len(run.row) or int(check[0]['source_row_0based']) != run.row[0] or int(
                    check[-1]['source_row_0based']) != run.row[-1]:
                raise ValueError('Trajectory export window changed')
            restored = np.array([float(row['soc_cc_fraction']) for row in check])
            np.testing.assert_array_equal(restored, estimated)
            if population['FULL_DYNAMIC']['numerator'] != len(check):
                raise ValueError('Incomplete nominal coverage')
            metrics[run.run_id] = dict(
                role=run.role, start_row=int(run.row[0]), end_row=int(run.row[-1]),
                raw_rows=len(check), merged_duplicate_metadata_rows=int(redundant.sum()),
                effective_events=int((~redundant).sum()), covered_effective_events=int((~redundant).sum()),
                voltage_measurement_updates_used=0, integrated_positive_dt_intervals=int((np.diff(run.time_s)>0).sum()),
                clock_event_counts=event_counts, prior_soc_fraction=run.prior_soc,
                prior_source='historical_preconditioning_through_dynamic_start', model_capacity_ah=run.capacity_ah,
                final_soc_fraction=float(estimated[-1]), reset_count=0, projection_count=0, invalid_count=0,
                out_of_range_count=int(((estimated < 0) | (estimated > 1)).sum()),
                estimator_wall_time_s=elapsed_s, trajectory_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                **population)
        if tuple(metrics) != RUN_IDS:
            raise ValueError('Incomplete development runs')
        report = dict(milestone='P2.4', gate='PASS', scenario='nominal_development', ER4='NOT_EVALUATED',
                      test_exposed=False, p22_delivery_sha256=P22_SHA256,
                      reference_kind='Arbin capacity-derived, same current source',
                      integration='Previous discharge-positive current; left ZOH, dt=0 adds zero',
                      warning='Measured voltage < 3.2976 V; telemetry only',
                      percentage_point_error='100 * (estimated fraction - reference fraction)',
                      runs=metrics, python=platform.python_version(),
                      dependencies={p: version(p) for p in ('numpy', 'pyarrow')},
                      completed_utc=datetime.now(timezone.utc).isoformat())
        (stage / 'metrics.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        (stage / 'source_access.json').write_text(json.dumps(
            dict(archive_sha256=P22_SHA256, members_read=accesses,
                 heldout_trajectory_reads=0, runtime_fields=['time_s', 'current_a', 'prior_soc', 'capacity_ah']),
            indent=2) + '\n', encoding='utf-8')
        for path in sorted(stage.rglob('*')):
            if path.is_file() and path.name != 'metrics.json':
                target = destination / path.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
        os.replace(stage / 'metrics.json', destination / 'metrics.json')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--p22-zip', required=True, type=Path)
    args = parser.parse_args()
    report = run_baseline(args.p22_zip)
    for run_id, result in report['runs'].items():
        full = result['FULL_DYNAMIC']
        print(f"{run_id}: {full['numerator']}/{full['denominator']} rows, max {full['MAX_abs_pp']:.6f} pp")
