# -*- coding: utf-8 -*-
"""
اختبارات منطق زرار التسجيل (HotkeyLogic في smart.py) — القرار النقي عن
الدوس/التسيب. مفيش pynput ولا مفاتيح حقيقية ولا لينت: المفاتيح قيم
عادية قابلة للتجزئة (كلمات زي "ctrl_r") والوقت جاي حجة صريحة (now).
"""
import os
import sys
import unittest

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart  # noqa: E402


class TestToggleMode(unittest.TestCase):
    """سلوك وضع toggle الحالي — «دوسة نضيفة» بس هي اللي تعمل حاجة:
    أي كورد أو مسكة أطول من TAP_MAX مهمل خالص."""

    def make(self):
        return smart.HotkeyLogic({"ctrl_r": "normal", "alt_r": "prompt"}, "toggle")

    def test_clean_tap_starts(self):
        lg = self.make()
        self.assertEqual(lg.press("ctrl_r", 0.0, False, False), [])
        self.assertEqual(lg.release("ctrl_r", 0.1, False, False), ["begin:normal"])

    def test_clean_tap_on_any_button_stops(self):
        # الدوسة النضيفة اللي بتمّي التسجيل ممكن تكون على زرار تاني عن اللي بدأ بيه
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.release("ctrl_r", 0.1, False, False)
        lg.press("alt_r", 0.5, True, False)
        self.assertEqual(lg.release("alt_r", 0.6, True, False), ["end"])

    def test_chord_never_starts(self):
        # زرار اتداس معاه حرف (Ctrl+C) معناه المستخدم بكتب أو بيعمل اختصار
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.press("c", 0.05, False, False)
        self.assertEqual(lg.release("ctrl_r", 0.1, False, False), [])

    def test_hold_longer_than_tap_max_never_starts(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        self.assertEqual(lg.release("ctrl_r", smart.TAP_MAX + 0.1, False, False), [])

    def test_auto_repeat_same_key_stays_clean(self):
        # التكرار التلقائي للكيبورد وهو ماسك الزرار مايتحسبش دوسة جديدة
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.press("ctrl_r", 0.1, False, False)
        self.assertEqual(lg.release("ctrl_r", 0.2, False, False), ["begin:normal"])

    def test_two_hotkeys_held_spoil_both(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.press("alt_r", 0.05, False, False)
        self.assertEqual(lg.release("alt_r", 0.1, False, False), [])
        self.assertEqual(lg.release("ctrl_r", 0.15, False, False), [])

    def test_release_unknown_key_is_noop(self):
        lg = self.make()
        self.assertEqual(lg.press("c", 0.0, False, False), [])
        self.assertEqual(lg.release("c", 0.1, False, False), [])

    def test_busy_blocks_start_but_not_stop(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, True)
        self.assertEqual(lg.release("ctrl_r", 0.1, False, True), [])
        lg.press("alt_r", 0.5, True, True)
        self.assertEqual(lg.release("alt_r", 0.6, True, True), ["end"])

    def test_next_clean_tap_after_spoiled_cycle_still_works(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.press("c", 0.05, False, False)
        self.assertEqual(lg.release("ctrl_r", 0.1, False, False), [])
        lg.press("ctrl_r", 1.0, False, False)
        self.assertEqual(lg.release("ctrl_r", 1.1, False, False), ["begin:normal"])


class TestHoldMode(unittest.TestCase):
    """وضع hold — دوسة تبدأ وتسيب نفس الزرار يوقف. الجديدي:
    أي زرار تاني اتداس والتسجيل شغال = cancel (الصوت بيترمي بهدوء)."""

    def make(self):
        return smart.HotkeyLogic({"ctrl_r": "normal", "alt_r": "prompt"}, "hold")

    def test_press_starts_release_of_same_key_ends(self):
        lg = self.make()
        self.assertEqual(lg.press("ctrl_r", 0.0, False, False), ["begin:normal"])
        self.assertEqual(lg.press("ctrl_r", 0.2, True, False), [])  # تكرار تلقائي وهو ماسك
        self.assertEqual(lg.release("ctrl_r", 0.5, True, False), ["end"])

    def test_no_double_begin_while_recording(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        self.assertEqual(lg.press("ctrl_r", 0.3, True, False), [])
        self.assertEqual(lg.press("ctrl_r", 0.4, True, False), [])

    def test_other_key_press_cancels_while_recording(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        self.assertEqual(lg.press("a", 0.1, True, False), ["cancel"])

    def test_other_hotkey_press_cancels_too(self):
        # «أي زرار تاني» — حتى لو زرار تسجيل تاني مش حرف
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        self.assertEqual(lg.press("alt_r", 0.1, True, False), ["cancel"])

    def test_cancel_fires_once_only(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.press("a", 0.1, True, False)
        self.assertEqual(lg.press("b", 0.2, False, False), [])

    def test_no_cancel_when_not_recording(self):
        lg = self.make()
        self.assertEqual(lg.press("a", 0.0, False, False), [])

    def test_auto_repeat_after_cancel_does_not_rebegin(self):
        # لسه ماسك زرار التسجيل بعد الـcancel: التكرار التلقائي
        # مايشغلش تسجيل جديد — غير كده كان هيبقى دوّامة دوس/إلغاء
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        lg.press("a", 0.1, True, False)
        self.assertEqual(lg.press("ctrl_r", 0.2, False, False), [])
        lg.release("ctrl_r", 0.3, False, False)
        # الدوسة النضيفة الجديدة بعد كده تبدأ عادي
        self.assertEqual(lg.press("ctrl_r", 0.5, False, False), ["begin:normal"])

    def test_release_of_other_key_never_ends(self):
        lg = self.make()
        lg.press("ctrl_r", 0.0, False, False)
        self.assertEqual(lg.release("a", 0.2, True, False), [])
        self.assertEqual(lg.release("ctrl_r", 0.3, True, False), ["end"])

    def test_busy_blocks_hold_start(self):
        lg = self.make()
        self.assertEqual(lg.press("ctrl_r", 0.0, False, True), [])
        self.assertEqual(lg.release("ctrl_r", 0.1, False, True), [])

    def test_press_while_recording_starts_nothing(self):
        lg = self.make()
        self.assertEqual(lg.press("ctrl_r", 0.0, True, False), [])


class TestAltMask(unittest.TestCase):
    """الـAlt كزرار تسجيل: كل دوسة عليه (down) تنزل «mask» قبل أي
    إجراء تاني — في الاتنين الوضعين، وحتى لو اتحولت لكورد."""

    def make(self, mode):
        return smart.HotkeyLogic({"ctrl_r": "normal", "alt_r": "prompt",
                                  "alt_gr": "translate"}, mode,
                                 alt_keys={"alt_r", "alt_gr"})

    def test_hold_mask_comes_before_begin(self):
        lg = self.make("hold")
        self.assertEqual(lg.press("alt_r", 0.0, False, False), ["mask", "begin:prompt"])

    def test_toggle_mask_on_press_none_on_release(self):
        lg = self.make("toggle")
        self.assertEqual(lg.press("alt_gr", 0.0, False, False), ["mask"])
        self.assertEqual(lg.release("alt_gr", 0.1, False, False), ["begin:translate"])

    def test_mask_even_when_it_becomes_a_chord(self):
        lg = self.make("toggle")
        self.assertEqual(lg.press("alt_r", 0.0, False, False), ["mask"])
        lg.press("b", 0.05, False, False)
        # الكورد بقى — الدوسة ما تتحسبش، بس الـmask نزل وقت الدوسة نفسها
        self.assertEqual(lg.release("alt_r", 0.1, False, False), [])

    def test_non_alt_hotkey_has_no_mask(self):
        lg = self.make("hold")
        self.assertEqual(lg.press("ctrl_r", 0.0, False, False), ["begin:normal"])

    def test_unrelated_alt_key_press_has_no_mask(self):
        # الـmask ليهم بس اللي هم زراير التسجيل نفسها — مش أي Alt في الدنيا
        lg = self.make("hold")
        self.assertEqual(lg.press("shift_l", 0.0, False, False), [])


@unittest.skipUnless(os.name == "nt", "وحدات ويندوز — وفحص الحجم من غير ما نرسل حاجة")
class TestWinputStructs(unittest.TestCase):
    """حجم البنية والثوابت بس: مفيش SendInput حقيقي في الاختبارات."""

    def test_input_size(self):
        import ctypes
        import winput
        # على 64-bit: 4 (type) + 4 (pad) + 32 (union) = 40
        expected = 40 if sys.maxsize > 2 ** 32 else 28
        self.assertEqual(ctypes.sizeof(winput.INPUT), expected)

    def test_tag_value(self):
        import winput
        self.assertEqual(winput.EMLAA_TAG, 0x454D4C41)

    def test_lock_key_vks(self):
        import winput
        self.assertEqual(winput.VK_CAPS_LOCK, 0x14)
        self.assertEqual(winput.VK_SCROLL_LOCK, 0x91)


class TestAutoRepeatHasNoMask(unittest.TestCase):
    """التكرار التلقائي وهو ماسك Alt (~30 مرة في الثانية) مايبعتش mask كل مرة."""

    def test_hold_repeat(self):
        lg = smart.HotkeyLogic({"alt_r": "normal"}, "hold", alt_keys={"alt_r"})
        self.assertEqual(lg.press("alt_r", 0.0, False, False), ["mask", "begin:normal"])
        for t in (0.03, 0.06, 0.09):
            self.assertEqual(lg.press("alt_r", t, True, False), [])

    def test_toggle_repeat(self):
        lg = smart.HotkeyLogic({"alt_r": "normal"}, "toggle", alt_keys={"alt_r"})
        self.assertEqual(lg.press("alt_r", 0.0, False, False), ["mask"])
        self.assertEqual(lg.press("alt_r", 0.03, False, False), [])


class TestEscCancel(unittest.TestCase):
    """Esc كمفتاح إلغاء (Task 27): بيلغي التسجيل في الوضعين، وno-op وقت الخمول
    من غير ما يلمس الحالة، ولو اتعيّن زرار تسجيل بيفضل زرار تسجيل."""

    def make(self, mode, key_map=None, cancel=("esc",)):
        return smart.HotkeyLogic(key_map or {"ctrl_r": "normal", "alt_r": "prompt"}, mode,
                                 cancel_keys=cancel)

    def test_esc_cancels_while_recording_toggle(self):
        lg = self.make("toggle")
        self.assertEqual(lg.press("esc", 0.0, True, False), ["cancel"])

    def test_esc_cancels_while_recording_hold(self):
        lg = self.make("hold")
        lg.press("ctrl_r", 0.0, False, False)   # يبدأ التسجيل
        self.assertEqual(lg.press("esc", 0.1, True, False), ["cancel"])

    def test_esc_idle_toggle_does_not_spoil_held_hotkey(self):
        # Esc وقت الخمول no-op: منيفسدش hotkey متعقدة ولا يلغى حاجة
        lg = self.make("toggle")
        lg.press("ctrl_r", 0.0, False, False)   # دوسة نضيفة متعقدة
        self.assertEqual(lg.press("esc", 0.05, False, False), [])
        self.assertEqual(lg.release("ctrl_r", 0.1, False, False), ["begin:normal"])

    def test_esc_idle_hold_is_noop(self):
        lg = self.make("hold")
        self.assertEqual(lg.press("esc", 0.0, False, False), [])
        self.assertEqual(lg.release("esc", 0.1, False, False), [])

    def test_hold_hotkey_release_after_esc_cancel_still_ends(self):
        # التسيب بعد الإلغاء بيرجّع "end" — والـcore بيطنّشه لأن recording بقت False
        lg = self.make("hold")
        lg.press("ctrl_r", 0.0, False, False)
        self.assertEqual(lg.press("esc", 0.1, True, False), ["cancel"])
        self.assertEqual(lg.release("ctrl_r", 0.3, True, False), ["end"])

    def test_esc_configured_as_hotkey_keeps_hotkey_role_toggle(self):
        lg = smart.HotkeyLogic({"esc": "normal"}, "toggle", cancel_keys={"esc"})
        self.assertEqual(lg.press("esc", 0.0, False, False), [])
        self.assertEqual(lg.release("esc", 0.1, False, False), ["begin:normal"])

    def test_esc_configured_as_hotkey_keeps_hotkey_role_hold(self):
        lg = smart.HotkeyLogic({"esc": "normal"}, "hold", cancel_keys={"esc"})
        self.assertEqual(lg.press("esc", 0.0, False, False), ["begin:normal"])
        self.assertEqual(lg.release("esc", 0.3, True, False), ["end"])

    def test_esc_cancel_spoils_physically_held_hotkey(self):
        # recording شغّال والمستخدم ماسك زرار التسجيل، داس Esc (cancel) وسابه:
        # التسيب ده مينفعش يبدأ تسجيل جديد (recording بقت False).
        lg = self.make("toggle")
        lg.press("ctrl_r", 0.0, True, False)   # ماسك الزرار وهو بيسجّل
        self.assertEqual(lg.press("esc", 0.1, True, False), ["cancel"])
        self.assertEqual(lg.release("ctrl_r", 0.2, False, False), [])


@unittest.skipUnless(os.name == "nt", "start_hotkey بيستورد winput (ويندوز)")
class TestStartHotkeyWiring(unittest.TestCase):
    """التوصيل الحقيقي في core.start_hotkey بـListener مزيّف — مفيش hook ولا SendInput حقيقي."""

    def wire(self, mode, hotkey="alt_r"):
        from unittest import mock
        import core
        from pynput import keyboard
        captured = {}

        class FakeListener:
            def __init__(self, on_press, on_release, win32_event_filter=None):
                captured.update(press=on_press, release=on_release, filt=win32_event_filter)
                self.daemon = False

            def start(self):
                pass

        app = core.App.__new__(core.App)
        app.recording, app.busy, app._listener = False, False, None
        app.begin, app.end, app.cancel = mock.Mock(), mock.Mock(), mock.Mock()
        cfg = dict(core.CFG, hotkey_normal=hotkey, hotkey_prompt="f9", hotkey_translate="f10", mode=mode)
        sent = []
        patches = [mock.patch.object(core, "CFG", cfg),
                   mock.patch.object(keyboard, "Listener", FakeListener),
                   mock.patch("winput.send_vk", side_effect=lambda vk: sent.append(vk) or 2)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app.start_hotkey()
        return app, captured, sent, keyboard

    def test_alt_mask_sends_unassigned_key_not_alt(self):
        app, cb, sent, kb = self.wire("hold")
        cb["press"](kb.Key.alt_r)
        self.assertEqual(sent, [0xE8])          # VK_MASK — أبدًا Alt (164/165) نفسه
        app.begin.assert_called_once_with(mode="normal")

    def test_hold_chord_cancels(self):
        app, cb, sent, kb = self.wire("hold", hotkey="ctrl_r")
        cb["press"](kb.Key.ctrl_r)
        app.recording = True
        cb["press"](kb.KeyCode.from_char("c"))
        app.cancel.assert_called_once()

    def test_filter_ignores_only_our_tagged_events(self):
        import winput
        _, cb, _, _ = self.wire("toggle")

        class Data:
            def __init__(self, extra):
                self.dwExtraInfo = extra
        self.assertFalse(cb["filt"](0x100, Data(winput.EMLAA_TAG)))
        self.assertTrue(cb["filt"](0x100, Data(0)))

    def test_lock_hotkey_restored_once_per_press_even_with_auto_repeat(self):
        app, cb, sent, kb = self.wire("toggle", hotkey="scroll_lock")
        for _ in range(3):                      # دوسة + تكرار تلقائي
            cb["press"](kb.Key.scroll_lock)
        cb["release"](kb.Key.scroll_lock)
        self.assertEqual(sent, [0x91])          # دوسة استرجاع واحدة بس
        app.begin.assert_called_once_with(mode="normal")

    def test_esc_cancels_when_recording_toggle(self):
        app, cb, sent, kb = self.wire("toggle", hotkey="ctrl_r")
        app.recording = True
        cb["press"](kb.Key.esc)
        app.cancel.assert_called_once()

    def test_esc_cancels_when_recording_hold(self):
        app, cb, sent, kb = self.wire("hold", hotkey="ctrl_r")
        cb["press"](kb.Key.ctrl_r)
        app.recording = True
        cb["press"](kb.Key.esc)
        app.cancel.assert_called_once()

    def test_esc_idle_does_nothing(self):
        app, cb, sent, kb = self.wire("toggle", hotkey="ctrl_r")
        cb["press"](kb.Key.esc)
        app.begin.assert_not_called()
        app.end.assert_not_called()
        app.cancel.assert_not_called()

    def test_esc_as_hotkey_still_begins(self):
        app, cb, sent, kb = self.wire("toggle", hotkey="esc")
        cb["press"](kb.Key.esc)
        cb["release"](kb.Key.esc)
        app.cancel.assert_not_called()
        app.begin.assert_called_once_with(mode="normal")
