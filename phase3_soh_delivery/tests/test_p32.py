import json
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from audit_rt_batt_cycles import (
    PHASE_DISCHARGE, annotate_pairs, audit_cycle, canonical_table,
    check_reference_cycle, index_dq, iter_cycles,
)


CHARGE = "Constant current charge"
DISCHARGE = "Constant current discharge_0"


def trace(cell, cycle, ordinal, statuses, times, currents, voltages=None, capacities=None):
    n = len(statuses)
    return pa.table({
        "cell_id": [cell] * n, "cycle_id": [cycle] * n,
        "cycle_source_order": [ordinal] * n, "sample_index": list(range(n)),
        "raw_status": statuses, "time_s_raw": pa.array(times, type=pa.float64()),
        "voltage_v_raw": pa.array(voltages or [3.5] * n, type=pa.float64()),
        "current_ma_raw": pa.array(currents, type=pa.float64()),
        "capacity_mah_raw": pa.array(capacities or list(range(n)), type=pa.float64()),
    })


class ParserTests(unittest.TestCase):
    def record(self, statuses, times, currents, dq=None, cell="a", cycle=1, order=0, **fields):
        return audit_cycle(trace(cell, cycle, order, statuses, times, currents, **fields), dq)[0]

    def test_batch_boundary_order_and_roundtrip(self):
        with TemporaryDirectory() as folder:
            file = Path(folder) / "fixture.parquet"
            tables = [
                trace("a", 2, 0, [CHARGE, CHARGE, DISCHARGE, DISCHARGE], [0, 1, 2, 3], [1, 1, -1, -1]),
                trace("a", 1, 1, [CHARGE, CHARGE], [0, 1], [1, 1]),
            ]
            pq.write_table(pa.concat_tables(tables), file, row_group_size=3)
            parsed = list(iter_cycles(file, batch_size=2))
            self.assertEqual([x.column("cycle_id")[0].as_py() for x in parsed], [2, 1])
            self.assertEqual([x.num_rows for x in parsed], [4, 2])
            rec, phases = audit_cycle(parsed[0], None)
            canon = canonical_table(parsed[0], rec, phases, "sha", "profile")
            output = Path(folder) / "canonical.parquet"
            pq.write_table(canon, output)
            self.assertTrue(pq.read_table(output).equals(canon, check_metadata=True))

    def test_one_sign_flip_and_discharge_first_classification(self):
        source = trace("a", 1, 0, [CHARGE, CHARGE, DISCHARGE, DISCHARGE], [0, 1, 2, 3], [500, 500, -1000, -1000])
        rec, phases = audit_cycle(source, 1.0)
        canon = canonical_table(source, rec, phases, "sha", "profile")
        self.assertEqual(canon["current_a"].to_pylist(), [-0.5, -0.5, 1.0, 1.0])
        self.assertEqual(canon["operation_type"].to_pylist(), ["charge","charge","discharge","discharge"])
        self.assertEqual(canon["temperature_c"].null_count, 4)
        self.assertEqual(phases[-1], PHASE_DISCHARGE)

    def test_timestamp_flags_keep_sample_coordinates(self):
        rec = self.record([CHARGE] * 4, [0, 2, 2, 1], [1] * 4)
        reasons = {(issue["reason"], issue["sample_index"]) for issue in rec["issues"]}
        self.assertIn(("TIME_DUPLICATE", 2), reasons)
        self.assertIn(("TIME_REVERSED", 3), reasons)

    def test_keyed_dq_and_two_cells_with_same_cycle(self):
        dq, duplicates = index_dq({"dq_by_cycle_raw": [
            {"cycle_id": 3,"value": 11}, {"cycle_id": 1,"value": 8}, {"cycle_id": 3,"value": 9},
        ]})
        self.assertEqual(duplicates, {3})
        self.assertEqual(dq, {1: 8})
        a = self.record([CHARGE]*2 + [DISCHARGE]*2,[0,1,2,3],[1,1,-1,-1],8,capacities=[0,9,9,1])
        b = self.record([CHARGE]*2 + [DISCHARGE]*2,[0,1,2,3],[1,1,-1,-1],None,cell="b",capacities=[0,12,12,1])
        annotate_pairs([a])
        annotate_pairs([b])
        self.assertEqual(a["pair_status"], "READY_FOR_P3_3_AUDIT")
        self.assertEqual(b["pair_reason"], "DQ_MISSING_OR_DUPLICATE")
        with self.assertRaisesRegex(ValueError,"same cell"):
            annotate_pairs([a,b])

    def test_ambiguous_phases_and_counter_reset(self):
        two_dis = self.record([CHARGE]*2+[DISCHARGE]*2+["Rest"]+[DISCHARGE]*2,
                              list(range(7)), [1,1,-1,-1,0,-1,-1], 4)
        annotate_pairs([two_dis])
        self.assertEqual(two_dis["pair_reason"], "MULTIPLE_DISCHARGE_SESSIONS")
        reset = self.record([CHARGE]*2+[DISCHARGE]*3, list(range(5)),[1,1,-1,-1,-1], 4, capacities=[0,6,6,8,2])
        annotate_pairs([reset])
        self.assertEqual(reset["pair_reason"], "CAPACITY_COUNTER_RESET")

    def test_cross_cycle_requires_proven_clock(self):
        a = self.record([CHARGE]*2, [0, 5], [1000,1000], cycle=4)
        b = self.record([DISCHARGE]*2, [0,6], [-1000,-1000], 10, cycle=5, order=1, capacities=[10,0])
        annotate_pairs([a,b])
        self.assertEqual(a["pair_reason"], "CROSS_CYCLE_CLOCK_NOT_PROVEN")
        b = self.record([DISCHARGE]*2, [7,9], [-1000,-1000], 10, cycle=5, order=1, capacities=[10,0])
        annotate_pairs([a,b])
        self.assertEqual(a["pair_geometry"], "CROSS_CYCLE")
        self.assertEqual(a["label_observed_at"]["time_s_raw"], 9)

    def test_integral_skips_gap_and_keeps_end_time(self):
        rec = self.record([CHARGE]*2+[DISCHARGE]*4, [0,1,2,7,12,90],
                          [1,1,-1000,-1000,-1000,-1000], 3,
                          capacities=[0,4,4,3,2,1])
        annotate_pairs([rec])
        self.assertAlmostEqual(rec["integral_mah"], 10000/3600)
        self.assertEqual(rec["integral_skipped_intervals"], 1)
        self.assertEqual(rec["label_observed_at"]["time_s_raw"], 90)

    def test_nonfinite_missing_and_wrong_sign(self):
        rec = self.record([CHARGE]*3, [0,1,None], [1,-1,float("inf")],
                          voltages=[3, float("nan"), None])
        self.assertEqual(rec["signal_counts"]["time_s_raw"]["null"], 1)
        self.assertEqual(rec["signal_counts"]["voltage_v_raw"]["nan"], 1)
        self.assertEqual(rec["signal_counts"]["current_ma_raw"]["inf"], 1)
        self.assertEqual(rec["wrong_sign_count"], 1)

    @unittest.skipUnless(Path("/staged/1-1.parquet").is_file(), "real staging not mounted")
    def test_real_reference_cycle_1(self):
        self.assertTrue(check_reference_cycle(Path("/staged")))


if __name__ == "__main__":
    unittest.main()
