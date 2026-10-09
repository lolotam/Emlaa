# -*- coding: utf-8 -*-
"""
الواجهة الكلاسيك (Tk): زراير التسجيل التلاتة بتتحفظ جوّه features. الحفظ بيبني القاموس كله
ويتفحص مرة واحدة — تركيبة اتسجّلت من الواجهة الجديدة بتفضل، وتبديل زرارين في نفس الحفظة
بيعدّي، والميزات اللي اتعدّلت مابتتمسحش لما المزوّد يتغيّر في حفظة بعدها.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core    # noqa: E402
import emlaa   # noqa: E402
import smart   # noqa: E402

CTRL_R, ALT_R, SHIFT_R, F7, F8, LCTRL = 0xA3, 0xA5, 0xA1, 0x76, 0x77, 0xA2


def features():
    """ميزات زي ما الترحيل بيحسبها لمستخدم Groq (Ctrl/Alt/Shift اليمين، التعديل من غير زرار)."""
    legacy = {"provider": "groq", "hotkey_normal": "ctrl_r", "hotkey_prompt": "alt_r",
              "hotkey_translate": "shift_r", "hotkey_edit": ""}
    return smart.default_features(legacy, {"groq": ["k"]}, None,
                                  {"groq": ["whisper-large-v3-turbo"], "openai": ["whisper-1"]},
                                  {"groq": ["qwen/qwen3.8-27b"], "openai": ["gpt-4o-mini"]})


def current_picks(feats):
    """اللي الكومبوبوكس شايلينه لو المستخدم ماغيّرش حاجة."""
    return {m: list(feats[m]["hotkey"]) for m in emlaa.CLASSIC_MODES}


class TestClassicHotkeyOptions(unittest.TestCase):
    def test_stored_combo_is_offered_next_to_legacy_keys(self):
        f = features()
        f["prompt"]["hotkey"] = [LCTRL, F7]
        opts = emlaa.classic_hotkey_options(f)
        self.assertIn(("Ctrl الشمال + F7", [LCTRL, F7]), opts["prompt"])
        self.assertIn(("F8", [F8]), opts["prompt"])
        self.assertNotIn(("Ctrl الشمال + F7", [LCTRL, F7]), opts["normal"])


class TestClassicSaveFeatures(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = os.path.join(tmp.name, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("GROQ_API_KEY=k\nOPENAI_API_KEY=sk\n")
        for p in (mock.patch.object(core, "ENV_PATH", env),
                  mock.patch.object(core.offline, "installed", return_value=None),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        self.cfg = dict(core.DEFAULTS, provider="groq", features=features(), features_custom=False)

    def save(self, picks, pid="groq"):
        return emlaa.classic_save_features(self.cfg, picks, pid)

    def test_untouched_save_keeps_a_combo_recorded_in_the_new_ui(self):
        self.cfg["features"]["prompt"]["hotkey"] = [LCTRL, F7]
        feats, _, err = self.save(current_picks(self.cfg["features"]))
        self.assertIsNone(err)
        self.assertEqual(feats["prompt"]["hotkey"], [LCTRL, F7])

    def test_swapping_two_modes_in_one_save_succeeds(self):
        feats, custom, err = self.save({"normal": [ALT_R], "prompt": [CTRL_R], "translate": [SHIFT_R]})
        self.assertIsNone(err)
        self.assertEqual((feats["normal"]["hotkey"], feats["prompt"]["hotkey"]), ([ALT_R], [CTRL_R]))
        self.assertTrue(custom)

    def test_duplicate_hotkey_refused_without_touching_stored_features(self):
        _, _, err = self.save({"normal": [CTRL_R], "prompt": [CTRL_R], "translate": [SHIFT_R]})
        self.assertIsNotNone(err)
        self.assertEqual(self.cfg["features"], features())

    def test_hotkey_changed_in_one_save_survives_a_provider_change_in_the_next(self):
        picks = dict(current_picks(self.cfg["features"]), normal=[F8])
        feats, custom, _ = self.save(picks)
        self.cfg.update(features=feats, features_custom=custom)
        feats, _, err = self.save(current_picks(feats), pid="openai")
        self.assertIsNone(err)
        self.assertEqual(feats["normal"]["hotkey"], [F8])
        self.assertEqual(feats["normal"]["stt"][0]["provider"], "groq")    # متعدّلة = مابتتحسبش تاني

    def test_provider_change_with_its_new_key_uses_that_provider_for_ai(self):
        # PR #15 (Codex): المفتاح الجديد لسه ماتكتبش وقت الحساب — لازم يتحسب كأنه موجود
        with open(core.ENV_PATH, "w", encoding="utf-8") as fh:
            fh.write("GROQ_API_KEY=k\n")
        feats, _, err = emlaa.classic_save_features(self.cfg, current_picks(self.cfg["features"]), "openai",
                                                    new_key="sk-new")
        self.assertIsNone(err)
        self.assertEqual({i["provider"] for i in feats["prompt"]["ai"]}, {"openai"})

    def test_untouched_features_follow_a_provider_change(self):
        feats, custom, err = self.save(current_picks(self.cfg["features"]), pid="openai")
        self.assertIsNone(err)
        self.assertFalse(custom)
        self.assertEqual(feats["normal"]["stt"][0]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
