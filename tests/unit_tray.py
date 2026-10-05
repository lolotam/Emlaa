# -*- coding: utf-8 -*-
"""
اختبارات Task 19 — core.import_pystray (سباق استيراد التراي #6).
مفيش تراي حقيقي: بنزوّد __import__ مزيّف عشان الاستيراد يفشل/ينجح من غير pystray فعلي.
"""
import os
import sys
import time
import types
import builtins
import threading
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core  # noqa: E402


def _fake_module(name):
    mod = types.ModuleType(name)
    mod._fake = True
    return mod


class TestImportPystray(unittest.TestCase):
    def setUp(self):
        # الاختبارات بتحط pystray مزيّف والإعادة بتشيل six.* الحقيقية من sys.modules —
        # بنرجّع sys.modules زي ما كان عشان باقي الاختبارات (pynput محتاج six.moves) ماتتأثرش
        p = mock.patch.dict(sys.modules)
        p.start()
        self.addCleanup(p.stop)
        sleep = mock.patch.object(core.time, "sleep")   # مهلة الإعادة (0.3 ث) مالهاش لازمة هنا
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_retry_succeeds_after_one_importerror(self):
        fake = _fake_module("pystray")
        real_import = builtins.__import__
        state = {"calls": 0}

        def fake_import(name, *a, **k):
            if name == "pystray":
                state["calls"] += 1
                if state["calls"] == 1:
                    raise ImportError("No module named 'six.moves'; 'six' is not a package")
                sys.modules["pystray"] = fake
                return fake
            return real_import(name, *a, **k)

        with mock.patch("builtins.__import__", fake_import):
            self.assertIs(core.import_pystray(), fake)
        self.assertEqual(state["calls"], 2)

    def test_second_failure_propagates(self):
        real_import = builtins.__import__
        state = {"calls": 0}

        def fake_import(name, *a, **k):
            if name == "pystray":
                state["calls"] += 1
                raise ImportError("six is broken")
            return real_import(name, *a, **k)

        with mock.patch("builtins.__import__", fake_import):
            with self.assertRaises(ImportError):
                core.import_pystray()
        self.assertEqual(state["calls"], 2)

    def test_concurrent_callers_get_one_module(self):
        fake = _fake_module("pystray")
        real_import = builtins.__import__
        state = {"inside": 0, "max_inside": 0}
        state_lock = threading.Lock()

        def fake_import(name, *a, **k):
            if name == "pystray":
                with state_lock:
                    state["inside"] += 1
                    state["max_inside"] = max(state["max_inside"], state["inside"])
                time.sleep(0.02)      # مساحة للتداخل لو مفيش قفل
                with state_lock:
                    state["inside"] -= 1
                sys.modules["pystray"] = fake
                return fake
            return real_import(name, *a, **k)

        results = []
        with mock.patch("builtins.__import__", fake_import):
            threads = [threading.Thread(target=lambda: results.append(core.import_pystray()))
                       for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)

        self.assertEqual(state["max_inside"], 1)          # القفل منع الاستيراد المتوازي
        self.assertEqual(len(set(map(id, results))), 1)   # كلهم واخدين نفس الموديول


if __name__ == "__main__":
    unittest.main()
