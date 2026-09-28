"""Profiles, the rules they must obey, and reading an older config file."""

import json
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from claude_profiles.core import config as cfgmod
from claude_profiles.core import paths
from claude_profiles.core.config import Config, ConfigError, Profile


def profile(pid="work", name="Work", **kw) -> Profile:
    kw.setdefault("data_dir", f"/tmp/claude-profiles-test/{pid}")
    return Profile(id=pid, name=name, **kw)


class TestIds(unittest.TestCase):
    def test_a_name_becomes_a_usable_id(self):
        self.assertEqual(cfgmod.make_id("Work", set()), "work")
        self.assertEqual(cfgmod.make_id("IEP SAS", set()), "iep-sas")
        self.assertEqual(cfgmod.make_id("Моя работа", set()), "profile")

    def test_ids_do_not_collide(self):
        self.assertEqual(cfgmod.make_id("Work", {"work"}), "work-2")
        self.assertEqual(cfgmod.make_id("Work", {"work", "work-2"}), "work-3")

    def test_reserved_ids_are_stepped_around(self):
        self.assertEqual(cfgmod.make_id("desktop", set()), "desktop-1")

    def test_a_long_name_is_cut_to_something_usable(self):
        self.assertLessEqual(len(cfgmod.make_id("A" * 60, set())), 20)


class TestValidate(unittest.TestCase):
    def test_a_plain_config_is_fine(self):
        Config(profiles=[profile()]).validate()

    def test_ids_must_be_unique(self):
        cfg = Config(profiles=[profile(), profile(name="Other")])
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_only_one_profile_may_use_the_standard_folders(self):
        cfg = Config(profiles=[profile(pid="a", system_default=True, data_dir=""),
                               profile(pid="b", name="B", system_default=True, data_dir="")])
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_two_profiles_cannot_share_a_folder(self):
        cfg = Config(profiles=[profile(pid="a", data_dir="/tmp/same"),
                               profile(pid="b", name="B", data_dir="/tmp/same")])
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_an_id_must_look_like_a_file_name(self):
        for bad in ("Work", "with space", "-leading", "a" * 21, "desktop"):
            with self.assertRaises(ConfigError, msg=bad):
                Config(profiles=[profile(pid=bad)]).validate()

    def test_a_data_folder_must_be_absolute(self):
        with self.assertRaises(ConfigError):
            Config(profiles=[profile(data_dir="relative/path")]).validate()

    def test_more_than_five_profiles_is_refused(self):
        cfg = Config(profiles=[profile(pid=f"p{i}", name=f"P{i}") for i in range(6)])
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_the_warning_threshold_is_a_percentage(self):
        for bad in (-1, 101, "90"):
            cfg = Config(profiles=[profile()], usage_alert_percent=bad)
            with self.assertRaises(ConfigError, msg=str(bad)):
                cfg.validate()


class TestGroups(unittest.TestCase):
    def _cfg(self) -> Config:
        return Config(profiles=[profile(pid="a", name="A"), profile(pid="b", name="B"),
                                profile(pid="c", name="C")])

    def test_a_group_needs_at_least_two_profiles(self):
        cfg = self._cfg()
        self.assertFalse(cfg.remember_group(["a"]))
        self.assertEqual(cfg.group(), [])

    def test_a_group_is_kept_in_profile_order(self):
        cfg = self._cfg()
        self.assertTrue(cfg.remember_group(["c", "a"]))
        self.assertEqual([p.id for p in cfg.group()], ["a", "c"])
        self.assertEqual(cfg.group_label(), "A + C")

    def test_remembering_the_same_group_changes_nothing(self):
        cfg = self._cfg()
        cfg.remember_group(["a", "b"])
        self.assertFalse(cfg.remember_group(["a", "b"]))

    def test_removing_a_profile_forgets_it_everywhere(self):
        cfg = self._cfg()
        cfg.remember_group(["a", "b"])
        cfg.autostart_profiles = ["a", "b"]
        cfg.profiles = [p for p in cfg.profiles if p.id != "b"]
        cfg.prune()
        self.assertEqual(cfg.loader.last_group, ["a"])
        self.assertEqual(cfg.autostart_profiles, ["a"])


class TestSaveAndLoad(unittest.TestCase):
    """The file lives at a fixed place, so point that place somewhere temporary."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self._keep = (paths.CONFIG_DIR, paths.CONFIG_FILE)
        paths.CONFIG_DIR = self.folder
        paths.CONFIG_FILE = self.folder / "config.json"

    def tearDown(self):
        paths.CONFIG_DIR, paths.CONFIG_FILE = self._keep
        self.tmp.cleanup()

    def test_what_is_saved_is_what_is_read_back(self):
        cfg = Config(profiles=[profile(pid="work", name="Work", usage_limit=300_000)])
        cfgmod.save(cfg)
        again = cfgmod.load()
        self.assertEqual(again.profiles[0].name, "Work")
        self.assertEqual(again.profiles[0].usage_limit, 300_000)

    def test_not_set_up_yet_reads_as_nothing(self):
        self.assertIsNone(cfgmod.load())

    def test_unknown_keys_are_ignored(self):
        paths.CONFIG_FILE.write_text(json.dumps({
            "profiles": [{"id": "work", "name": "Work", "data_dir": "/tmp/w",
                          "something_new": 1}],
            "invented_later": True, "version": 2,
        }))
        cfg = cfgmod.load()
        self.assertEqual(cfg.profiles[0].id, "work")

    def test_an_older_file_starts_asking_the_account(self):
        paths.CONFIG_FILE.write_text(json.dumps({
            "profiles": [{"id": "work", "name": "Work", "data_dir": "/tmp/w"}],
            "usage_online": False, "version": 1,
        }))
        cfg = cfgmod.load()
        self.assertTrue(cfg.usage_online)          # the key changed meaning
        self.assertEqual(cfg.version, cfgmod.CONFIG_VERSION)

    def test_a_current_file_is_left_alone(self):
        paths.CONFIG_FILE.write_text(json.dumps({
            "profiles": [{"id": "work", "name": "Work", "data_dir": "/tmp/w"}],
            "usage_online": False, "version": 2,
        }))
        self.assertFalse(cfgmod.load().usage_online)

    def test_the_file_is_private(self):
        cfgmod.save(Config(profiles=[profile()]))
        self.assertEqual(paths.CONFIG_FILE.stat().st_mode & 0o077, 0)


class TestNames(unittest.TestCase):
    def test_a_name_is_needed(self):
        self.assertIsNotNone(cfgmod.check_name(Config(), "  "))

    def test_names_do_not_repeat(self):
        cfg = Config(profiles=[profile(name="Work")])
        self.assertIsNotNone(cfgmod.check_name(cfg, "work"))
        self.assertIsNone(cfgmod.check_name(cfg, "Work", profile=cfg.profiles[0]))

    def test_colors_are_handed_out_one_by_one(self):
        cfg = Config()
        first = cfgmod.next_color(cfg)
        cfg.profiles.append(profile(color=first))
        self.assertNotEqual(cfgmod.next_color(cfg), first)


if __name__ == "__main__":
    unittest.main()
