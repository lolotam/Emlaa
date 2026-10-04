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


def _paste(mod_vk, key_vk, key_flags):
    """
    اللزق: modifier↓ · key↓ · key↑ · modifier↑. لو SendInput حقن أول الأحداث
    بس (جزء من التسلسل)، المفاتيح اللي اتدست من غير ما تنساب لازم تنساب —
    بنبعت key-up بتاعها (بأفضل جهد) وبنرجّع False. (F6: Ctrl/Shift ميفضلوش
    ماسكين لو الحقن قطع في النص.)
    """
    events = [
        _kb_event(mod_vk, 0, 0),
        _kb_event(key_vk, 0, key_flags),
        _kb_event(key_vk, 0, key_flags | KEYEVENTF_KEYUP),
        _kb_event(mod_vk, 0, KEYEVENTF_KEYUP),
    ]
    u = _user32()
    n = len(events)
    inserted = int(u.SendInput(n, (INPUT * n)(*events), ctypes.sizeof(INPUT)))
    if inserted == n:
        return True
    # المفاتيح اللي down اتحقن بس up لسه ما اتحقنش — بنرجع كل واحد up
    # بترتيب عكسي لترتيب الدوس، عشان الموديفاير مايفضلش ماسك.
    pressed = {}
    for ev in events[:inserted]:
        if ev.u.ki.dwFlags & KEYEVENTF_KEYUP:
            pressed.pop(ev.u.ki.wVk, None)
        else:
            pressed[ev.u.ki.wVk] = ev
    releases = [_kb_event(vk, 0, ev.u.ki.dwFlags | KEYEVENTF_KEYUP)
                for vk, ev in reversed(list(pressed.items()))]
    if releases:
        u.SendInput(len(releases), (INPUT * len(releases))(*releases),
                    ctypes.sizeof(INPUT))
    return False


def paste_ctrl_v():
    """Ctrl+V بأحداث SendInput (0x11↓ 0x56↓ 0x56↑ 0x11↑). True لو الكل اتحقن."""
    return _paste(VK_CONTROL, VK_V, 0)


def paste_shift_insert():
    """
    Shift+Insert — زرار اللزق اللي بيشتغل في الـconhost والـTerminals:
    0x10↓ · 0x2D↓ (EXTENDED) · 0x2D↑ · 0x10↑. True لو الكل اتحقن.
    """
    return _paste(VK_SHIFT, VK_INSERT, KEYEVENTF_EXTENDEDKEY)


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


# ── الكبسولة العائمة: منع تفعيل النافذة (WS_EX_NOACTIVATE) ────────────────────
# الكبسولة Toplevel بتبان فوق كل حاجة، بس كليك عليها كان بياخد الفوكس —
# والكلام المُملى بعدين بيتكتب جوّاها مش في البرنامج اللي قدام المستخدم.
# الحل: نضيف WS_EX_NOACTIVATE لطراز النافذة، فالماوس يوصل لزرار الإلغاء/
# الإنهاء والسحب عادي، بس النافذة عمرها ما بتاخد الفوكس ولا بتبقى الأمامية.

GWL_EXSTYLE      = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

# فلاجات SetWindowPos: بننده بيهم كلهم عشان تغيير الطراز يسري من غير ما
# النافذة تتحرّك أو تتنشّط أو يتغيّر ترتيبها
SWP_NOSIZE       = 0x0001
SWP_NOMOVE       = 0x0002
SWP_NOZORDER     = 0x0004
SWP_NOACTIVATE   = 0x0010
SWP_FRAMECHANGED = 0x0020
_STYLE_FLAGS = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED

# LONG_PTR بحجم المؤشر (32/64) — وهو اللي GetWindowLongPtrW/SetWindowLongPtrW بياخدوه
LONG_PTR = ctypes.c_ssize_t

_sty32 = None


def _style32():
    """ميتولّد مرة: argtypes/restype لدوال طراز النافذة — عشان النداءات تصح."""
    global _sty32
    if _sty32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetParent.argtypes = [wintypes.HWND]
        u.GetParent.restype = wintypes.HWND
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = LONG_PTR
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        u.SetWindowLongPtrW.restype = LONG_PTR
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos.restype = wintypes.BOOL
        _sty32 = u
    return _sty32


def toplevel_hwnd(widget):
    """الـHWND الفعلي لنافذة Toplevel في Tk — winfo_id بيشير لحاوية داخلية،
    فالوالد (GetParent) هو الـHWND اللي نعدّل عليه الطراز. بيرجّع 0 لو فشل."""
    try:
        widget.update_idletasks()
        return int(_style32().GetParent(widget.winfo_id()))
    except Exception:
        return 0


def set_no_activate(hwnd):
    """
    بيضيف WS_EX_NOACTIVATE لطراز النافذة. بيرجّع True لو اتطبق (أو متطبّق
    بالفعل)، وFalse من غير ما يرمي — كبسولة فشل تظبيطها لازم تفضل شغّالة.
    """
    try:
        u = _style32()
        if not hwnd:
            return False
        ctypes.set_last_error(0)
        style = int(u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        if style == 0 and ctypes.get_last_error():
            return False                  # hwnd مش صالح
        if style & WS_EX_NOACTIVATE:
            return True                   # متطبّق بالفعل
        ctypes.set_last_error(0)
        if int(u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)) == 0 \
                and ctypes.get_last_error():
            return False
        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _STYLE_FLAGS)
        return True
    except Exception as e:
        try:
            import core    # تأخير: core بيستورد winput جوّه دواله — مفيش دورة
            core.log_error(e, "overlay/noactivate")
        except Exception:
            pass
        return False



# Tk نفسه بيرد على WM_MOUSEACTIVATE بـ«فعّل» لنوافذه العلوية، وده بيتجاوز WS_EX_NOACTIVATE —
# اتجرّب فعليًا: الطراز متطبّق والكليك برضه خطف الفوكس. فبنلف إجراء النافذة (subclass):
# WM_MOUSEACTIVATE بيرجع MA_NOACTIVATE، وأي رسالة تانية بتعدّي لإجراء Tk الأصلي زي ما هي.
GWLP_WNDPROC     = -4
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE    = 3
LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_subclassed = {}   # hwnd → (الإجراء الجديد، الأصلي) — المرجع لازم يفضل عايش وإلا الـcallback يتمسح


def block_mouse_activate(hwnd):
    """
    الكليك على النافذة ميفعّلهاش أبدًا (WM_MOUSEACTIVATE → MA_NOACTIVATE)، والماوس
    يفضل يوصل للزراير والسحب عادي. مرة واحدة لكل نافذة؛ بيرجّع False من غير ما يرمي.
    """
    if not hwnd:
        return False
    if hwnd in _subclassed:
        return True
    try:
        u = _style32()
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
        u.CallWindowProcW.restype = LRESULT
        old = {}

        @_WNDPROC
        def proc(h, msg, wp, lp):
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            return u.CallWindowProcW(old["proc"], h, msg, wp, lp)

        ctypes.set_last_error(0)
        prev = int(u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p).value))
        if prev == 0 and ctypes.get_last_error():
            return False
        old["proc"] = prev
        _subclassed[hwnd] = (proc, prev)
        return True
    except Exception as e:
        try:
            import core
            core.log_error(e, "overlay/mouseactivate")
        except Exception:
            pass
        return False
