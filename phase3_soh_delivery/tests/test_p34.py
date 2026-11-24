import unittest

from build_p34_split import canonical_ids, allocate, build_folds, reconcile_counts


class P34Tests(unittest.TestCase):
    def setUp(self):
        distribution={2:(5,1),3:(24,6),4:(23,6),5:(24,6)}
        self.metadata={f"{rate}-{cell}":(rate,1,3) for rate,(num,_) in distribution.items() for cell in range(1,num+1)}
        self.quotas={rate:test for rate,(_,test) in distribution.items()}

    def test_canonical_id_rejects_alias_and_invalid_id(self):
        for ids in (["1-1","01-1"], ["1-1","1-01"], ["1-1","1-1 "], ["1-1","1-1"],["0-1"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                canonical_ids(ids)
        self.assertEqual(canonical_ids(["10-1","2-1","1-1"]),["1-1","2-1","10-1"])

    def test_split_is_deterministic_independent_of_input_order(self):
        left=allocate(self.metadata,self.quotas,42)
        right=allocate(dict(reversed(list(self.metadata.items()))),self.quotas,42)
        self.assertEqual(left,right)
        development, held_out=left
        self.assertEqual((len(development),len(held_out)),(57,19))
        self.assertEqual(set(development)&set(held_out),set())
        self.assertEqual(set(development)|set(held_out),set(self.metadata))
        for rate,quota in self.quotas.items():
            self.assertEqual(sum(self.metadata[c][0]==rate for c in held_out),quota)

    def test_missing_or_invalid_stratum_quota_stops_before_draw(self):
        for quotas in ({2:0,3:6,4:6,5:6},{2:5,3:6,4:6,5:6},{2:1,3:6,4:6},{2:1,3:6,4:6,5:6,6:1}):
            with self.subTest(quotas=quotas),self.assertRaises(ValueError):
                allocate(self.metadata,quotas,42)

    def test_fold_assignments_cover_every_dev_cell_once(self):
        development, held_out=allocate(self.metadata,self.quotas,42)
        counts={cell:i+1 for i,cell in enumerate(development)}
        folds=build_folds(counts,5)
        self.assertEqual(folds,build_folds(dict(reversed(list(counts.items()))),5))
        validate=[cell for fold in folds for cell in fold["validation_cell_ids"]]
        self.assertEqual(sorted(validate),sorted(development))
        for fold in folds:
            train,val=set(fold["train_cell_ids"]),set(fold["validation_cell_ids"])
            self.assertFalse(train&val)
            self.assertFalse((train|val)&set(held_out))
            self.assertEqual(train|val,set(development))
            self.assertEqual(fold["validation_labels"],sum(counts[c] for c in val))

    def test_reconciliation_counts_only_whole_cells(self):
        a,b=reconcile_counts({"1-1":7,"2-1":4,"3-1":3},["1-1","3-1"],["2-1"])
        self.assertEqual((a,b),(10,4))
        for counts,dev,test in (
            ({"1-1":1,"2-1":1},["1-1","2-1"],["2-1"]),
            ({"1-1":1,"2-1":1},["1-1"],["3-1"]),
            ({"1-1":1,"2-1":0},["1-1"],["2-1"]),
        ):
            with self.subTest(counts=counts,dev=dev,test=test),self.assertRaises(ValueError):
                reconcile_counts(counts,dev,test)


if __name__=="__main__":
    unittest.main()
