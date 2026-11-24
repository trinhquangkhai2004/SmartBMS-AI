"""Read only four frozen DST/FUDS windows from the verified P2.2 delivery."""
import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np


P22_SHA256 = '101934ecc5a9bd89c8877a426a7346d1e89d3ffb752eef4ecdc365638ff8cd89'
RUN_IDS = (
    '11_05_2015_SP20-2_DST_50SOC', '11_05_2015_SP20-2_DST_80SOC',
    '11_06_2015_SP20-2_FUDS_80SOC', '11_09_2015_SP20-2_FUDS_50SOC',
)


@dataclass(frozen=True)
class DevelopmentRun:
    run_id: str
    role: str
    row: np.ndarray
    time_s: np.ndarray
    current_a: np.ndarray
    voltage_v: np.ndarray
    clock_event: np.ndarray
    prior_soc: float
    capacity_ah: float


def classify_clock(time_s, current_a, voltage_v, step_index, cycle_index):
    time, current, voltage, step, cycle = map(np.asarray, (time_s, current_a, voltage_v, step_index, cycle_index))
    if time.ndim != 1 or not time.size or any(a.shape != time.shape for a in (current, voltage, step, cycle)):
        raise ValueError("Clock fields must align")
    if not all(np.isfinite(a).all() for a in (time, current, voltage, step, cycle)):
        raise ValueError("Invalid clock or measurement")
    dt = np.diff(time)
    if np.any(dt < 0):
        raise ValueError("Source clock reversal")
    same = (current[1:] == current[:-1]) & (voltage[1:] == voltage[:-1])
    transition = (step[1:] != step[:-1]) | (cycle[1:] != cycle[:-1])
    repeated = dt == 0
    if np.any(repeated & ~same & ~transition):
        raise ValueError("Unresolved same-step clock conflict")
    events = np.full(time.size, 'MEASUREMENT', dtype='<U36')
    events[0] = 'FIRST'
    events[1:][repeated & same & ~transition] = 'DUPLICATE_OBSERVATION'
    events[1:][repeated & same & transition] = 'ZERO_DT_STEP_TRANSITION_SAME_SIGNAL'
    events[1:][repeated & ~same & transition] = 'ZERO_DT_NEW_TRANSITION'
    return events


def require(check, message):
    if not check:
        raise ValueError("P2.2 input integrity: " + message)


