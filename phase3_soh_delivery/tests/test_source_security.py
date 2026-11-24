import io
import stat
import unittest
import warnings
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from scripts.audit_rt_batt_source import inspect_pickle, validate_directory


class SourceAuditTests(unittest.TestCase):
    def check_members(self, *members):
        memory = io.BytesIO()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Duplicate name")
            with ZipFile(memory, "w", compression=ZIP_DEFLATED) as archive:
                for name, data in members:
                    archive.writestr(name, data)
        with ZipFile(memory) as archive:
            return validate_directory(archive.infolist())

    def test_accepts_regular_file_under_directory(self):
        self.assertEqual(self.check_members(("our_data/", b""), ("our_data/1-1.pkl", b"abc")), 3)

    def test_rejects_path_traversal_and_windows_aliases(self):
        for name in ("../outside", "/absolute", "folder/../../outside", "C:/file", "folder/COM1"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe ZIP path"):
                self.check_members((name, b"data"))

    def test_rejects_backslash_in_raw_zip_directory(self):
        memory = io.BytesIO()
        with ZipFile(memory, "w") as archive:
            archive.writestr("folder/file", b"data")
        raw = memory.getvalue().replace(b"folder/file", b"folder\\file")
        with ZipFile(io.BytesIO(raw)) as archive:
            with self.assertRaisesRegex(ValueError, "Unsafe ZIP path"):
                validate_directory(archive.infolist())

    def test_rejects_duplicate_or_conflicting_paths(self):
        for first, second in (("same", "same"), ("same", "Same"), ("file", "file/nested"), ("A/one", "a/two")):
            with self.subTest(first=first, second=second), self.assertRaisesRegex(ValueError, "ZIP path"):
                self.check_members((first, b"one"), (second, b"two"))

    def test_rejects_symlink_entry(self):
        entry = ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(ValueError, "Link or special ZIP member"):
            self.check_members((entry, b"target"))

    def test_rejects_expansion_ratio_over_limit(self):
        with self.assertRaisesRegex(ValueError, "exceeds expanded size or ratio quota"):
            self.check_members(("large", b"0" * 10_000))

    def test_zip_library_detects_bad_crc(self):
        memory = io.BytesIO()
        with ZipFile(memory, "w") as archive:
            archive.writestr("entry", b"original-content")
        changed = memory.getvalue().replace(b"original-content", b"modified-content", 1)
        with ZipFile(io.BytesIO(changed)) as archive:
            self.assertEqual(archive.testzip(), "entry")

    def test_resolves_stack_global_from_memoized_strings(self):
        # PROTO, string/memo, POP, string loaded from memo, name, STACK_GLOBAL, STOP.
        stream = io.BytesIO(b"\x80\x04\x8c\x08builtins\x940h\x00\x8c\x05slice\x93.")
        result = inspect_pickle(stream)
        self.assertEqual(result["globals"], {"builtins.slice": 1})
        self.assertEqual(result["findings"], [])

    def test_flags_unknown_global_and_trailing_bytes(self):
        stream = io.BytesIO(b"\x80\x04\x8c\x07decimal\x8c\x07Decimal\x93.x")
        result = inspect_pickle(stream)
        self.assertEqual(result["findings"], ["Extra bytes after STOP", "Global outside expected set: decimal.Decimal"])

    def test_flags_unresolved_stack_global(self):
        stream = io.BytesIO(b"\x80\x04NN\x93.")
        self.assertEqual(inspect_pickle(stream)["findings"], ["Unresolved STACK_GLOBAL at byte 4"])

    def test_rejects_truncated_pickle(self):
        with self.assertRaises(ValueError):
            inspect_pickle(io.BytesIO(b"\x80\x04N"))


if __name__ == "__main__":
    unittest.main()
