# -*- coding: utf-8 -*-
"""
winput.write_clipboard_text: الفحص (رقم التسلسل) والكتابة والحافظة مفتوحة طول الوقت —
مفيش برنامج تاني يقدر يكتب بينهم (PR #14، Codex P2). و winput.wait_responsive: هل
البرنامج اللي قدام المستخدم بيرد (مش مهنّج) قبل ما نرجّع الحافظة (PR #14، Codex P1).
مفيش حافظة حقيقية: user32/kernel32 مزيّفين.
"""
import ctypes
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import winput  # noqa: E402


class FakeUser32:
    def __init__(self, seq=7, open_ok=True, responsive=True):
        self.seq, self.open_ok, self.responsive = seq, open_ok, responsive
        self.calls, self.data = [], None

    def CreateWindowExW(self, *args):
        self.calls.append("create")
        return 99

    def DestroyWindow(self, hwnd):
        self.calls.append("destroy")
        return 1

    def OpenClipboard(self, hwnd):
        self.calls.append(("open", hwnd))
        return self.open_ok

    def CloseClipboard(self):
        self.calls.append("close")
        return 1

    def GetClipboardSequenceNumber(self):
        return self.seq

    def EmptyClipboard(self):
        self.calls.append("empty")
        return 1

    def SetClipboardData(self, fmt, handle):
        self.calls.append(("set", fmt))
        self.data = handle
        return handle

    def SendMessageTimeoutW(self, hwnd, msg, wparam, lparam, flags, timeout, result):
        self.calls.append(("ping", hwnd, timeout))
        return 1 if self.responsive else 0


class FakeKernel32:
    """GlobalAlloc حقيقي على buffer من ctypes — عشان نقرا النص اللي اتكتب."""

    def __init__(self, alloc_ok=True):
        self.buffers, self.alloc_ok = {}, alloc_ok

    def GlobalAlloc(self, flags, size):
        if not self.alloc_ok:
            return None
        h = len(self.buffers) + 1
        self.buffers[h] = ctypes.create_string_buffer(size)
        return h

    def GlobalLock(self, h):
        return ctypes.addressof(self.buffers[h])

    def GlobalUnlock(self, h):
        return 1

    def GlobalFree(self, h):
        self.buffers.pop(h, None)
        return None

    def text(self, h):
        return self.buffers[h].raw.decode("utf-16-le").rstrip("\x00")


class TestWriteClipboardText(unittest.TestCase):
    def write(self, text, expect_seq=None, alloc_ok=True, **u32):
        self.u, self.k = FakeUser32(**u32), FakeKernel32(alloc_ok)
        with mock.patch.object(winput, "_clipboard32", return_value=self.u), \
                mock.patch.object(winput, "_kernel32", return_value=self.k), \
                mock.patch.object(winput.time, "sleep"):
            return winput.write_clipboard_text(text, expect_seq)

    def test_writes_unicode_text_while_clipboard_is_open(self):
        self.assertTrue(self.write("نص Docker"))
        self.assertEqual(self.k.text(self.u.data), "نص Docker")
        self.assertEqual(self.u.calls, ["create", ("open", 99), "empty",
                                        ("set", winput.CF_UNICODETEXT), "close", "destroy"])

    def test_sequence_changed_writes_nothing(self):
        # حد نسخ بعد ما قرينا الرقم — الحافظة مفتوحة وقت الفحص، فمنكتبش فوقه
        self.assertFalse(self.write("نص", expect_seq=6, seq=7))
        self.assertNotIn("empty", self.u.calls)
        self.assertIsNone(self.u.data)
        self.assertEqual(self.u.calls[-2:], ["close", "destroy"])

    def test_allocation_failure_leaves_clipboard_untouched(self):
        # PR #14 (Codex P2): الذاكرة بتتحجز قبل EmptyClipboard — فشلها ميمسحش حافظة المستخدم
        with self.assertRaises(OSError):
            self.write("نص", alloc_ok=False)
        self.assertNotIn("empty", self.u.calls)
        self.assertNotIn(("open", 99), self.u.calls)

    def test_sequence_changed_frees_the_unused_block(self):
        self.write("نص", expect_seq=6, seq=7)
        self.assertEqual(self.k.buffers, {})

    def test_matching_sequence_writes(self):
        self.assertTrue(self.write("نص", expect_seq=7, seq=7))
        self.assertEqual(self.k.text(self.u.data), "نص")

    def test_empty_text_only_empties_clipboard(self):
        self.assertTrue(self.write(""))
        self.assertIn("empty", self.u.calls)
        self.assertIsNone(self.u.data)

    def test_clipboard_busy_raises_and_destroys_window(self):
        with self.assertRaises(OSError):
            self.write("نص", open_ok=False)
        self.assertNotIn("empty", self.u.calls)
        self.assertEqual(self.u.calls[-1], "destroy")


class TestWaitResponsive(unittest.TestCase):
    def ping(self, hwnd, **u32):
        self.u = FakeUser32(**u32)
        with mock.patch.object(winput, "_clipboard32", return_value=self.u):
            return winput.wait_responsive(hwnd, 5000)

    def test_responsive_window(self):
        self.assertTrue(self.ping(42))
        self.assertEqual(self.u.calls, [("ping", 42, 5000)])

    def test_hung_window(self):
        self.assertFalse(self.ping(42, responsive=False))

    def test_no_window_is_not_responsive(self):
        self.assertFalse(self.ping(0))
        self.assertEqual(self.u.calls, [])


if __name__ == "__main__":
    unittest.main()