def load_development_runs(p22_zip, audit=None):
    """Yield a runtime-only record and a separate evaluation-only reference.

    Memorable names and manifest paths cannot expand the four-file allowlist.
    Only the declared signal, provenance, window, and evaluation columns are decoded.
    """
    import pyarrow.parquet as parquet

    p22_zip = Path(p22_zip)
    with p22_zip.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == P22_SHA256, 'archive SHA-256')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            prefix = 'phase2_soc/'
            manifest = json.loads(archive.read(prefix + 'manifests/p2_2_delivery_manifest.json'))
            files = {e['path']: e for e in manifest['files']}

            def read_member(path):
                data = archive.read(prefix + path)
                digest = hashlib.sha256(data).hexdigest()
                require(files[path]['sha256'] == digest and files[path]['bytes'] == len(data), path)
                if audit is not None:
                    audit(dict(member=path, sha256=digest, bytes=len(data)))
                return data

            gate = json.loads(read_member('results/p2_2/p2_2_gate_status.json'))
            require(gate['P2.1'] == gate['P2.2'] == 'PASS', 'upstream gate')
            capacity = json.loads(read_member('artifacts/capacity_metadata.json'))
            require(capacity['capacity_model_ah'] == capacity['capacity_ref_ah'] == 2.028344937765965,
                    'calibrated capacity')
            require(capacity['source_cell_id'] == 'SP20-2' and capacity['status'] == 'VALID', 'capacity source')
            ref_policy = read_member('configs/p2_2_reference_policy.yaml')
            read_member('reference_protocol_P2_2.md')
            read_member('configs/evaluation_protocol.yaml')
            ref_manifest = json.loads(read_member('manifests/p2_2_reference_manifest.json'))
            require(hashlib.sha256(ref_policy).hexdigest() == ref_manifest['policy_sha256'], 'reference policy SHA')
            references = {r['run_id']: r for r in ref_manifest['entries']}
            splits = {r['run_id']: r for r in json.loads(read_member('manifests/split_manifest.json'))['entries']}
            windows = {r['run_id']: r for r in csv.DictReader(io.StringIO(
                read_member('manifests/window_manifest.csv').decode('utf-8-sig')))}
            for run_id in RUN_IDS:
                ref, split, window = references[run_id], splits[run_id], windows[run_id]
                profile = run_id.split('_')[-2]
                role = {'DST': 'identification', 'FUDS': 'validation'}[profile]
                require(split['profile'] == profile and split['cell_id'] == 'SP20-2', 'frozen split')
                require(split['role'] == ref['role'] == window['role'] == role, 'run role')
                require(split['file_sha256'] == window['file_sha256'] == ref['source_sha256']
                        and split['archive_sha256'] == ref['raw_archive_sha256'], 'raw source SHA')
                require(ref['source_provenance']['resolved_cell_id'] == 'SP20-2', 'run cell')
                require(ref['generation_status'] == 'GENERATED' and ref['quality_status'] == 'VALID'
                        and ref['evaluation_only'] is True, 'reference unavailable')
                require(ref['policy_sha256'] == ref_manifest['policy_sha256']
                        and ref['capacity_ref_ah'] == capacity['capacity_ref_ah'], 'reference protocol')
                start, end = ref['window_start'], ref['window_end']
                require(int(window['dynamic_start_row']) == start and int(window['dynamic_end_row']) == end
                        and window['window_status'] == 'VERIFIED', 'window boundaries')
                prior = ref['historical_prior']
                require(prior['prior_kind'] == 'historical_prior' and prior['information_cutoff_row'] == start
                        and prior['same_prior_required_for_CC_EKF'] is True, 'prior availability')
                require(not ref['sampled_current_crosscheck']['unobserved_interval_rows'], 'sampled-current gap')
                path = f'data/processed/p2_2/reference/{run_id}.parquet'
                require(path == ref['output_path'] and ref['output_sha256'] == files[path]['sha256'], 'parquet identity')
                data = read_member(path)
                runtime_fields = ['time_s', 'current_a', 'voltage_v', 'step_index', 'cycle_index']
                provenance_fields = ['run_id', 'cell_id', 'phase']
                full = parquet.read_table(io.BytesIO(data), columns=runtime_fields + provenance_fields)
                require(0 <= start <= end < len(full), 'window bounds')
                dynamic = full.slice(start, end - start + 1)
                require(set(dynamic['run_id'].to_pylist()) == {run_id}
                        and set(dynamic['cell_id'].to_pylist()) == {'SP20-2'}, 'parquet source')
                require(np.array_equal(np.flatnonzero(np.array(full['phase'].to_pylist()) == 'DYNAMIC'),
                                       np.arange(start, end + 1)), 'dynamic row mask')
                t, i, v, step, cycle = (dynamic[key].to_numpy() for key in runtime_fields)
                require(t[0] == float(window['start_time_s']) and t[-1] == float(window['end_time_s']), 'window time')
                events = classify_clock(t, i, v, step, cycle)
                run = DevelopmentRun(run_id, role, np.arange(start, end + 1), t, i, v, events,
                                     prior['soc_fraction'], capacity['capacity_model_ah'])
                evaluation = parquet.read_table(io.BytesIO(data), columns=['soc_ref_fraction', 'evaluation_only',
                                                                           'reference_flag']).slice(start, len(t))
                labels = evaluation['soc_ref_fraction'].to_numpy()
                require(all(evaluation['evaluation_only'].to_pylist()) and np.isfinite(labels).all()
                        and set(evaluation['reference_flag'].to_pylist()) == {'VALID'}, 'evaluation coverage')
                yield run, labels
