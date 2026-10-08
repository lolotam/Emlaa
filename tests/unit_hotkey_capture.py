# -*- coding: utf-8 -*-
"""
زراير التسجيل بأرقام ويندوز (vk) بدل أسماء pynput: نموذج الزرار والمطابقة الواحدة
(HotkeyMatcher) اللي المنع والتشغيل الاتنين بيستخدموها، وقرار المنع (HotkeyFilter)،
وتسجيل الزرار من الكيبورد (CaptureSession). كله منطق نقي — مفيش كيبورد حقيقي.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart  # noqa: E402

F7, F8, LCTRL, RCTRL, RALT, LSHIFT = 0x76, 0x77, 0xA2, 0xA3, 0xA5, 0xA0


class TestHotkeyModel(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(smart.hotkey_from_vks([F7]), smart.Hotkey(frozenset(), F7))
        self.assertEqual(smart.hotkey_from_vks([LCTRL, F7]), smart.Hotkey(frozenset({LCTRL}), F7))
        self.assertIsNone(smart.hotkey_from_vks([]))

    def test_shape_rules(self):
        self.assertTrue(smart.hotkey_shape_ok([]))
        self.assertTrue(smart.hotkey_shape_ok([RCTRL]))
        self.assertTrue(smart.hotkey_shape_ok([LCTRL, F7]))
        self.assertFalse(smart.hotkey_shape_ok([0x41, 0x42]))     # زرارين عاديين
        self.assertFalse(smart.hotkey_shape_ok([LCTRL, RALT]))    # موديفايرين
        self.assertFalse(smart.hotkey_shape_ok([F7, LCTRL]))      # الموديفاير لازم الأول
        self.assertFalse(smart.hotkey_shape_ok([0x1B]))           # Esc للإلغاء
        self.assertFalse(smart.hotkey_shape_ok([LCTRL, 0x1B]))
        self.assertFalse(smart.hotkey_shape_ok([1, 2, 3]))

    def test_labels(self):
        self.assertEqual(smart.hotkey_label([LCTRL, F7], "en"), "Left Ctrl + F7")
        self.assertEqual(smart.vk_label(RALT, "ar"), "Alt اليمين")
        self.assertEqual(smart.vk_label(0xB3, "en"), "Media Play/Pause")
        self.assertEqual(smart.vk_label(0x41, "ar"), "A")
        self.assertEqual(smart.vk_label(0xFE, "en"), "Key 0xFE")
        self.assertEqual(smart.hotkey_label([], "ar"), "")

    def test_legacy_names(self):
        self.assertEqual(smart.LEGACY_HOTKEY_VKS["alt_r"], RALT)
        self.assertEqual(smart.LEGACY_HOTKEY_VKS["f12"], 0x7B)


class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.m = smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                      "prompt": smart.Hotkey(frozenset({LCTRL}), F7),
                                      "translate": smart.Hotkey(frozenset(), RCTRL)})

    def test_same_trigger_two_modes(self):
        self.assertEqual(self.m.match(F7, frozenset()), "normal")
        self.assertEqual(self.m.match(F7, frozenset({LCTRL})), "prompt")

    def test_extra_modifier_matches_nothing(self):
        self.assertIsNone(self.m.match(F7, frozenset({LSHIFT})))
        self.assertIsNone(self.m.match(F7, frozenset({LCTRL, LSHIFT})))

    def test_modifier_trigger_ignores_itself_in_held(self):
        self.assertEqual(self.m.match(RCTRL, frozenset({RCTRL})), "translate")

    def test_non_modifier_keys_in_held_are_ignored(self):
        # held بيتقارن بالموديفايرز بس — زرار عادي ماسك تاني مالوش دعوة بالمطابقة
        self.assertEqual(self.m.match(F7, frozenset({0x41})), "normal")

    def test_triggers(self):
        self.assertEqual(self.m.triggers(), {F7, RCTRL})


class TestFilter(unittest.TestCase):
    """قرار المنع: بيستخدم نفس المطابقة، ومتثبّت لكل دوسة حقيقية لحد ما الزرار يتساب."""

    def matcher(self):
        return smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                    "prompt": smart.Hotkey(frozenset({LCTRL}), F8),
                                    "translate": smart.Hotkey(frozenset(), RALT)})

    def make(self, initially_down=frozenset()):
        return smart.HotkeyFilter(self.matcher(), initially_down=initially_down)

    def test_single_trigger_suppressed_press_and_release(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        self.assertEqual(f.event(F7, False, False, False), (True, True))

    def test_unmatched_modifier_combination_is_not_suppressed(self):
        # F7 لوحده زرار التسجيل — Ctrl+F7 لسه بتاع البرنامج اللي قدامك
        f = self.make()
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F7, True, False, False), (True, False))

    def test_combo_release_suppressed_after_modifier_released_first(self):
        f = self.make()
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F8, True, False, False), (True, True))
        f.event(LCTRL, False, False, False)
        self.assertEqual(f.event(F8, False, False, False), (True, True))

    def test_bare_modifier_trigger_never_suppressed(self):
        self.assertEqual(self.make().event(RALT, True, False, False), (True, False))

    def test_injected_and_fake_ctrl_ignored(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, True, False), (False, False))
        self.assertEqual(f.event(LCTRL, True, False, True), (False, False))
        self.assertEqual(f.held(), frozenset())

    def test_decision_latched_across_repeats(self):
        # Ctrl اتداس والـF7 ماسك: التكرار والتسيب بياخدوا قرار أول دوسة
        f = self.make()
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        self.assertEqual(f.event(F7, False, False, False), (True, True))

    def test_initially_held_ctrl_is_known(self):
        f = self.make(initially_down=frozenset({LCTRL}))
        self.assertEqual(f.event(F7, True, False, False), (True, False))   # Ctrl+F7، مش F7


class TestComboLogic(unittest.TestCase):
    def matcher(self):
        return smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                    "prompt": smart.Hotkey(frozenset({LCTRL}), F7)})

    def test_toggle_same_trigger_two_modes(self):
        lg = smart.HotkeyLogic(self.matcher(), "toggle")
        lg.press(F7, 0.0, False, False, held=frozenset())
        self.assertEqual(lg.release(F7, 0.1, False, False), ["begin:normal"])
        lg.press(F7, 1.0, False, False, held=frozenset({LCTRL}))
        self.assertEqual(lg.release(F7, 1.1, False, False), ["begin:prompt"])

    def test_toggle_extra_modifier_does_nothing(self):
        lg = smart.HotkeyLogic(self.matcher(), "toggle")
        lg.press(F7, 0.0, False, False, held=frozenset({LSHIFT}))
        self.assertEqual(lg.release(F7, 0.1, False, False), [])

    def test_hold_extra_modifier_does_not_begin(self):
        lg = smart.HotkeyLogic(self.matcher(), "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False, held=frozenset({LSHIFT})), [])

    def test_hold_combo_begin_end(self):
        lg = smart.HotkeyLogic(self.matcher(), "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False, held=frozenset({LCTRL})), ["begin:prompt"])
        self.assertEqual(lg.release(F7, 0.4, True, False), ["end"])

    def test_legacy_key_map_still_accepted(self):
        lg = smart.HotkeyLogic({F7: "normal"}, "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False), ["begin:normal"])

    def test_alt_trigger_still_masked(self):
        lg = smart.HotkeyLogic(smart.HotkeyMatcher({"prompt": smart.Hotkey(frozenset(), RALT)}),
                               "toggle", alt_keys={RALT})
        self.assertEqual(lg.press(RALT, 0.0, False, False), ["mask"])


class TestCapture(unittest.TestCase):
    """تسجيل الزرار من الكيبورد: بيسجّل اللي اتداس جوّه الجلسة بس، وبيستنى التسيب."""

    def feed(self, s, events):
        return [s.event(vk, down, fake) for vk, down, fake in events]

    def test_altgr_records_right_alt_not_fake_ctrl(self):
        s = smart.CaptureSession(1)
        self.feed(s, [(LCTRL, True, True), (RALT, True, False), (LCTRL, False, True), (RALT, False, False)])
        self.assertEqual((s.finished, s.result), (True, [RALT]))

    def test_single_key_ignores_auto_repeat(self):
        s = smart.CaptureSession(1)
        self.assertEqual(self.feed(s, [(F7, True, False), (F7, True, False)]), [True, True])
        self.assertFalse(s.decided)
        s.event(F7, False, False)
        self.assertEqual(s.result, [F7])

    def test_key_held_before_session_passes_through_including_repeats(self):
        s = smart.CaptureSession(1, initially_down=frozenset({LCTRL}))
        self.assertEqual(self.feed(s, [(LCTRL, True, False), (LCTRL, False, False)]), [False, False])
        self.assertFalse(s.decided)
        # بعد ما اتساب، دوسة جديدة عليه بتاعتنا
        self.assertTrue(s.event(LCTRL, True, False))

    def test_release_of_unknown_key_passes_through(self):
        s = smart.CaptureSession(1)
        self.assertEqual(self.feed(s, [(LCTRL, False, False)]), [False])

    def test_two_keys_finished_only_after_full_release(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(F7, True, False), (LCTRL, True, False), (F7, False, False)])
        self.assertTrue(s.decided)
        self.assertFalse(s.finished)
        self.assertTrue(s.event(LCTRL, False, False))     # لسه بتاعنا: متمنوع
        self.assertTrue(s.finished)
        self.assertEqual(s.result, [LCTRL, F7])

    def test_two_keys_needs_both_down_together(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(F7, True, False), (F7, False, False)])
        self.assertFalse(s.decided)

    def test_single_key_waits_for_other_captured_keys(self):
        s = smart.CaptureSession(1)
        self.feed(s, [(F7, True, False), (F8, True, False), (F7, False, False)])
        self.assertEqual((s.decided, s.finished, s.result), (True, False, [F7]))
        s.event(F8, False, False)
        self.assertTrue(s.finished)

    def test_two_non_modifiers_rejected(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(0x41, True, False), (0x42, True, False), (0x41, False, False), (0x42, False, False)])
        self.assertTrue(s.finished)
        self.assertIsNone(s.result)
        self.assertIsNotNone(s.error)

    def test_escape_cancels_and_is_suppressed(self):
        s = smart.CaptureSession(1)
        self.assertTrue(s.event(0x1B, True, False))
        self.assertTrue(s.cancelled)
        self.assertTrue(s.decided)
        self.assertFalse(s.finished)              # Esc لسه ماتسابش
        self.assertTrue(s.event(0x1B, False, False))
        self.assertTrue(s.finished)
        self.assertIsNone(s.result)


if __name__ == "__main__":
    unittest.main()
