# -*- coding: utf-8 -*-
"""
اختبار الكبسولة العائمة ما تاخدش الفوكس (Task 10).

بس على ويندوز (os.name == "nt"): بيبني نافذة Tk حقيقية مخفية وكبسولة
WaveOverlay، وبيتأكد إن الـexstyle فيه WS_EX_NOACTIVATE بعد الظهور، وإنه
لسه موجود بعد الإخفاء والظهور تاني. مفيش شبكة ولا مفاتيح ولا ميكروفون.
"""
import os
import sys
import unittest

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import tkinter as tk  # noqa: E402

import winput  # noqa: E402
import emlaa   # noqa: E402


@unittest.skipUnless(os.name == "nt", "ويندوز بس — بيستدعي user32")
class TestSetNoActivateInvalid(unittest.TestCase):
    """set_no_activate على hwnd غلط بيرجّع False من غير ما يرمي."""

    def test_invalid_hwnd_returns_false(self):
        self.assertFalse(winput.set_no_activate(0))


@unittest.skipUnless(os.name == "nt", "كبسولة Tk حقيقية — ويندوز بس")
class TestOverlayNoActivate(unittest.TestCase):
    """الكبسولة لازم تفضل بلا تفعيل بعد الظهور وبعد إعادة الظهور."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = emlaa.WaveOverlay(self.root)

    def tearDown(self):
        # عشان _on_destroy ماتسجّلش «الموجة اتدمّرت» — إحنا اللي بنقفل عادي
        self.root._quitting = True
        try:
            self.overlay.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _exstyle(self):
        hwnd = winput.toplevel_hwnd(self.overlay)
        return int(winput._style32().GetWindowLongPtrW(hwnd, winput.GWL_EXSTYLE))

    def test_noactivate_set_on_show(self):
        self.overlay.show()
        self.assertTrue(self._exstyle() & winput.WS_EX_NOACTIVATE)

    def test_noactivate_still_set_after_hide_and_reshow(self):
        self.overlay.show()
        self.overlay.hide()
        self.overlay.show()
        self.assertTrue(self._exstyle() & winput.WS_EX_NOACTIVATE)


@unittest.skipUnless(os.name == "nt", "كبسولة Tk حقيقية — ويندوز بس")
class TestOverlayMouseActivate(unittest.TestCase):
    """Tk بيرد على WM_MOUSEACTIVATE بـ«فعّل» ويتجاوز WS_EX_NOACTIVATE — لازم الرد يبقى MA_NOACTIVATE."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = emlaa.WaveOverlay(self.root)

    def tearDown(self):
        self.root._quitting = True
        for w in (self.overlay, self.root):
            try:
                w.destroy()
            except Exception:
                pass

    def _ask(self):
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32")
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.restype = ctypes.c_ssize_t
        hwnd = winput.toplevel_hwnd(self.overlay)
        # HTCLIENT (1) + WM_LBUTTONDOWN (0x201) — زي كليك حقيقي على الكبسولة
        return u.SendMessageW(hwnd, winput.WM_MOUSEACTIVATE, hwnd, (0x201 << 16) | 1)

    def test_click_never_activates(self):
        self.overlay.show()
        self.assertEqual(self._ask(), winput.MA_NOACTIVATE)

    def test_still_blocked_after_hide_and_reshow(self):
        self.overlay.show()
        self.overlay.hide()
        self.overlay.show()
        self.assertEqual(self._ask(), winput.MA_NOACTIVATE)

    def test_invalid_hwnd(self):
        self.assertFalse(winput.block_mouse_activate(0))
