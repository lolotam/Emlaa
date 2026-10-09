# -*- coding: utf-8 -*-
"""
إعدادات الميزات الأربعة: الترحيل من الإعدادات القديمة (من غير تغيير في التصرف)، والتحقق
قبل الحفظ، وإن البرنامج يقدر يشتغل (can_run)، وإن load_config عمره ما بيكتب الملف.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core   # noqa: E402
import smart  # noqa: E402

STT = {"groq": ["whisper-large-v3-turbo", "whisper-large-v3"], "deepgram": ["nova-3", "whisper-large"],
       "openai": ["whisper-1"], "gemini": ["g-stt"]}
CHAT = {"groq": ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"], "gemini": ["g1", "g2"], "openai": ["o1"],
        "deepgram": []}
LOCAL = {"provider": "local", "model": ""}


def mig(pools=None, local=None, **cfg):
    base = {"provider": "groq", "models": {}, "hotkey_normal": "ctrl_r", "hotkey_prompt": "alt_r",
            "hotkey_translate": "shift_r", "hotkey_edit": "", "offline_mode": "fallback"}
    base.update(cfg)
    return smart.default_features(base, pools if pools is not None else {"groq": ["k"]}, local, STT, CHAT)


CASES = [dict(), dict(local="base"), dict(local="base", offline_mode="always"),
         dict(offline_mode="always"),
         dict(provider="deepgram", pools={"deepgram": ["d"], "gemini": ["g"]}),
         dict(provider="deepgram", pools={"deepgram": ["d"]}), dict(pools={}),
         dict(hotkey_normal="f8", hotkey_edit="f9")]


class TestMigration(unittest.TestCase):
    def test_every_case_passes_validation(self):
        for c in CASES:
            self.assertIsNone(smart.validate_features(mig(**c)), c)

    def test_hotkeys_from_names(self):
        f = mig()
        self.assertEqual([f[m]["hotkey"] for m in smart.FEATURES], [[0xA3], [0xA5], [0xA1], []])

    def test_stt_keeps_todays_fallbacks_visible(self):
        self.assertEqual(mig()["normal"]["stt"], [{"provider": "groq", "model": "whisper-large-v3-turbo"},
                                                  {"provider": "groq", "model": "whisper-large-v3"}])

    def test_offline_fallback_appends_local_when_installed(self):
        self.assertEqual(mig(local="base")["normal"]["stt"][-1], LOCAL)
        self.assertNotIn(LOCAL, mig()["normal"]["stt"])

    def test_offline_always_is_local_only_everywhere(self):
        f = mig(local="base", offline_mode="always")
        self.assertTrue(all(f[m]["stt"] == [LOCAL] for m in smart.FEATURES))
        # كان اختيار خصوصية: النص عمره ما راح لموديل — العادي يفضل خام
        self.assertEqual(f["normal"]["ai"], [])
        self.assertTrue(f["prompt"]["ai"])

    def test_ai_mirrors_hidden_chat_fallbacks(self):
        self.assertEqual(mig()["prompt"]["ai"], [{"provider": "groq", "model": m} for m in CHAT["groq"]])

    def test_deepgram_borrows_first_chat_provider_with_key(self):
        f = mig(provider="deepgram", pools={"deepgram": ["d"], "gemini": ["g"]})
        self.assertEqual({i["provider"] for i in f["prompt"]["ai"]}, {"gemini"})
        self.assertEqual(f["normal"]["stt"][0], {"provider": "deepgram", "model": "nova-3"})

    def test_no_chat_key_normal_is_raw_others_keep_a_provider(self):
        f = mig(provider="deepgram", pools={"deepgram": ["d"]})
        self.assertEqual(f["normal"]["ai"], [])
        self.assertTrue(f["prompt"]["ai"])

    def test_features_are_independent_copies(self):
        f = mig()
        f["normal"]["stt"].append(LOCAL)
        self.assertNotIn(LOCAL, f["prompt"]["stt"])


class TestValidate(unittest.TestCase):
    def bad(self, mutate):
        f = mig()
        mutate(f)
        self.assertIsNotNone(smart.validate_features(f))

    def test_rules(self):
        self.bad(lambda f: f["prompt"].update(hotkey=[0xA3]))                        # مكرر
        self.bad(lambda f: f["prompt"].update(ai=[]))                                 # معالجة فاضية
        self.bad(lambda f: f["normal"].update(ai=[{"provider": "deepgram", "model": "x"}]))
        self.bad(lambda f: f["normal"].update(ai=[LOCAL]))
        self.bad(lambda f: f["normal"].update(stt=[]))
        self.bad(lambda f: f["normal"].update(stt=[{"provider": "nope", "model": "x"}]))
        self.bad(lambda f: f["edit"].update(hotkey=[0x1B]))
        self.bad(lambda f: f["edit"].update(hotkey=[0x41, 0x42]))
        self.bad(lambda f: f["edit"].update(hotkey=[0xA3, 0x77]))   # Ctrl اليمين لوحده زرار العادي
        self.bad(lambda f: f.pop("translate"))
        self.assertIsNone(smart.validate_features(mig()))

    def test_empty_ai_allowed_for_normal_only(self):
        f = mig()
        f["normal"]["ai"] = []
        self.assertIsNone(smart.validate_features(f))

    def test_several_empty_hotkeys_allowed(self):
        f = mig()
        for m in smart.FEATURES:
            f[m]["hotkey"] = []
        self.assertIsNone(smart.validate_features(f))

    def test_same_trigger_different_modifiers_allowed(self):
        f = mig()
        f["edit"]["hotkey"] = [0xA2, 0xA3 + 0]   # Ctrl الشمال + Ctrl اليمين: شكل غلط
        self.assertIsNotNone(smart.validate_features(f))
        f["edit"]["hotkey"] = [0xA2, 0x76]
        f["prompt"]["hotkey"] = [0x76]
        self.assertIsNone(smart.validate_features(f))


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self.env_path = os.path.join(self.tmp.name, ".env")
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=gsk_test\n")
        for p in (mock.patch.object(core, "CFG_PATH", self.cfg_path),
                  mock.patch.object(core, "ENV_PATH", self.env_path),
                  mock.patch.object(core.offline, "installed", return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def write(self, content):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write(content)

    def read_bytes(self):
        with open(self.cfg_path, "rb") as f:
            return f.read()

    def test_missing_features_computed_not_written(self):
        self.write(json.dumps({"provider": "groq", "hotkey_normal": "f7"}))
        before = self.read_bytes()
        cfg = core.load_config()
        self.assertEqual(cfg["features"]["normal"]["hotkey"], [0x76])
        self.assertFalse(cfg["features_custom"])
        self.assertEqual(self.read_bytes(), before)

    def test_existing_features_kept(self):
        feats = mig()
        feats["normal"]["hotkey"] = [0xA2, 0x76]
        self.write(json.dumps({"features": feats, "features_custom": True}))
        cfg = core.load_config()
        self.assertEqual(cfg["features"]["normal"]["hotkey"], [0xA2, 0x76])
        self.assertTrue(cfg["features_custom"])

    def test_corrupt_file_not_overwritten(self):
        self.write("{not json")
        cfg = core.load_config()
        self.assertIn("features", cfg)
        self.assertEqual(self.read_bytes(), b"{not json")

    def test_legacy_hotkey_only_file_migrates_to_f8(self):
        self.write(json.dumps({"hotkey": "f8"}))
        self.assertEqual(core.load_config()["features"]["normal"]["hotkey"], [0x77])


class TestCanRun(unittest.TestCase):
    def test_any_usable_stt_item(self):
        f = mig(local="base")
        self.assertTrue(core.can_run({"features": f}, pools={"groq": ["k"]}, local=None))
        self.assertTrue(core.can_run({"features": f}, pools={}, local="base"))
        self.assertFalse(core.can_run({"features": f}, pools={}, local=None))
        self.assertFalse(core.can_run({"features": mig()}, pools={"gemini": ["k"]}, local="base"))


if __name__ == "__main__":
    unittest.main()
