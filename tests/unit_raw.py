# -*- coding: utf-8 -*-
"""
اختبارات «التفريغ الحرفي» — زرار قايمة التراي بيقفل/يفتح «تنظيف النص»
(مفتاح polish). بنجرّب تاثيره على CFG وpayload الـpush على الواجهة
والقايمة نفسها. الـcontroller بيتبنى بـobject.__new__ من غير ما
البرنامج يبدأ (مفيش pywebview ولا Tk ولا تراي حقيقي)، والموجة
والـroot والـtray كلها مزيفة. رسم علامة «خام» فوق الموجة نفسه بيتأكد
باليد (Tk لازم يكون فيه شاشة) — مبيتنفذش هون.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core      # noqa: E402
import app_web   # noqa: E402


class FakeWave:
    """موجة عائلية مزيفة: بتسجّل كل نداء _draw (بالمستوى اللي جات بيه)."""

    def __init__(self, state="rec", lvl=0.4):
        self._state = state
        self._lvl = lvl
        self.draws = []

    def winfo_exists(self):
        return True

    def _draw(self, lvl):
        self.draws.append(lvl)


class FakeRoot:
    """Tk root مزيف: after() بيحفظ الـcallback عشان الاختبار ينفّذه بإيده."""

    def __init__(self):
        self.pending = []

    def after(self, ms, fn):
        self.pending.append(fn)


def make_ctrl(wave=None, tray=None, root=None):
    """Controller من غير __init__ — بس السمات اللي toggle_raw بيستخدمها."""
    c = object.__new__(app_web.Controller)
    c.root = root
    c.wave = wave
    c.tray = tray
    c.push_calls = []

    def push(fn, payload):
        c.push_calls.append((fn, payload))

    c.push = push
    return c


class _PolishGuard(unittest.TestCase):
    """بيتحكم على CFG وsave_config ويرجّعهم بعد كل اختبار."""

    def setUp(self):
        self._saved = dict(core.CFG)
        self.addCleanup(self._restore)
        p = mock.patch.object(core, "save_config")
        self.save = p.start()
        self.addCleanup(p.stop)

    def _restore(self):
        core.CFG.clear()
        core.CFG.update(self._saved)


class TestToggleRaw(_PolishGuard):
    def test_flip_off_saves_and_pushes_payload(self):
        core.CFG["polish"] = True
        tray = mock.Mock()
        c = make_ctrl(tray=tray)
        c.toggle_raw()
        self.assertIs(core.CFG["polish"], False)
        self.save.assert_called_once_with(core.CFG)
        self.assertEqual(c.push_calls, [("onConfig", {"polish": False})])
        tray.update_menu.assert_called_once_with()

    def test_flip_on_pushes_true(self):
        core.CFG["polish"] = False
        c = make_ctrl()
        c.toggle_raw()
        self.assertIs(core.CFG["polish"], True)
        self.assertEqual(c.push_calls, [("onConfig", {"polish": True})])

    def test_missing_key_defaults_to_polish(self):
        # config قديم من غير المفتاح: الافتراضي True، فالتبديل الأول بيأخده False
        core.CFG.pop("polish", None)
        c = make_ctrl()
        c.toggle_raw()
        self.assertIs(core.CFG["polish"], False)

    def test_no_tray_does_not_crash(self):
        core.CFG["polish"] = True
        c = make_ctrl(tray=None)
        c.toggle_raw()
        self.assertIs(core.CFG["polish"], False)
        self.assertEqual(c.push_calls, [("onConfig", {"polish": False})])

    def test_window_closed_push_is_noop(self):
        # لو النافذة مقفولة، push الحقيقي بيرجّع من غير نداء — الترتيب كله يتنفذ
        core.CFG["polish"] = True
        c = make_ctrl()
        c.push = app_web.Controller.push.__get__(c)
        c.window = None
        c.toggle_raw()
        self.assertIs(core.CFG["polish"], False)
        self.save.assert_called_once_with(core.CFG)


class TestWaveRedraw(_PolishGuard):
    """إعادة رسم الموجة بعد التبديل — بتمر عبر tk_call (ثريد Tk)."""

    def _toggle_and_run(self, wave, root):
        c = make_ctrl(wave=wave, root=root)
        c.toggle_raw()
        for fn in root.pending:
            fn()
        return wave

    def test_rec_wave_redraws_with_current_level(self):
        wave = self._toggle_and_run(FakeWave("rec", lvl=0.3), FakeRoot())
        self.assertEqual(wave.draws, [0.3])

    def test_work_wave_redraws_too(self):
        wave = self._toggle_and_run(FakeWave("work"), FakeRoot())
        self.assertEqual(len(wave.draws), 1)

    def test_idle_wave_not_redrawn(self):
        # الزرار الصغير (idle) لي رسم تاني — _draw هيرسم الكبسولة الكبيرة غلط فوقه
        wave = self._toggle_and_run(FakeWave("idle"), FakeRoot())
        self.assertEqual(wave.draws, [])

    def test_dead_wave_skipped(self):
        class Dead(FakeWave):
            def winfo_exists(self):
                return False
        wave = self._toggle_and_run(Dead(), FakeRoot())
        self.assertEqual(wave.draws, [])

    def test_no_root_redraw_moot(self):
        # مفيش ثريد Tk لسه: مفيش callback بيتنفذ، والموجة تتلمسش
        wave = FakeWave("rec")
        c = make_ctrl(wave=wave, root=None)
        c.toggle_raw()
        self.assertEqual(wave.draws, [])


class TestTrayMenuItem(_PolishGuard):
    def test_item_checkmark_follows_config(self):
        try:
            import pystray  # noqa: F401
        except ImportError:
            self.skipTest("pystray مش متساب")
        core.CFG["lang"] = "ar"
        c = make_ctrl()
        items = list(c._tray_menu().items)

        def raw_item():
            found = [i for i in items if "تفريغ حرفي" in i.text]
            self.assertEqual(len(found), 1)
            return found[0]

        core.CFG["polish"] = True
        self.assertIs(raw_item().checked, False)
        core.CFG["polish"] = False
        self.assertIs(raw_item().checked, True)


class TestEngineStartsOnce(unittest.TestCase):
    """أكتر من نداء start_engine (إضافة مفتاح + حفظ) وهو لسه بيقوم = محرك واحد بس."""

    def test_second_start_while_booting_is_ignored(self):
        c = object.__new__(app_web.Controller)
        c.engine = None
        with mock.patch.object(app_web.threading, "Thread") as thread:
            c.start_engine()
            c.start_engine()
        self.assertEqual(thread.call_count, 1)

    def test_hotkey_failure_at_boot_leaves_no_engine_so_a_later_start_retries(self):
        # PR #15 (CodeRabbit): الـengine كان بيتسجّل قبل start_hotkey — لو فشل، الحارس كان بيرفض أي محاولة تانية
        c = object.__new__(app_web.Controller)
        c.engine, c.root = None, None
        c.set_state = mock.Mock()
        app = mock.Mock()
        app.start_hotkey.side_effect = OSError("hook")
        threads = []

        def thread(target=None, daemon=None):
            threads.append(target)
            return mock.Mock(start=target)

        with mock.patch.object(app_web.core, "App", return_value=app), \
                mock.patch.object(app_web.core, "log_error"), \
                mock.patch.object(app_web.threading, "Thread", side_effect=thread):
            c.start_engine()
            self.assertIsNone(c.engine)
            app.shutdown.assert_called_once()
            c.start_engine()
        self.assertEqual(len(threads), 2)


class TestQuitFlushesSettings(unittest.TestCase):
    """PR #16 (Codex): «خروج» من التراي بيستنى الواجهة تخلّص حفظ الإعدادات قبل ما يقفل."""

    def controller(self, window):
        c = object.__new__(app_web.Controller)
        c._quitting, c.tray, c.engine, c._open_hk, c.clip, c.root = False, None, None, None, None, None
        c.window = window
        return c

    def test_quit_waits_for_the_ui_flush_before_destroying_the_window(self):
        order = []
        window = mock.Mock()
        window.evaluate_js.side_effect = lambda script, callback: (order.append("flush"), callback(None))
        window.destroy.side_effect = lambda: order.append("destroy")
        self.controller(window).quit()
        self.assertEqual(order, ["flush", "destroy"])
        self.assertIn("flushSave", window.evaluate_js.call_args.args[0])

    def test_quit_still_closes_when_the_ui_cannot_flush(self):
        window = mock.Mock()
        window.evaluate_js.side_effect = RuntimeError("window gone")
        with mock.patch.object(app_web.core, "log_error"):
            self.controller(window).quit()
        window.destroy.assert_called_once()
