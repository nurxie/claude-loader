"""The password lock, and how a release archive is unpacked."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import context  # noqa: F401
from claude_profiles.core import security, selfupdate


class TestPasswords(unittest.TestCase):
    def test_the_right_password_opens_it(self):
        record = security.hash_password("hunter2")
        self.assertTrue(security.verify_password("hunter2", record))

    def test_a_wrong_password_does_not(self):
        record = security.hash_password("hunter2")
        for wrong in ("hunter3", "", "HUNTER2", " hunter2"):
            self.assertFalse(security.verify_password(wrong, record), wrong)

    def test_the_password_itself_is_not_in_the_record(self):
        record = security.hash_password("hunter2")
        self.assertNotIn("hunter2", str(record))
        self.assertEqual(set(record), {"algo", "iterations", "salt", "hash"})

    def test_the_same_password_hashes_differently_every_time(self):
        self.assertNotEqual(security.hash_password("x")["hash"],
                            security.hash_password("x")["hash"])

    def test_a_damaged_record_refuses_rather_than_crashes(self):
        for record in ({}, None, {"algo": "something-else"},
                       {"algo": security.ALGO, "salt": "!!", "hash": "!!", "iterations": "x"}):
            self.assertFalse(security.verify_password("x", record))

    def test_unicode_passwords_work(self):
        record = security.hash_password("пароль")
        self.assertTrue(security.verify_password("пароль", record))


class TestVersions(unittest.TestCase):
    def test_a_tag_becomes_numbers(self):
        self.assertEqual(selfupdate.parse_version("v0.4.0"), (0, 4, 0))
        self.assertEqual(selfupdate.parse_version("0.10.2"), (0, 10, 2))

    def test_versions_compare_by_number_not_by_text(self):
        self.assertGreater(selfupdate.parse_version("0.10.0"), selfupdate.parse_version("0.9.0"))

    def test_newer_is_newer(self):
        self.assertTrue(selfupdate.is_newer("0.5.0", "0.4.0"))
        self.assertFalse(selfupdate.is_newer("0.4.0", "0.4.0"))
        self.assertFalse(selfupdate.is_newer("0.3.0", "0.4.0"))

    def test_something_unreadable_sorts_lowest(self):
        self.assertEqual(selfupdate.parse_version("nightly"), (0,))
        self.assertFalse(selfupdate.is_newer(None, "0.1.0"))


class TestUnpacking(unittest.TestCase):
    """Only the program's Python files may come out of a downloaded archive."""

    def _zip(self, members) -> zipfile.ZipFile:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            for name, content in members.items():
                zf.writestr(name, content)
        return zipfile.ZipFile(buffer)

    def test_python_files_are_taken(self):
        zf = self._zip({"repo-abc/cross-platform/claude_profiles/core/usage.py": "x = 1\n",
                        "repo-abc/cross-platform/claude_profiles/core/sub/a.py": "y = 2\n"})
        with tempfile.TemporaryDirectory() as tmp:
            written = selfupdate._extract_tree(
                zf, "repo-abc/", "cross-platform/claude_profiles/core", Path(tmp))
            self.assertEqual(written, 2)
            self.assertEqual((Path(tmp) / "usage.py").read_text(), "x = 1\n")

    def test_anything_that_is_not_python_is_left_behind(self):
        zf = self._zip({"repo-abc/cross-platform/claude_profiles/core/run.sh": "rm -rf /\n",
                        "repo-abc/cross-platform/claude_profiles/core/a.py": "ok = 1\n"})
        with tempfile.TemporaryDirectory() as tmp:
            selfupdate._extract_tree(zf, "repo-abc/", "cross-platform/claude_profiles/core",
                                     Path(tmp))
            self.assertFalse((Path(tmp) / "run.sh").exists())
            self.assertTrue((Path(tmp) / "a.py").exists())

    def test_a_path_that_climbs_out_of_the_folder_is_refused(self):
        zf = self._zip({"repo-abc/cross-platform/claude_profiles/core/../../escape.py": "x\n"})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(selfupdate.UpdateError):
                selfupdate._extract_tree(zf, "repo-abc/",
                                         "cross-platform/claude_profiles/core", Path(tmp))

    def test_an_unexpectedly_large_file_is_refused(self):
        zf = self._zip({"repo-abc/cross-platform/claude_profiles/core/big.py":
                        "#" * (selfupdate.MAX_FILE + 1)})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(selfupdate.UpdateError):
                selfupdate._extract_tree(zf, "repo-abc/",
                                         "cross-platform/claude_profiles/core", Path(tmp))

    def test_an_update_must_come_over_https(self):
        with self.assertRaises(selfupdate.UpdateError):
            selfupdate.install("http://example.org/release.zip")


if __name__ == "__main__":
    unittest.main()
