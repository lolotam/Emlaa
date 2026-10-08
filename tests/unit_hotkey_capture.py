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


if __name__ == "__main__":
    unittest.main()
