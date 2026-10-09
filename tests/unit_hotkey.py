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
    """
    التوصيل الحقيقي في core.start_hotkey بـListener مزيّف: الفلتر (win32_event_filter) بيتنادى
    بأحداث مزيّفة (vkCode/scanCode/dwExtraInfo)، وطابور الـdispatcher بيتفضّى بـdrain() في
    نفس الثريد — مفيش hook ولا SendInput ولا كيبورد حقيقي.
    """

    F7, F8, LCTRL, RCTRL, RALT, ESC, SCROLL = 0x76, 0x77, 0xA2, 0xA3, 0xA5, 0x1B, 0x91

    class Suppressed(Exception):
        pass

    def wire(self, mode, normal=(0xA3,), prompt=(0xA2, 0x77), translate=(0xA5,), held=()):
        from unittest import mock
        import core
        from pynput import keyboard
        captured = {}
        test = self
        self.physical = set(held)       # الزراير الماسكة فعلًا — key() بيحدّثها

        class FakeListener:
            def __init__(self, win32_event_filter=None, **kw):
                captured["filt"] = win32_event_filter
                captured["kw"] = kw
                self.daemon = False

            def start(self):
                pass

            def stop(self):
                pass

            def suppress_event(self):
                raise test.Suppressed()

        app = core.App.__new__(core.App)
        app.recording, app.busy, app._listener = False, False, None
        app.begin, app.end, app.cancel = mock.Mock(), mock.Mock(), mock.Mock()
        app.on_state = mock.Mock()
        feats = {m: {"hotkey": list(v), "stt": [{"provider": "groq", "model": "w"}], "ai": []}
                 for m, v in (("normal", normal), ("prompt", prompt), ("translate", translate),
                              ("edit", ()))}
        cfg = dict(core.CFG, features=feats, mode=mode)
        sent = []
        patches = [mock.patch.object(core, "CFG", cfg),
                   mock.patch.object(keyboard, "Listener", FakeListener),
                   mock.patch.object(core.HotkeyDispatcher, "start", lambda self: None),
                   mock.patch("winput.keys_down", side_effect=self.keys_down),
                   mock.patch.object(core, "log_error"),
                   mock.patch("winput.send_vk", side_effect=lambda vk: sent.append(vk) or 2)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app.start_hotkey()
        self.app, self.filt, self.sent, self.listener_kw = app, captured["filt"], sent, captured["kw"]
        return app

    def keys_down(self, vks):
        """GetAsyncKeyState زي ويندوز: الكود العام (Ctrl/Shift/Alt) ماسك لو أي جنب ماسك."""
        generic = {0x10: (0xA0, 0xA1), 0x11: (0xA2, 0xA3), 0x12: (0xA4, 0xA5)}
        state = set(self.physical) | {g for g, sides in generic.items() if self.physical & set(sides)}
        return frozenset(v for v in vks if v in state)

    def key(self, vk, down, extra=0, scan=0):
        """حدث واحد من الـhook: بيرجّع True لو اتمنع عن البرامج التانية."""
        import types
        if down:
            self.physical.add(vk)
        else:
            self.physical.discard(vk)
        data = types.SimpleNamespace(vkCode=vk, scanCode=scan, dwExtraInfo=extra)
        try:
            result = self.filt(0x100 if down else 0x101, data)
        except self.Suppressed:
            return True
        self.assertIs(result, False)      # pynput مبيبعتش لـcallbacks بتاعته خالص
        return False

    def drain(self):
        self.app._dispatcher.drain()

    def test_listener_gets_only_the_filter(self):
        self.wire("toggle")
        self.assertEqual(self.listener_kw, {})

    def test_f7_toggle_tap_suppressed_and_begins(self):
        app = self.wire("toggle", normal=(self.F7,))
        self.assertTrue(self.key(self.F7, True))
        self.assertTrue(self.key(self.F7, False))
        self.drain()
        app.begin.assert_called_once_with(mode="normal")

    def test_right_ctrl_tap_begins_and_is_not_suppressed(self):
        app = self.wire("toggle")
        self.assertFalse(self.key(self.RCTRL, True))
        self.assertFalse(self.key(self.RCTRL, False))
        self.drain()
        app.begin.assert_called_once_with(mode="normal")

    def test_ctrl_f8_hold_begins_and_ends_suppressing_only_f8(self):
        app = self.wire("hold")
        self.assertFalse(self.key(self.LCTRL, True))
        self.assertTrue(self.key(self.F8, True))
        self.drain()
        app.begin.assert_called_once_with(mode="prompt")
        app.recording = True
        self.assertTrue(self.key(self.F8, False))
        self.assertFalse(self.key(self.LCTRL, False))
        self.drain()
        app.end.assert_called_once()

    def test_injected_event_neither_queued_nor_suppressed(self):
        import winput
        app = self.wire("toggle", normal=(self.F7,))
        self.assertFalse(self.key(self.F7, True, extra=winput.EMLAA_TAG))
        self.assertFalse(self.key(self.F7, False, extra=winput.EMLAA_TAG))
        self.drain()
        app.begin.assert_not_called()

    def test_altgr_fake_ctrl_ignored_and_right_alt_begins_with_mask(self):
        app = self.wire("hold")
        self.assertFalse(self.key(self.LCTRL, True, scan=0x21D))   # Ctrl المزيّف بتاع AltGr
        self.assertFalse(self.key(self.RALT, True))
        self.drain()
        app.begin.assert_called_once_with(mode="translate")
        self.assertEqual(self.sent, [0xE8])                         # VK_MASK — أبدًا Alt نفسه

    def test_ctrl_held_when_listener_starts_does_not_block_hotkeys_after_release(self):
        # ويندوز بيقول إن Ctrl العام (0x11) ماسك كمان، بس الـhook بيبعت تسيب Ctrl الشمال بس
        self.wire("toggle", normal=(self.F7,), held=(self.LCTRL,))
        self.key(self.LCTRL, False)
        self.key(self.F7, True)
        self.key(self.F7, False)
        self.drain()
        self.app.begin.assert_called_once_with(mode="normal")

    def test_modifier_release_lost_on_secure_desktop_does_not_block_hotkeys(self):
        # Ctrl+Alt+Del / Win+L: الدوسة وصلت للـhook والتسيب ماوصلش
        self.wire("toggle", normal=(self.F7,))
        self.key(self.LCTRL, True)
        self.physical.discard(self.LCTRL)
        self.key(self.F7, True)
        self.key(self.F7, False)
        self.drain()
        self.app.begin.assert_called_once_with(mode="normal")

    def test_initially_held_ctrl_makes_f7_a_different_hotkey(self):
        app = self.wire("toggle", normal=(self.F7,), held=(self.LCTRL,))
        self.assertFalse(self.key(self.F7, True))                   # Ctrl+F7 مش زرار حد
        self.key(self.F7, False)
        self.drain()
        app.begin.assert_not_called()

    def test_hold_chord_cancels(self):
        app = self.wire("hold")
        self.key(self.RCTRL, True)
        self.drain()
        app.recording = True
        self.key(0x43, True)                                          # C
        self.drain()
        app.cancel.assert_called_once()

    def test_esc_cancels_when_recording(self):
        for mode in ("toggle", "hold"):
            app = self.wire(mode)
            app.recording = True
            self.key(self.ESC, True)
            self.drain()
            app.cancel.assert_called_once()

    def test_esc_idle_does_nothing(self):
        app = self.wire("toggle")
        self.key(self.ESC, True)
        self.key(self.ESC, False)
        self.drain()
        app.begin.assert_not_called()
        app.cancel.assert_not_called()

    def test_scroll_lock_trigger_is_suppressed_and_begins(self):
        # الزرار متمنوع فمبيقلبش حالة Scroll Lock — مفيش دوسة استرجاع
        app = self.wire("toggle", normal=(self.SCROLL,))
        self.assertTrue(self.key(self.SCROLL, True))
        self.assertTrue(self.key(self.SCROLL, True))                # تكرار تلقائي
        self.assertTrue(self.key(self.SCROLL, False))
        self.drain()
        app.begin.assert_called_once_with(mode="normal")
        self.assertEqual(self.sent, [])

    def test_action_error_reported_and_next_event_still_processed(self):
        app = self.wire("toggle")
        app.begin.side_effect = [RuntimeError("mic"), None]
        for _ in range(2):
            self.key(self.RCTRL, True)
            self.key(self.RCTRL, False)
            self.drain()
        self.assertEqual(app.begin.call_count, 2)
        self.assertEqual(app.on_state.call_args_list[0].args[0], "err")

    def test_restart_drops_events_queued_for_the_old_engine(self):
        app = self.wire("toggle")
        old = app._dispatcher
        self.key(self.RCTRL, True)
        self.key(self.RCTRL, False)
        app.restart_hotkey()
        self.assertIsNot(app._dispatcher, old)
        old.drain()
        app.begin.assert_not_called()
