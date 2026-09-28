"""Windows hotkeys in the form "Win+Shift+C" <-> RegisterHotKey modifiers and key codes."""

import ctypes
from typing import Optional, Tuple

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
         "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN}
# Windows writes shortcuts as Win+Ctrl+Alt+Shift+Key (e.g. Win+Shift+S, Ctrl+Alt+Del).
_ORDER = [("Win", MOD_WIN), ("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT)]

_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "insert": 0x2D, "delete": 0x2E,
         "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
         "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _KEYS[_c.lower()] = ord(_c)
for _n in range(1, 25):
    _KEYS[f"f{_n}"] = 0x6F + _n

# A shortcut is between two and four keys: one to three modifiers and one key.
MIN_KEYS, MAX_KEYS = 2, 4

PRESETS = [("Win+Shift+C", "Win+Shift+C"), ("Ctrl+Alt+C", "Ctrl+Alt+C"),
           ("Win+Alt+C", "Win+Alt+C"), ("Ctrl+Shift+Space", "Ctrl+Shift+Space"),
           ("Ctrl+Alt+Shift+C", "Ctrl+Alt+Shift+C")]


def _split(accel: Optional[str]) -> list:
    return [p.strip().lower() for p in (accel or "").split("+") if p.strip()]


def problem(accel: Optional[str]) -> Optional[str]:
    """Why this shortcut cannot be used, in one sentence. None means it is fine."""
    parts = _split(accel)
    if not parts:
        return "Press a key combination."
    if len(parts) < MIN_KEYS:
        return f"Use at least {MIN_KEYS} keys, for example Ctrl+Alt+C."
    if len(parts) > MAX_KEYS:
        return f"Use at most {MAX_KEYS} keys."
    modifiers = parts[:-1]
    unknown = next((p for p in modifiers if p not in _MODS), None)
    if unknown:
        return f"\"{unknown}\" is not a modifier. Use Ctrl, Alt, Shift or Win."
    if parts[-1] in _MODS:
        return "Finish the shortcut with a normal key, not a modifier."
    if parts[-1] not in _KEYS:
        return f"\"{parts[-1]}\" cannot be used as the last key."
    if len({_MODS[p] for p in modifiers}) != len(modifiers):
        return "The same modifier is used twice."
    mods = 0
    for p in modifiers:
        mods |= _MODS[p]
    # Shift alone is not enough: it would steal ordinary typing.
    if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return "Add Ctrl, Alt or Win - Shift on its own would swallow normal typing."
    return None


def parse(accel: Optional[str]) -> Optional[Tuple[int, int]]:
    """'Win+Shift+C' -> (modifiers, virtual key), or None if invalid."""
    if problem(accel):
        return None
    parts = _split(accel)
    mods = 0
    for p in parts[:-1]:
        mods |= _MODS[p]
    return mods, _KEYS[parts[-1]]


def normalize(accel: Optional[str]) -> Optional[str]:
    parsed = parse(accel)
    if not parsed:
        return None
    mods, vk = parsed
    names = [n for n, m in _ORDER if mods & m]
    key = next(k for k, v in _KEYS.items() if v == vk and (len(k) > 1 or k.isalnum()))
    key = key.upper() if len(key) == 1 else key[0].upper() + key[1:]
    if key.startswith("F") and key[1:].isdigit():
        key = key.upper()
    key = {"Pageup": "PageUp", "Pagedown": "PageDown"}.get(key, key)
    return "+".join(names + [key])


def is_free(accel: str) -> bool:
    """Try to register the hotkey for a moment. False if another program owns it."""
    parsed = parse(accel)
    if not parsed:
        return False
    user32 = ctypes.windll.user32
    hotkey_id = 0x5C1A
    if not user32.RegisterHotKey(None, hotkey_id, parsed[0] | MOD_NOREPEAT, parsed[1]):
        return False
    user32.UnregisterHotKey(None, hotkey_id)
    return True


def from_tk_event(keysym: str) -> str:
    """The shortcut a Tk key event plus the modifiers held right now spell out.

    The result is not checked; pass it to `problem()` to say what is wrong with
    it, or to `normalize()` to get the value to store.
    """
    user32 = ctypes.windll.user32

    def down(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    names = []
    if down(0x5B) or down(0x5C):
        names.append("Win")
    if down(0x11):
        names.append("Ctrl")
    if down(0x12):
        names.append("Alt")
    if down(0x10):
        names.append("Shift")
    key = {"space": "Space", "Return": "Enter", "Prior": "PageUp", "Next": "PageDown"}.get(
        keysym, keysym)
    return "+".join(names + [key])
