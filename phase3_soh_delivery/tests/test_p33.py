import json
import math
from pathlib import Path
import unittest
import csv
from itertools import islice

from build_p33_labels import commission, make_label, parse_pair


def point(cell, cycle, operation, sample, seconds):
    return {
        "cell_id": cell, "cycle_id": cycle, "cycle_source_order": cycle - 1,
        "operation_number": operation, "sample_index": sample, "time_s_raw": seconds,
    }


def pair(cycle, capacity=1000.0, cell="test"):
    return {
        "cell_id": cell, "cycle_id": str(cycle), "cycle_source_order": str(cycle - 1),
        "source_member": f"our_data/{cell}.pkl", "protocol_id": "TEST_OBSERVED",
        "pair_status": "READY_FOR_P3_3_AUDIT", "pair_geometry": "SAME_CYCLE",
        "pair_reason": "", "discharge_cycle_id": str(cycle),
        "feature_available_at": json.dumps(point(cell, cycle, 0, 100, 500.0)),
        "discharge_start_at": json.dumps(point(cell, cycle, 1, 101, 506.0)),
        "label_observed_at": json.dumps(point(cell, cycle, 1, 201, 1006.0)),
        "paired_dq_raw": str(capacity), "capacity_counter_delta_mah": str(capacity),
        "capacity_counter_reset_count": "0", "discharge_cutoff_v": "1.99",
        "diagnostic_counts": "{}",
    }


def evidence(rows):
    return [{"cycle_id": row["cycle_id"], "source_order": row["cycle_source_order"], "review_reasons": []} for row in rows]


class P33Tests(unittest.TestCase):
    def setUp(self):
        self.pairs = [parse_pair(pair(cycle, q)) for cycle, q in enumerate([1100, 900, 1000, 1200, 800, 1050], 1)]

    def test_reference_median_and_fifth_discharge_availability(self):
        result = commission("test", self.pairs, evidence(self.pairs))
        self.assertAlmostEqual(result["q_ref_ah"], 1.0)
        self.assertEqual(result["qref_available_at"].cycle_id, 5)
        self.assertEqual(result["qref_available_at"].sample_index, 201)

    def test_reset_clock_and_warmup_never_leak(self):
        ref = commission("test", self.pairs, evidence(self.pairs))
        for item in self.pairs[:5]:
            self.assertEqual(make_label(item, ref)["label_status"], "COMMISSIONING_WARMUP")
        result = make_label(self.pairs[5], ref)
        self.assertGreater(ref["qref_available_at"].time_s_raw, self.pairs[5]["feature"].time_s_raw)
        self.assertEqual(result["label_status"], "LABEL_DRAFT_READY")
        self.assertEqual(result["soh_ref_percent"], 105.0)

    def test_missing_cycle_does_not_slide_commissioning(self):
        rows = [self.pairs[0], *self.pairs[2:]]
        result = commission("test", rows, evidence(rows))
        self.assertIn("EARLY_CYCLES_NOT_CONSECUTIVE_1_TO_5", result["reasons"])
        self.assertIsNone(result["q_ref_ah"])

    def test_short_commissioning_and_mismatched_early_trace(self):
        rows = self.pairs[:4]
        self.assertIn("FEWER_THAN_FIVE_EARLY_CYCLES", commission("test", rows, evidence(rows))["reasons"])
        traces = evidence(self.pairs)
        traces[4]["cycle_id"] = 6
        self.assertIn("EARLY_TRACE_KEYS_DO_NOT_MATCH", commission("test", self.pairs, traces)["reasons"])

    def test_nonpositive_capacity_and_counter_disagreement(self):
        for value in (0, -1, math.nan, math.inf):
            with self.subTest(value=value):
                parsed = parse_pair(pair(3, value))
                self.assertFalse(parsed["valid_pair"])
                rows = [*self.pairs[:2], parsed, *self.pairs[3:]]
                self.assertIsNone(commission("test", rows, evidence(rows))["q_ref_ah"])
        raw = pair(1)
        raw["capacity_counter_delta_mah"] = "998.0"
        self.assertEqual(parse_pair(raw)["pair_review_reason"], "DQ_COUNTER_MISMATCH")

    def test_two_cells_with_same_cycle_do_not_mix(self):
        other = [parse_pair(pair(c, 700, "other")) for c in range(1, 7)]
        ref = commission("other", other, evidence(other))
        self.assertAlmostEqual(ref["q_ref_ah"], 0.7)
        with self.assertRaisesRegex(ValueError,"same cell"):
            commission("test", [self.pairs[0], *other[1:]], evidence(other))
        with self.assertRaisesRegex(ValueError,"same cell"):
            make_label(self.pairs[-1], ref)

    def test_rejected_pair_preserves_p32_duplicate(self):
        raw = pair(6)
        raw.update(pair_status="REVIEW",pair_reason="CHARGE_OR_DISCHARGE_SIGNAL_REVIEW",
                   diagnostic_counts='{"TIME_DUPLICATE":1}')
        item = parse_pair(raw)
        ref = commission("test", self.pairs, evidence(self.pairs))
        result = make_label(item, ref)
        self.assertEqual(result["label_status"], "P32_PAIR_REVIEW")
        self.assertIn("TIME_DUPLICATE", result["p32_diagnostics"])
        self.assertIsNone(result["soh_ref_percent"])

    def test_cross_cell_missing_event_and_reversed_events_do_not_pair(self):
        for field, replacement in (
            ("label_observed_at",point("other",1,1,201,1006)),
            ("discharge_start_at",point("test",2,1,101,506)),
            ("label_observed_at",point("test",1,1,99,499)),
            ("label_observed_at",None),
        ):
            with self.subTest(replacement=replacement):
                raw = pair(1)
                raw[field] = json.dumps(replacement) if replacement else ""
                self.assertFalse(parse_pair(raw)["valid_pair"])

    def test_contested_cell_is_held_without_substitution(self):
        items = [parse_pair(pair(c,cell="7-5")) for c in range(1, 8)]
        ref = commission("7-5", items, evidence(items))
        self.assertEqual(ref["status"], "QREF_COMMISSIONING_BLOCKED")
        self.assertIn("BATTERYML_EARLY_CYCLE_REVIEW", ref["reasons"])
        self.assertEqual(ref["source_cycle_ids"], [1,2,3,4,5])
        self.assertIsNone(ref["qref_available_at"])
        self.assertEqual(make_label(items[-1], ref)["label_status"], "QREF_COMMISSIONING_BLOCKED")

    @unittest.skipUnless(Path("/input/cell_cycle_inventory.csv").is_file(), "P3.2 inventory not mounted")
    def test_real_cell_1_1_reference_and_cycle_six(self):
        with Path("/input/cell_cycle_inventory.csv").open(encoding="utf-8",newline="") as source:
            rows = [parse_pair(raw) for raw in islice(csv.DictReader(source),6)]
        reference = commission("1-1",rows,evidence(rows))
        self.assertAlmostEqual(reference["q_ref_ah"],1.1725066444444444,places=12)
        self.assertEqual(make_label(rows[4],reference)["label_status"], "COMMISSIONING_WARMUP")
        self.assertAlmostEqual(make_label(rows[5],reference)["soh_ref_percent"],99.8959550382275,places=6)


if __name__ == "__main__":
    unittest.main()
