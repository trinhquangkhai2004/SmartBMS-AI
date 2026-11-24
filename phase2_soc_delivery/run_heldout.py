"""Register a frozen P2.6 experiment, then evaluate each held-out workbook once."""
import argparse
import hashlib
import io
import json
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from run_ekf import decode_candidate, diagnostics, export_trajectory, inputs_for_scenario, replay
from src.development_data import P22_SHA256
from src.ekf import load_frozen_calibration
from src.final_evaluation import environment, inventory, load_json, now, record_once, reference_and_signals, run_verdict, sha


ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results/p26'
PROTOCOL = 'configs/p26_final_protocol.json'
P25_CONFIG = 'results/p25/ekf_config.json'
ECM = 'artifacts/ecm_params.json'
LOCK = OUT / 'locked_protocol.json'
PINNED = (PROTOCOL, P25_CONFIG, ECM, 'run_cc.py', 'run_ekf.py', 'run_heldout.py',
          'src/governance.py', 'src/development_data.py', 'src/cc.py', 'src/ekf.py',
          'src/final_evaluation.py', 'configs/g10_conditional_run_policy.yaml', 'configs/p25_development_search.json',
          'approvals/conditional_approval_record.json', 'approvals/heldout_approval.json', 'artifacts/ocv_model.json',
          'artifacts/capacity_metadata.json', 'results/p24/metrics.json', 'results/p25/metrics.json',
          'results/p25/candidate_selection.json', 'results/p25/source_access.json')


def prerequisites(p22_zip):
    approval = load_json(ROOT / 'approvals/heldout_approval.json')
    protocol = load_json(ROOT / PROTOCOL)
    if not (approval['decision'] == 'APPROVED_ONCE_AFTER_LOCK' and approval['scope'] == 'P2.6'
            and approval['coverage_required'] == protocol['coverage_required'] == 1.0
            and approval['max_abs_error_pp'] == protocol['max_abs_error_pp'] == 10.0
            and approval['scientific_release'] is False and approval['full_window'] is True
            and approval['per_run'] is True and approval['approval_source']):
        raise PermissionError('Final acceptance/exposure authorization missing')
    p24, p25 = (load_json(ROOT / f'results/p{n}/metrics.json') for n in (24, 25))
    if not (p24['gate'] == p25['gate'] == 'PASS' and p24['test_exposed'] is p25['test_exposed'] is False
            and p24['p22_delivery_sha256'] == P22_SHA256 and p25['p24_metrics_sha256'] == sha(ROOT/'results/p24/metrics.json')):
        raise PermissionError('Linked development PASS evidence required')
    config = load_json(ROOT / P25_CONFIG)
    doc = load_json(ROOT / ECM)
    approval_dev = load_json(ROOT / 'approvals/conditional_approval_record.json')
    if not (config['selected'] == p25['selected'] and config['scientific_release'] is False
            and config['warning_threshold_v'] == 3.2976 and config['plan_sha256'] == sha(ROOT/'configs/p25_development_search.json')
            and config['driver_sha256'] == sha(ROOT/'run_ekf.py') and config['runtime_sha256'] == sha(ROOT/'src/ekf.py')
            and config['candidate_ecm_sha256'] == approval_dev['ecm_sha256'] == sha(ROOT / ECM)
            and doc['lock_status'] == 'NEEDS_REVIEW_NOT_RELEASED'):
        raise ValueError('Model, code or configuration differs from P2.5')
    ocv, capacity = load_frozen_calibration(ROOT/'artifacts/ocv_model.json', ROOT/'artifacts/capacity_metadata.json')
    model = decode_candidate(doc, capacity)
    sources = inventory(p22_zip, protocol)
    snapshot = dict(files={p: sha(ROOT / p) for p in PINNED}, environment=environment(),
                    p22_sha256=P22_SHA256, sources=sources, scientific_release=False)
    return snapshot, protocol, config, ocv, model


def register(p22_zip):
    snapshot, *_ = prerequisites(p22_zip)
    if LOCK.exists():
        if load_json(LOCK)['snapshot'] != snapshot:
            raise PermissionError('A different P2.6 snapshot has already been registered')
    else:
        if (OUT / 'claims').exists() or (OUT / 'opened.json').exists():
            raise PermissionError('Existing exposure evidence forbids a new registration')
        record_once(LOCK, dict(registered_utc=now(), snapshot=snapshot))
    return sha(LOCK)


def evaluate_run(index, run, reference, ref_meta, config, ocv, model, plan):
    scenarios = {}
    for name, perturbation in plan['scenarios'].items():
        seed = int(config['seed']) + index
        inputs = inputs_for_scenario(run, perturbation, seed=seed)
        if inputs is None:
            scenarios[name] = dict(status='INAPPLICABLE_PRIOR_OUTSIDE_PHYSICAL_RANGE')
            continue
        prior, current, voltage = inputs
        if not ocv.z_min <= prior <= ocv.z_max:
            scenarios[name] = dict(status='INAPPLICABLE_PRIOR_OUTSIDE_OCV_DOMAIN')
            continue
        tic = perf_counter()
        vrc = ocv.evaluate(prior)[0] - model.r0_ohm * float(current[0]) - float(voltage[0])
        z, cc, rows = replay(run, prior, current, voltage, config['selected'], model, ocv,
                             config['max_gap_active_s'], config['approval_record_id'], config['current_range_a'],
                             vrc0=vrc, first_voltage_used_for_prior=True)
        elapsed = perf_counter() - tic
        evidence = diagnostics(run, reference, z, cc, rows, voltage, config['max_gap_active_s'], elapsed)
        evidence.update(status='EXECUTED', seed=seed, prior_soc_fraction=prior, initial_vrc_v=vrc,
                        initial_voltage_corrections=int(rows[0]['corrected']))
        if rows[0]['corrected']:
            raise ValueError('Initialization voltage was corrected twice')
        if name == 'nominal':
            path = OUT / 'trajectories' / (run.run_id + '.csv.gz')
            export_trajectory(path, run, reference, current, voltage, z, cc, rows)
            evidence['trajectory_sha256'] = sha(path)
        scenarios[name] = evidence
    nominal = scenarios['nominal']
    verdict = 'ER4_NOT_ASSESSABLE'
    if nominal['status'] == 'EXECUTED':
        verdict = run_verdict(nominal['EKF'], ref_meta['quality'] == 'VALID',
                              nominal['covered_effective_events'], nominal['effective_event_count'])
    return dict(run_id=run.run_id, role=run.role, source_start_row=int(run.row[0]),
                source_end_row=int(run.row[-1]), test_exposed=True, ER4=verdict,
                reference=ref_meta, scenarios=scenarios)


