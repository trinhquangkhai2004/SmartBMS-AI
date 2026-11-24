"""Measure a trusted P3.6 RF load and one-session inference in a fresh process."""
import json
import platform
from time import perf_counter

import numpy as np
import psutil
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from scripts.p36_inputs import PRIMARY, ROOT, dump_json, require, sha
from scripts.train_p36 import MANIFESTS, dispersion, verify_load


def peak_resident(process):
    memory = process.memory_info()
    return memory.peak_wset if hasattr(memory, "peak_wset") else memory.rss


def latency(runner, rows):
    measures = []
    for row in rows:
        start = perf_counter()
        runner(row.reshape(1, -1))
        measures.append(1000 * (perf_counter() - start))
    return dict(sessions=len(measures), p50_ms=float(np.percentile(measures, 50)),
                p95_ms=float(np.percentile(measures, 95)), p99_ms=float(np.percentile(measures, 99)))


def main():
    results = json.loads((ROOT / MANIFESTS / "p3_6_training.json").read_bytes())
    model_meta = results["artifacts"]["rf"]
    process = psutil.Process()
    with threadpool_limits(limits=1):
        before = peak_resident(process)
        load_start = perf_counter()
        model = verify_load(ROOT / model_meta["path"], model_meta["sha256"])
        load_ms = 1000 * (perf_counter() - load_start)
        loaded = peak_resident(process)
        require(model.feature_importances_.size == len(PRIMARY), "RF model feature count mismatch")
        model.set_params(n_jobs=1)
        path = ROOT / "data/features/soh_feature_table.parquet"
        require(sha(path) == results["input_gate"]["feature_sha256"], "Frozen feature table changed")
        table = pq.read_table(path, columns=list(PRIMARY))
        positions = np.linspace(0, table.num_rows - 1, num=205, dtype=int)
        rows = np.ascontiguousarray(np.column_stack([table[n].to_numpy()[positions] for n in PRIMARY]),
                                    dtype=np.float32)
        del table
        for warm in rows[:5]:
            x = warm.reshape(1, -1)
            model.predict(x)
            dispersion(model, x)
        prediction = latency(model.predict, rows[5:])
        prediction_and_sigma = latency(lambda x: (model.predict(x), dispersion(model, x)), rows[5:])
        inferred = peak_resident(process)
    dump_json(ROOT / MANIFESTS / "p3_6_resource_measurement.json", dict(
        platform=platform.platform(), cpu=platform.processor(), logical_processors=psutil.cpu_count(),
        physical_ram_bytes=psutil.virtual_memory().total, python=platform.python_version(),
        runtime_kind="local Windows development CPU, F5 production runtime unmeasured",
        rf_threads=1, elapsed_load_ms=load_ms, load_includes_sha256=True,
        memory_method="Windows OS process peak working set" if platform.system() == "Windows"
        else "Process RSS sampled at measurement boundaries",
        baseline_peak_bytes=before, post_load_peak_bytes=loaded, post_infer_peak_bytes=inferred,
        inference_scope="200 sampled dev sessions, precomputed features, warmed in-process",
        peak_infer_includes_sample_input_preparation=True,
        predict=prediction, predict_plus_sigma=prediction_and_sigma, rf_sha256=model_meta["sha256"],
        rf_size_bytes=model_meta["bytes"]))
    print(f"RF {model_meta['bytes']} bytes, prediction + sigma p95 {prediction_and_sigma['p95_ms']:.3f} ms")


if __name__ == "__main__":
    main()
