from copyreg import __newobj__
import io
import json
from pathlib import Path
import pickle
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.core.internals.managers import BlockManager
import pyarrow.parquet as pq

from secure_source_converter import (
    parse_member,
    read_source_object,
    resolve_expected_globals,
    verify_official_source,
    write_cell,
)


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.cell_id = "1-1"
        self.source = "our_data/1-1.pkl"

    def trace(self):
        return pd.DataFrame(
            {
                "Status": ["charge", "discharge"],
                "Time (s)": [31.0, 6.0],
                "Voltage (V)": [3.6, 3.24],
                "Current (mA)": [1000.0, -1200.0],
                "Capacity (mAh)": [np.nan, 42.0],
                "Other": [11, 12],
            }
        )

    def test_all_upstream_globals_resolve_inside_image(self):
        resolved = resolve_expected_globals()
        self.assertEqual(len(resolved), 10)
        self.assertIs(resolved["builtins", "slice"], slice)
        self.assertIs(resolved["pandas.core.frame", "DataFrame"], pd.DataFrame)
        self.assertIs(resolved["numpy", "ndarray"], np.ndarray)

    def test_restricted_read_round_trips_known_types(self):
        value = {"capacity": np.float64(1.08), "rows": np.array([1, 2]), "segment": slice(0, 1)}
        decoded = read_source_object(io.BytesIO(pickle.dumps(value, protocol=4)), resolve_expected_globals())
        self.assertEqual(decoded["capacity"], value["capacity"])
        np.testing.assert_array_equal(decoded["rows"], value["rows"])
        self.assertEqual(decoded["segment"], value["segment"])

    def test_restricted_read_refuses_unlisted_benign_global(self):
        emitted = pickle.dumps(complex(1, 2), protocol=4)
        with self.assertRaisesRegex(pickle.UnpicklingError, "builtins.complex"):
            read_source_object(io.BytesIO(emitted), resolve_expected_globals())

    def test_restricted_read_rejects_bytes_after_stop(self):
        payload = pickle.dumps({}, protocol=4) + b"extra"
        with self.assertRaisesRegex(ValueError, "trailing"):
            read_source_object(io.BytesIO(payload), resolve_expected_globals())

    def test_source_identity_failure_on_other_file(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "our_data.zip"
            source.write_bytes(b"small non-source fixture")
            with self.assertRaisesRegex(ValueError, "official"):
                verify_official_source(source)

    def test_staging_round_trip_preserves_cycle_order_and_raw_values(self):
        data = {self.cell_id: {"data": {4: self.trace(), 2: self.trace()}, "dq": {4: 1.08}, "rul": {4: 10}}}
        cycles, summary = parse_member(data, self.cell_id)
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)
            record = write_cell(out, self.source, self.cell_id, cycles, summary)
            traces = pq.read_table(out / record["trace"]["path"])
            self.assertEqual(traces["cycle_id"].to_pylist(), [4, 4, 2, 2])
            self.assertEqual(traces["cycle_source_order"].to_pylist(), [0, 0, 1, 1])
            self.assertEqual(traces["sample_index"].to_pylist(), [0, 1, 0, 1])
            self.assertEqual(traces["time_s_raw"].to_pylist(), [31, 6, 31, 6])
            self.assertEqual(traces["current_ma_raw"].to_pylist(), [1000, -1200, 1000, -1200])
            self.assertEqual(traces["capacity_mah_raw"].to_pylist(), [None, 42, None, 42])
            exported = json.loads((out / record["summary"]["path"]).read_text())
            self.assertEqual(exported["dq_by_cycle_raw"], [{"cycle_id": 4, "value": 1.08}])
            self.assertEqual(record["sample_rows"], 4)
            self.assertEqual(record["cycle_count"], 2)
            self.assertEqual(record["source_member"], self.source)
            self.assertEqual(record["extra_trace_columns"], ["Other"])

    def test_staging_reports_missing_required_columns(self):
        cycles = {4: self.trace().drop(columns="Status")}
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "Status"):
                write_cell(Path(root), self.source, self.cell_id, cycles, {})

    def test_legacy_pandas_dataframe_path_with_synthetic_data(self):
        class LegacyBlockFixturePickler(pickle.Pickler):
            def reducer_override(self, obj):
                if not isinstance(obj, BlockManager):
                    return NotImplemented
                axes = list(obj.axes)
                blocks = [{"values": block.values, "mgr_locs": block.mgr_locs.indexer} for block in obj.blocks]
                legacy_state = (axes, [], [], {"0.14.1": {"axes": axes, "blocks": blocks}})
                return __newobj__, (type(obj),), legacy_state

        frame = self.trace()
        member = {self.cell_id: {"data": {1: frame}, "dq": {1: np.float64(1.08)}}}
        stream = io.BytesIO()
        LegacyBlockFixturePickler(stream, protocol=4).dump(member)
        stream.seek(0)
        decoded = read_source_object(stream, resolve_expected_globals())
        cycles, summary = parse_member(decoded, self.cell_id)
        pd.testing.assert_frame_equal(cycles[1], frame)
        with tempfile.TemporaryDirectory() as root:
            record = write_cell(Path(root), self.source, self.cell_id, cycles, summary)
            self.assertEqual(record["sample_rows"], 2)
            self.assertEqual(record["dq_records"], 1)

    def test_mismatched_cell_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cell key"):
            parse_member({"1-2": {"data": {4: self.trace()}}}, self.cell_id)


if __name__ == "__main__":
    unittest.main()
