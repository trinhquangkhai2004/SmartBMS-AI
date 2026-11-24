import unittest
import json
import numpy as np
import pyarrow.parquet as pq
from scripts.build_p35_features import ROOT, manifest, SPLIT_HASH, FOLD_HASH
from src.soh.feature_extractor import FAST, TOP, extract_charge, band_capacity


class ChargeFeatureTests(unittest.TestCase):
    def test_linear_crossings_and_units(self):
        # Between seconds 2 and 6 the current rises linearly from 1.4 to 2.2 A.
        result, reason=band_capacity(np.array([0.,10.]),np.array([3.,4.]),np.array([1.,3.]),3.2,3.6,30.)
        self.assertIsNone(reason)
        self.assertAlmostEqual(result,1.8*4/3600)
    def test_missing_crossing_or_gap(self):
        for v,reason in [([3.4,3.49],"PARTIAL_WINDOW"),([3.4,3.6],"WINDOW_GAP")]:
            self.assertEqual(band_capacity(np.array([0.,60.]),np.array(v),np.ones(2),3.45,3.55,30.),(None,reason))
    def test_flat_voltage_integrates_finitely(self):
        val,reason=band_capacity(np.arange(4.),np.array([3.4,3.5,3.5,3.6]),np.ones(4),3.45,3.55,30.)
        self.assertAlmostEqual(val,2/3600)
        self.assertIsNone(reason)
    def setUp(self):
        self.t=np.arange(9.)*5
        self.v=np.array([3.1,3.4,3.42,3.45,3.55,3.596,3.598,3.600,3.600])
        self.i=-np.array([5.5,5.5,1.1,1.1,1.1,0.90,0.60,0.35,0.08])
        self.status=[FAST]*2+[TOP]*7
    def test_confirmed_stages_and_ratio(self):
        out,why=extract_charge(self.t,self.v,self.i,self.status)
        self.assertAlmostEqual(out["q_cc_ah"],(5.5*5+1.1*10)/3600)
        self.assertAlmostEqual(out["q_cv_ah"],((.9+.6)/2+(.6+.35)/2+(.35+.08)/2)*5/3600)
        self.assertAlmostEqual(out["q_cv_over_q_cc"],out["q_cv_ah"]/out["q_cc_ah"])
        self.assertNotIn("q_cc_ah",why)
    def test_invalid_current_time_and_future_phase(self):
        for t,i,s in [(self.t,-self.i,self.status),(self.t*0,self.i,self.status),
                      (self.t,self.i,self.status[:-1]+["discharge"]),(self.t,np.zeros_like(self.i),self.status)]:
            out,why=extract_charge(t,self.v,i,s)
            self.assertTrue(all(x is None for x in out.values()))
            self.assertTrue(why)
    def test_unconfirmed_tail_is_missing(self):
        v=self.v.copy();v[-1]=3.53
        out,_=extract_charge(self.t,v,self.i,self.status)
        self.assertIsNone(out["q_cv_ah"]);self.assertIsNone(out["q_cv_over_q_cc"])
    def test_unsupported_features_and_inputs(self):
        out,_=extract_charge(self.t,self.v,self.i,self.status)
        self.assertFalse(any("ic_peak" in x or "relative_delta" in x or "temp" in x for x in out))
        with self.assertRaises(TypeError):
            extract_charge(self.t,self.v,self.i,self.status,soh_ref_percent=90)

    def test_individual_plateau_violations(self):
        for name, idx, value, lost in [
            ("fast", 0, -5.67, ("q_cc_ah", "q_cv_over_q_cc")),
            ("topup", 2, -1.16, ("q_cc_ah", "q_cv_ah", "q_cv_over_q_cc")),
            ("cv", -1, 3.594, ("q_cc_ah", "q_cv_ah", "q_cv_over_q_cc")),
        ]:
            with self.subTest(guard=name):
                amps, volts = self.i.copy(), self.v.copy()
                (volts if name == "cv" else amps)[idx] = value
                out, why = extract_charge(self.t, volts, amps, self.status)
                for feature in lost:
                    self.assertIsNone(out[feature])
                    self.assertIn(feature, why)
                self.assertGreater(out["delta_q_350_358_ah"], 0)
                if name == "fast":
                    self.assertGreater(out["q_cv_ah"], 0)

    def test_ratio_denominator_below_epsilon(self):
        out, why = extract_charge(self.t * 1e-9, self.v, self.i, self.status)
        self.assertGreater(out["q_cc_ah"], 0)
        self.assertLess(out["q_cc_ah"], 1e-8)
        self.assertIsNone(out["q_cv_over_q_cc"])
        self.assertIn("q_cv_over_q_cc", why)
        zero, _ = extract_charge(self.t, self.v, np.zeros_like(self.i), self.status)
        self.assertIsNone(zero["q_cv_over_q_cc"])

    def test_empty_band_and_noisy_plateau(self):
        v = np.array([3.49, 3.52, 3.52, 3.519, 3.521, 3.59])
        t = np.arange(len(v), dtype=float)
        q, why = band_capacity(t, v, np.ones_like(v), 3.50, 3.58, 30)
        self.assertIsNone(why)
        expected_seconds = 2/3 + 3 + (3.58-3.521)/(3.59-3.521)
        self.assertAlmostEqual(q, expected_seconds/3600, places=12)
        self.assertEqual(band_capacity(t, v, np.zeros_like(v), 3.50, 3.58, 30),
                         (None, "EMPTY_WINDOW"))

    def test_real_development_parity_each_validation_fold(self):
        allowed = set(manifest("p3_split_manifest.json", SPLIT_HASH)["development_cell_ids"])
        folds = manifest("p3_cv_fold_manifest.json", FOLD_HASH)["folds"]
        for fold in folds:
            cell = fold["validation_cell_ids"][0]
            self.assertIn(cell, allowed)
            rows = pq.read_table(ROOT/"data/features/soh_feature_table.parquet",
                                 filters=[("cell_id", "=", cell)])
            row = rows.slice(rows.num_rows // 2, 1).to_pylist()[0]
            with self.subTest(cell=cell, cycle=row["cycle_id"], fold=fold["fold"]):
                self.assertEqual(row["validation_fold"], fold["fold"])
                trace = pq.read_table(ROOT/f"data/staging/rt_batt_v2/{cell}.parquet",
                                      columns=["time_s_raw", "voltage_v_raw", "current_ma_raw",
                                               "raw_status", "sample_index"],
                                      filters=[("cycle_id", "=", row["cycle_id"]),
                                               ("raw_status", "in", [FAST, TOP])])
                values, why = extract_charge(trace["time_s_raw"].to_numpy(), trace["voltage_v_raw"].to_numpy(),
                                             -trace["current_ma_raw"].to_numpy()/1000, trace["raw_status"].to_pylist())
                self.assertEqual(values, {n: row[n] for n in values})
                self.assertEqual(why, json.loads(row["missing_reasons"]))
                self.assertEqual(trace["sample_index"][-1].as_py(), row["end_charge_sample_index"])
