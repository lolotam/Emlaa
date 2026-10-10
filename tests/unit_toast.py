# -*- coding: utf-8 -*-
"""
رسالة «النص ما اتكتبش» (ResultToast): الإملاء مبيتنسخش لوحده — النسخ بزرار جوّه الرسالة،
والرسالة بتختفي بعد ٣ ثواني إلا لو الماوس عليها. ويندوز بس (Tk حقيقي مخفي).
الحافظة نفسها مش بتتلمس: clipboard_* بتاعة Tk متبدّلة بـmock.
"""
import gc
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import tkinter as tk  # noqa: E402
import emlaa  # noqa: E402


@unittest.skipUnless(os.name == "nt", "Tk حقيقي — ويندوز بس")
class TestResultToast(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.toast = emlaa.ResultToast(self.root, "نص الإملاء")

    def tearDown(self):
        for w in (self.toast, self.root):
            try:
                w.destroy()
            except Exception:
                pass
        self.toast = self.root = None
        gc.collect()

    def test_copy_button_copies_text_and_confirms(self):
        self.assertEqual(self.toast.copy_btn.cget("text"), self.toast._t("نسخ", "Copy"))
        with mock.patch.object(self.toast, "clipboard_clear"), \
                mock.patch.object(self.toast, "clipboard_append") as append:
            self.toast._copy()
        append.assert_called_once_with("نص الإملاء")
        self.assertEqual(self.toast.copy_btn.cget("text"), self.toast._t("✓ اتنسخ", "✓ Copied"))

    def test_stays_while_hovered_then_closes(self):
        self.toast._hover = True
        self.toast._expire()
        self.assertTrue(self.toast.winfo_exists(), "الماوس على الرسالة = تفضل")
        self.toast._hover = False
        self.toast._expire()
        self.assertFalse(self.toast.winfo_exists())


@unittest.skipUnless(os.name == "nt", "Tk حقيقي — ويندوز بس")
class TestFailedToast(unittest.TestCase):
    """تسجيل فشل واتحفظ: الرسالة بتقول السبب، و«افتح السجل» بيودّي للتسجيل."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.opened = []
        self.toast = emlaa.FailedToast(self.root, "مفيش اتصال بالنت", lambda: self.opened.append(1))

    def tearDown(self):
        for w in (self.toast, self.root):
            try:
                w.destroy()
            except Exception:
                pass
        self.toast = self.root = None
        gc.collect()

    def test_open_history_button_opens_it_and_closes(self):
        self.toast._open()
        self.assertEqual(self.opened, [1])
        self.assertFalse(self.toast.winfo_exists())

    def test_stays_while_hovered_then_closes(self):
        self.toast._hover = True
        self.toast._expire()
        self.assertTrue(self.toast.winfo_exists())
        self.toast._hover = False
        self.toast._expire()
        self.assertFalse(self.toast.winfo_exists())


if __name__ == "__main__":
    unittest.main()
