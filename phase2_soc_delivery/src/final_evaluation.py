"""Frozen reference reconstruction and one-exposure evidence for P2.6."""
import csv
import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np

from .development_data import DevelopmentRun, P22_SHA256, classify_clock


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def record_once(path, data):
    """Exclusive create followed by fsync. A partial claim permanently marks exposure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as out:
        json.dump(data, out, indent=2, allow_nan=False)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())


def now():
    return datetime.now(timezone.utc).isoformat()


def environment():
    packages = ('numpy', 'pandas', 'pyarrow', 'openpyxl')
    versions = {}
    for name in packages:
        distribution = metadata.distribution(name)
        record = distribution.read_text('RECORD')
        versions[name] = dict(version=distribution.version,
                              record_sha256=hashlib.sha256(record.encode()).hexdigest() if record else None)
    return dict(python=sys.version, executable_sha256=sha(sys.executable), packages=versions)


def inventory(p22_zip, protocol):
    if sha(p22_zip) != P22_SHA256:
        raise ValueError('Unexpected P2.2 delivery SHA-256')
    with zipfile.ZipFile(p22_zip) as z:
        def read(path):
            return z.read('phase2_soc/' + path)
        source = {r['run_id']: r for r in json.loads(read('manifests/split_manifest.json'))['entries']}
        windows = {r['run_id']: r for r in csv.DictReader(io.StringIO(
            read('manifests/window_manifest.csv').decode('utf-8-sig')))}
        raw = {e['sha256']: e for e in json.loads(read('manifests/download_log.json'))}
        deferred = {r['run_id']: r for r in json.loads(read('manifests/p2_2_reference_manifest.json'))['entries']}
        if set(protocol['run_order']) != {k for k, e in source.items() if e['role'] == 'held_out_test'}:
            raise ValueError('Final run IDs disagree with verified split')
        result = {}
        for run_id in protocol['run_order']:
            split, window, ref = source[run_id], windows[run_id], deferred[run_id]
            archive = raw[split['archive_sha256']]
            if not (split['profile'] in {'US06', 'BJDST'} and split['role'] == window['role'] == 'held_out_test'
                    and split['cell_id'] == 'SP20-2' and window['window_status'] == 'VERIFIED'
                    and split['file_sha256'] == window['file_sha256'] == ref['source_sha256']
                    and ref['generation_status'] == 'DEFERRED_TO_P2_6'):
                raise ValueError('Unverified held-out metadata')
            result[run_id] = dict(split=split, window=window, archive=archive['archive'],
                                  archive_sha256=archive['sha256'])
    return result


def reference_and_signals(p22_zip, raw_path, entry, capacity_ah):
    """Called only after the durable per-run claim. Reuse exact P2.2 parser and algorithms."""
    source_root = str(Path(p22_zip).resolve() / 'phase2_soc' / 'src')
    sys.path.insert(0, source_root)
    try:
        from soc.data import normalize, read_archive, resolve_provenance
        from soc.capacity import operational_full_anchor
        from soc.reference import build_reference
    finally:
        sys.path.pop(0)
    if any(not Path(fn.__code__.co_filename).is_relative_to(source_root)
           for fn in (normalize, read_archive, resolve_provenance, operational_full_anchor, build_reference)):
        raise ValueError('P2.2 reference implementation provenance mismatch')
    split, window = entry['split'], entry['window']
    with zipfile.ZipFile(raw_path) as source:
        payload = source.read(split['file'])
    if hashlib.sha256(payload).hexdigest() != split['file_sha256']:
        raise ValueError('Held-out source workbook identity mismatch')
    # P2.2 parses complete archives. Expose only this already claimed member to it.
    isolated = io.BytesIO()
    with zipfile.ZipFile(isolated, 'w') as z:
        z.writestr(split['file'], payload)
    isolated.seek(0)
    book, = read_archive(isolated)
    provenance = resolve_provenance(book['file'], book['info'],
                                    [s['sheet'] for s in book['sheets'] if s['kind'] == 'OBSERVATION'])
    if provenance['resolved_cell_id'] != 'SP20-2':
        raise ValueError('Cell provenance unresolved')
    frame, sign = normalize(book['frame'], book['file'], 'SP20-2')
    if sign['multiplier'] != -1:
        raise ValueError('Raw sign contradicts frozen source convention')
    start, end = int(window['dynamic_start_row']), int(window['dynamic_end_row'])
    anchor = operational_full_anchor(frame, start)
    output, report = build_reference(frame, anchor_row=anchor['row'], dynamic_start=start, dynamic_end=end,
                                     capacity_ref_ah=capacity_ah, anchor_fraction=1., anchor_kind='historical_prior')
    dynamic = output.iloc[start:end+1]
    t, i, v, step, cycle = (dynamic[k].to_numpy() for k in
                            ('time_s', 'current_a', 'voltage_v', 'step_index', 'cycle_index'))
    if not (len(t) == end - start + 1 and t[0] == float(window['start_time_s'])
            and t[-1] == float(window['end_time_s']) and (dynamic.phase == 'DYNAMIC').all()):
        raise ValueError('Frozen dynamic window mismatch')
    prior = report['historical_prior']
    if prior['soc_fraction'] is None or prior['information_cutoff_row'] != start or not 0 <= prior['soc_fraction'] <= 1:
        raise ValueError('Historical prior unavailable at the declared dynamic boundary')
    run = DevelopmentRun(split['run_id'], split['role'], np.arange(start, end+1), t, i, v,
                         classify_clock(t, i, v, step, cycle), prior['soc_fraction'], capacity_ah)
    details = dict(anchor=anchor, prior=prior, quality=report['quality_status'], reference_flags=report['flags'],
                   unresolved_gaps=report['unresolved_gaps'], uncertainty=report['uncertainty'],
                   counter_roundoff_rows=report['counter_roundoff_rows'], source=split,
                   source_provenance=provenance, reference_kind=report['reference_kind'])
    return run, dynamic.soc_ref_fraction.to_numpy(), details


def run_verdict(metrics, trusted_reference, valid_events, total_events, threshold_pp=10.0):
    full = metrics['FULL_DYNAMIC']
    if not trusted_reference or total_events == 0:
        return 'ER4_NOT_ASSESSABLE'
    if full['MAX_abs_pp'] is not None and full['MAX_abs_pp'] > threshold_pp:
        return 'ER4_FAIL'
    if full['numerator'] != full['denominator'] or valid_events != total_events or full['MAX_abs_pp'] is None:
        return 'ER4_NOT_ASSESSABLE'
    return 'ER4_PASS'