def evaluate(p22_zip, raw_dir, expected_lock):
    if not LOCK.is_file() or sha(LOCK) != expected_lock:
        raise PermissionError('Supply the SHA-256 of the previously registered P2.6 lock')
    snapshot, protocol, config, ocv, model = prerequisites(p22_zip)
    if snapshot != load_json(LOCK)['snapshot']:
        raise PermissionError('Environment or artifact differs from the registered lock')
    plan = load_json(ROOT/'configs/p25_development_search.json')
    sources = snapshot['sources']
    paths = {row['archive']: Path(raw_dir) / row['archive'] for row in sources.values()}
    for row in sources.values():
        path = paths[row['archive']]
        if not path.is_file():
            raise FileNotFoundError(f'Provide the approved raw archive {path.name}')
    # Hash verification reads opaque archive bytes only. No workbook is opened before its claim.
    for name, path in paths.items():
        identity = next(row['archive_sha256'] for row in sources.values() if row['archive'] == name)
        if sha(path) != identity:
            raise ValueError(f'Frozen archive SHA-256 differs: {name}')
    stamp = OUT/'opened.json'
    try:
        record_once(stamp, dict(lock_sha256=expected_lock, time_utc=now(), policy='per-workbook durable claims'))
    except FileExistsError:
        if load_json(stamp)['lock_sha256'] != expected_lock:
            raise PermissionError('Exposure record is bound to a different lock')
    results = {}
    for index, run_id in enumerate(protocol['run_order']):
        entry = sources[run_id]
        claim, receipt = OUT/'claims'/(run_id+'.json'), OUT/'runs'/(run_id+'.json')
        try:
            record_once(claim, dict(run_id=run_id, lock_sha256=expected_lock, source_sha256=entry['split']['file_sha256'],
                                    time_utc=now(), test_exposed=True, action='open_workbook_once'))
        except FileExistsError:
            if not receipt.is_file():
                results[run_id] = dict(ER4='ER4_NOT_ASSESSABLE', reason='Prior claim without a completed receipt')
                continue
            previous = load_json(receipt)
            if previous['lock_sha256'] != expected_lock or previous['run_id'] != run_id:
                raise PermissionError('Previously persisted evidence identity differs')
            results[run_id] = dict(ER4=previous['ER4'], receipt_sha256=sha(receipt))
            continue
        try:
            run, reference, ref_meta = reference_and_signals(p22_zip, paths[entry['archive']], entry, model.capacity_ah)
            result = evaluate_run(index, run, reference, ref_meta, config, ocv, model, plan)
        except Exception as exc:
            window = entry['window']
            result = dict(run_id=run_id, ER4='ER4_NOT_ASSESSABLE', test_exposed=True,
                          expected_raw_rows=int(window['dynamic_end_row'])-int(window['dynamic_start_row'])+1,
                          reason=f'{type(exc).__name__}: {exc}')
        result.update(lock_sha256=expected_lock, completed_utc=now())
        record_once(receipt, result)
        results[run_id] = dict(ER4=result['ER4'], receipt_sha256=sha(receipt))
    states = [r['ER4'] for r in results.values()]
    verdict = ('ER4_FAIL' if 'ER4_FAIL' in states else
               'ER4_PASS' if len(states) == 4 and all(s == 'ER4_PASS' for s in states) else 'ER4_NOT_ASSESSABLE')
    summary = dict(ER4=verdict, test_exposed=True, scientific_release=False, lock_sha256=expected_lock, runs=results,
                   next_action='P2.7 handoff' if verdict == 'ER4_PASS' else 'Return to P2.3 under change control')
    # Partial/in-flight claims cannot seal a premature aggregate result.
    if all('receipt_sha256' in r for r in results.values()):
        receipt = OUT / 'metrics.json'
        try:
            record_once(receipt, summary)
        except FileExistsError:
            if load_json(receipt) != summary:
                raise PermissionError('Final summary differs from sealed evidence')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    for name in ('register', 'evaluate'):
        cmd = subs.add_parser(name)
        cmd.add_argument('--p22-zip', type=Path, required=True)
        if name == 'evaluate':
            cmd.add_argument('--raw-dir', type=Path, required=True)
            cmd.add_argument('--lock-sha256', required=True)
    args = parser.parse_args()
    if args.action == 'register':
        print(register(args.p22_zip))
    else:
        print(json.dumps(evaluate(args.p22_zip, args.raw_dir, args.lock_sha256), indent=2))
