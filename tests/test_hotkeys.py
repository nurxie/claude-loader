"""Shortcut strings on both systems: what counts as usable, and how it reads."""

import unittest

import context  # noqa: F401
from claude_profiles.linux import integration as linux
from claude_profiles.windows import hotkeys as win


class TestWindowsHotkeys(unittest.TestCase):
    def test_a_plain_shortcut_is_fine(self):
        for accel in ("Win+Shift+C", "Ctrl+Alt+C", "Ctrl+Alt+Shift+F5", "Win+Alt+Space"):
            self.assertIsNone(win.problem(accel), accel)

    def test_one_key_on_its_own_is_not_a_shortcut(self):
        self.assertIsNotNone(win.problem("C"))
        self.assertIsNotNone(win.problem(""))
        self.assertIsNotNone(win.problem(None))

    def test_five_keys_are_too_many(self):
        self.assertIsNotNone(win.problem("Win+Ctrl+Alt+Shift+C"))

    def test_shift_alone_would_swallow_typing(self):
        self.assertIsNotNone(win.problem("Shift+C"))

    def test_a_modifier_cannot_be_the_last_key(self):
        self.assertIsNotNone(win.problem("Ctrl+Alt"))

    def test_the_same_modifier_twice_is_refused(self):
        self.assertIsNotNone(win.problem("Ctrl+Control+C"))

    def test_an_unknown_key_is_refused(self):
        self.assertIsNotNone(win.problem("Ctrl+Alt+Пробел"))

    def test_shortcuts_are_written_the_way_windows_writes_them(self):
        self.assertEqual(win.normalize("shift+win+c"), "Win+Shift+C")
        self.assertEqual(win.normalize("alt+ctrl+f5"), "Ctrl+Alt+F5")
        self.assertEqual(win.normalize("ctrl+shift+space"), "Ctrl+Shift+Space")
        self.assertEqual(win.normalize("ctrl+alt+pageup"), "Ctrl+Alt+PageUp")

    def test_parsing_gives_the_flags_and_the_key(self):
        mods, vk = win.parse("Ctrl+Alt+C")
        self.assertEqual(mods, win.MOD_CONTROL | win.MOD_ALT)
        self.assertEqual(vk, ord("C"))

    def test_nonsense_does_not_parse(self):
        self.assertIsNone(win.parse("Shift+C"))
        self.assertIsNone(win.normalize("nope"))

    def test_every_preset_is_usable(self):
        for value, _label in win.PRESETS:
            self.assertIsNone(win.problem(value), value)


class TestLinuxHotkeys(unittest.TestCase):
    def test_a_plain_shortcut_is_fine(self):
        for accel in ("<Super><Shift>c", "<Control><Alt>c", "<Super><Alt>k"):
            self.assertIsNone(linux.hotkey_problem(accel), accel)

    def test_it_must_be_written_the_gnome_way(self):
        self.assertIsNotNone(linux.hotkey_problem("Super+Shift+C"))
        self.assertIsNotNone(linux.hotkey_problem(""))
        self.assertIsNotNone(linux.hotkey_problem(None))

    def test_one_key_on_its_own_is_not_a_shortcut(self):
        self.assertIsNotNone(linux.hotkey_problem("c"))

    def test_five_keys_are_too_many(self):
        self.assertIsNotNone(linux.hotkey_problem("<Super><Control><Alt><Shift>c"))

    def test_shift_alone_would_swallow_typing(self):
        self.assertIsNotNone(linux.hotkey_problem("<Shift>c"))

    def test_the_same_modifier_twice_is_refused(self):
        self.assertIsNotNone(linux.hotkey_problem("<Control><Control>c"))

    def test_shortcuts_read_the_way_people_say_them(self):
        self.assertEqual(linux.hotkey_label("<Super><Shift>c"), "Super+Shift+C")
        self.assertEqual(linux.hotkey_label("<Control><Alt>k"), "Ctrl+Alt+K")
        self.assertEqual(linux.hotkey_label("<Primary><Alt>F5"), "Ctrl+Alt+F5")
        self.assertEqual(linux.hotkey_label(None), "none")

    def test_every_preset_is_usable(self):
        from claude_profiles.linux.platform import LinuxPlatform
        for value, _label in LinuxPlatform.hotkey_presets:
            self.assertTrue(linux.valid_hotkey(value), value)


class TestDesktopEntries(unittest.TestCase):
    def test_arguments_with_spaces_are_quoted(self):
        self.assertEqual(linux._exec_arg("/usr/bin/claude"), "/usr/bin/claude")
        self.assertEqual(linux._exec_arg("/home/a b/claude"), '"/home/a b/claude"')

    def test_quotes_in_a_path_are_escaped(self):
        self.assertEqual(linux._exec_arg('a"b'), '"a\\"b"')

    def test_an_entry_carries_the_marker_that_says_it_is_ours(self):
        text = linux._entry_text(Type="Application", Name="X", Terminal=False)
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Terminal=false", text)
        self.assertIn(linux.MARKER, text)

    def test_empty_fields_are_left_out(self):
        self.assertNotIn("Icon=", linux._entry_text(Type="Application", Icon=None))


if __name__ == "__main__":
    unittest.main()
