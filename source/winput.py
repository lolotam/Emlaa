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

الاستيراد من جوّه دوال core (start_hotkey وخط الكتابة في paste_text)
— وبيستخدم smart.TERMINAL_CLASSES لقرار «قابل للكتابة» في
focused_info: الكلاسات دي بيانات قرار، ومصدر واحد للجانبين.
"""
import ctypes
from ctypes import wintypes

import smart

# علامة أحداثنا التركيبية ("EMLA" بالـhex) — أي حدث عليه الوسم ده
# ماسيبتوش من فلتر الـlistener.
EMLAA_TAG = 0x454D4C41

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
# KEYEVENTF_UNICODE: الحدث حرف مش مفتاح — wVk بيتصفر وwScan ياخد
# كود وحدة UTF-16، وده اللي بيمكّن كتابة العربي والإيموجي زي ما هي.
KEYEVENTF_UNICODE = 0x0004

# كتابة Unicode على دفعات: كل دفعة 64 حرف أو أقل. SendInput بيعترض
# الصفوف الطويلة، والحد ده مايشيلهش. حدود الدفعة بترجع «حرف» مش
# «وحدة»: الحرف اللي برا الـBMP (إيموجي) بيوكّده شيفرات surrogate
# اتنين، وقسمتهم على دفعتين كان هيكسر الحرف.
TYPE_CHUNK = 64

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_V = 0x56
VK_INSERT = 0x2D

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


def _kb_event(w_vk, w_scan, flags):
    """حدث كيبورد تركيبي واحد عليه EMLAA_TAG — فلتر التسجيل بيرفضه."""
    ev = INPUT()
    ev.type = INPUT_KEYBOARD
    ev.u.ki.wVk = w_vk
    ev.u.ki.wScan = w_scan
    ev.u.ki.dwFlags = flags
    ev.u.ki.dwExtraInfo = EMLAA_TAG
    return ev


def _send(events):
    """
    بحقن قائمة أحداث بيرجّع True بس لو SendInput حقن كلها:
    عدد أقل من اللي اتبعت = الصف رفض حاجة في النص — بنعتبرها فشل
    ومبنعيدش إرسال (R1 #12: مفيش replay بعد كتابة جزئية).
    """
    u = _user32()
    n = len(events)
    return int(u.SendInput(n, (INPUT * n)(*events), ctypes.sizeof(INPUT))) == n


def type_text(text):
    """
    كتابة نص Unicode أحداث SendInput: لكل وحدة UTF-16 حدث down (wVk=0,
    wScan=الوحدة, KEYEVENTF_UNICODE) وحدث up، على دفعات TYPE_CHUNK حرف.
    بيرجّع True لو كل الأحداث اتحقنت، وFalse عند أول دفعة قصرت —
    بدون أي إعادة إرسال للباقي.
    """
    text = text or ""
    if not text:
        return True
    for i in range(0, len(text), TYPE_CHUNK):
        chunk = text[i:i + TYPE_CHUNK]
        evs = []
        # الترميز بعد التقسيم بالحرف: الحرف الواسع (surrogate pair)
        # عمره ما يتقسم على دفعتين
        data = chunk.encode("utf-16-le")
        for j in range(0, len(data), 2):
            unit = data[j] | (data[j + 1] << 8)
            evs.append(_kb_event(0, unit, KEYEVENTF_UNICODE))
            evs.append(_kb_event(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if not _send(evs):
            return False
    return True


def paste_ctrl_v():
    """Ctrl+V بأحداث SendInput (0x11↓ 0x56↓ 0x56↑ 0x11↑). True لو الكل اتحقن."""
    return _send([
        _kb_event(VK_CONTROL, 0, 0),
        _kb_event(VK_V, 0, 0),
        _kb_event(VK_V, 0, KEYEVENTF_KEYUP),
        _kb_event(VK_CONTROL, 0, KEYEVENTF_KEYUP),
    ])


def paste_shift_insert():
    """
    Shift+Insert — زرار اللزق اللي بيشتغل في الـconhost والـTerminals:
    0x10↓ · 0x2D↓ (EXTENDED) · 0x2D↑ · 0x10↑. True لو الكل اتحقن.
    """
    return _send([
        _kb_event(VK_SHIFT, 0, 0),
        _kb_event(VK_INSERT, 0, KEYEVENTF_EXTENDEDKEY),
        _kb_event(VK_INSERT, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP),
        _kb_event(VK_SHIFT, 0, KEYEVENTF_KEYUP),
    ])


# معرّفات خصائص UIA: IsPassword 30019 · IsValuePatternAvailable 30043 ·
# IsTextPatternAvailable 30040 · ValueIsReadOnly 30046 ·
# ControlType Edit 50004 / Document 50030
def focused_info():
    """
    (F3) خصائص العنصر المركّز بنداء UIA واحد — بيحط محل جسم
    has_text_focus القديم وبيزوّد is_password:
      is_password — IsPassword (30019)؛ None = ماتعرفناش
      class       — اسم كلاسم العنصر
      editable    — نفس قرار «قابل للكتابة» القديم بالظبط؛
                    None = UIA فشل واللي بيراح يتعامل «gui» مش «secure»
    عمره ما يرمي خطأ: أي فشل بيرجّع القمطة كلها بقيم None.
    """
    out = {"is_password": None, "class": "", "editable": None}
    try:
        import comtypes, comtypes.client
        comtypes.CoInitialize()             # كل تسجيل بيتعالج في ثريد جديد — COM لازم يتعمل لكل ثريد
        from comtypes.gen.UIAutomationClient import IUIAutomation, CUIAutomation
        uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        el = uia.GetFocusedElement()
        if not el:
            out["editable"] = False
            return out
        out["class"] = el.CurrentClassName or ""
        out["is_password"] = bool(el.GetCurrentPropertyValue(30019))
        # الترمنال (Windows Terminal / cmd / ConEmu / mintty) مش بيقول عن نفسه إنه خانة كتابة
        if out["class"] in smart.TERMINAL_CLASSES:
            out["editable"] = True
        elif el.GetCurrentPropertyValue(30043):
            out["editable"] = not el.GetCurrentPropertyValue(30046)
        elif el.CurrentControlType == 50004:                                    # Edit
            out["editable"] = True
        elif el.CurrentControlType == 50030 and el.GetCurrentPropertyValue(30040):  # Document بنص
            out["editable"] = True
        else:
            out["editable"] = False
        return out
    except Exception as e:
        try:
            import core    # تأخير: core بيستورد winput جوّه دواله — مفيش دورة
            core.log_error(e, "focus/uia")
        except Exception:
            pass
        return out

