# -*- coding: utf-8 -*-
"""
أحداث الكيبورد التركيبية على ويندوز (SendInput) وحالة مفاتيح القفل
------------------------------------------------------------------
طبقة أثر جانبي (side effects) واحدة بس، ومنفصلة عن منطق القرار:
  • «mask» زرار الـAlt: لما يكون Alt هو زرار التسجيل، أول دوسة عليه بنبعت
    معاها دوسة VK_MASK (مفتاح مالوش معنى)، فسيبان Alt مايفتحش قايمة البرنامج.
  • مفاتيح القفل (Caps Lock / Scroll Lock) لو اتستخدموا كزرار تسجيل:
    كل دوسة حقيقية بتقلب حالة القفل مرة، فعند التسيب بنرجّعها بدوسة واحدة
    (send_vk).

كل حدث تركيبة عليه dwExtraInfo = EMLAA_TAG، وفلتر win32_event_filter
جوّه start_hotkey بيرفضه (يرجع False) عشان منطق زرار التسجيل
ميسمعش نفسه. مفيش suppress_event: مفاتيح المستخدم الحقيقية مابتتكتش
الأساس أبداً.

الاستيراد الوحيد هنا من جوّه start_hotkey في core — smart.py ماتلمستش
الحاجة دي خالص (smart قرار نقي، وده أثر جانبي).
"""
import ctypes
from ctypes import wintypes

# علامة أحداثنا التركيبية ("EMLA" بالـhex) — أي حدث عليه الوسم ده
# ماسيبتوش من فلتر الـlistener.
EMLAA_TAG = 0x454D4C41

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# مفتاح مالوش معنى (unassigned): لما يتداس وAlt ماسك، ويندوز ميعتبرش سيبان Alt
# «دوسة Alt لوحدها»، فالبرنامج مايدخلش وضع القايمة — نفس MenuMaskKey بتاع AutoHotkey.
# (لازم مايكونش Alt نفسه: Alt تركيبي بيقول للويندوز إن Alt اتساب والمستخدم لسه ماسكه.)
VK_MASK = 0xE8
VK_CAPS_LOCK = 0x14
VK_SCROLL_LOCK = 0x91


# ── بنية INPUT ────────────────────────────────────────────────────────────────
# اليونين لازم فيّه أكبر عضو (MOUSEINPUT) — لو بنيناها على KEYBDINPUT بس
# يبقى sizeof(INPUT) غلط، وSendInput بيرجع 0 في صمت ومش هتعرف إن مفيش
# حاجة اتبعت.
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT)]


# dwExtraInfo حجمه ULONG_PTR: على 64-bit بيت 8 بايت، فـsizeof(INPUT)
# بيبقى 40 (28 على 32-bit) — الاختبار بيتأكد من ده في unit_hotkey.
class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD),
                ("u", _INPUT_UNION)]


_u32 = None


def _user32():
    """ميتولّد مرة (بيتخزن في _u32) — argtypes/restype اللازمين لصحة النداء."""
    global _u32
    if _u32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        u.SendInput.restype = wintypes.UINT
        _u32 = u
    return _u32


def send_vk(vk):
    """
    يرسل دوسة زر كاملة (down ثم up) للمفتاح vk، وعلامة EMLAA_TAG.
    بيرجّع عدد الأحداث اللي SendInput حقنها فعلاً (0 = مفيش حاجة اتبعت).
    """
    u = _user32()

    def event(key_up):
        ev = INPUT()
        ev.type = INPUT_KEYBOARD
        ev.u.ki.wVk = vk
        ev.u.ki.dwFlags = KEYEVENTF_KEYUP if key_up else 0
        ev.u.ki.dwExtraInfo = EMLAA_TAG
        return ev

    events = (INPUT * 2)(event(False), event(True))
    return int(u.SendInput(2, events, ctypes.sizeof(INPUT)))

