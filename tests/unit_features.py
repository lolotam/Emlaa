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

    def test_two_modifiers_are_not_a_combo(self):
        f = mig()
        f["edit"]["hotkey"] = [0xA2, 0xA3]       # Ctrl الشمال + Ctrl اليمين
        self.assertIsNotNone(smart.validate_features(f))

    def test_same_trigger_different_modifiers_allowed(self):
        f = mig()
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

    def test_invalid_stored_features_fall_back_to_migration(self):
        broken = mig()
        del broken["translate"]                     # ملف اتعدّل بإيد أو اتقطع
        self.write(json.dumps({"provider": "groq", "hotkey_normal": "f7", "features": broken,
                               "features_custom": True}))
        cfg = core.load_config()
        self.assertIsNone(smart.validate_features(cfg["features"]))
        self.assertEqual(cfg["features"]["normal"]["hotkey"], [0x76])
        self.assertFalse(cfg["features_custom"])

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


class _Ctrl:
    """وحدة تحكم مزيّفة لـApi: المحرك (لو موجود) مزيّف وبيتعد كام مرة اتشغّل."""
    version = "0"
    brand = {"name": "x", "url": "y"}
    state = "ready"
    last_text = ""
    update_info = None
    hotkeys = []

    def __init__(self, engine=None):
        self.engine = engine
        self.started = 0

    def apply_lang(self):
        pass

    def start_engine(self):
        self.started += 1

    def start_open_hotkey(self):
        pass

    def tk_call(self, fn):
        pass


class _BridgeCase(unittest.TestCase):
    """CFG في الذاكرة، و.env مؤقت، والحفظ بيتسجّل بدل ما يكتب config.json."""

    def setUp(self):
        import app_web
        self.app_web = app_web
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_path = os.path.join(self.tmp.name, ".env")
        self.write_env("")
        self.cfg = dict(core.DEFAULTS, features=mig(), features_custom=False)
        self.saved = []
        self.local = None
        stats = {"words": 0, "count": 0, "wpm": None, "saved_min": 0.0}
        for p in (mock.patch.object(core, "CFG", self.cfg),
                  mock.patch.object(core, "ENV_PATH", self.env_path),
                  mock.patch.object(core, "save_config",
                                    side_effect=lambda c: self.saved.append(json.loads(json.dumps(c)))),
                  mock.patch.object(core, "history_prune"),
                  mock.patch.object(core, "history_stats", return_value=stats),
                  mock.patch.object(core, "_is_packaged", return_value=False),
                  mock.patch.object(core.offline, "installed", side_effect=lambda: self.local),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)

    def write_env(self, text):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(text)

    def save(self, data, engine=None):
        ctrl = _Ctrl(engine)
        return self.app_web.Api(ctrl).save_settings(data), ctrl


class TestSaveSettings(_BridgeCase):
    def test_invalid_features_rejected_and_nothing_saved(self):
        f = mig()
        f["prompt"]["hotkey"] = [0xA3]          # نفس زرار العادي
        r, _ = self.save({"features": f})
        self.assertFalse(r["ok"])
        self.assertEqual(self.saved, [])
        self.assertEqual(self.cfg["features"], mig())

    def test_valid_features_stored_without_display_fields(self):
        self.write_env("GROQ_API_KEY=k\n")
        f = mig()
        f["normal"].update(hotkey=[0xA2, 0x76], ai=[], label="Left Ctrl + F7")
        r, _ = self.save({"features": f})
        self.assertTrue(r["ok"])
        stored = self.saved[-1]
        self.assertTrue(stored["features_custom"])
        self.assertEqual(stored["features"]["normal"], {"hotkey": [0xA2, 0x76], "stt": mig()["normal"]["stt"],
                                                        "ai": []})

    def test_welcome_recomputes_features_that_were_never_customized(self):
        with mock.patch.object(self.app_web.providers, "verify", return_value=(True, "")):
            r, _ = self.save({"provider": "openai", "key": "sk-new"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.saved[-1]["features"]["normal"]["stt"][0]["provider"], "openai")

    def test_welcome_keeps_customized_features(self):
        self.cfg["features_custom"] = True
        with mock.patch.object(self.app_web.providers, "verify", return_value=(True, "")):
            self.save({"provider": "openai", "key": "sk-new"})
        self.assertEqual(self.saved[-1]["features"], mig())

    def test_welcome_without_key_refused_when_nothing_can_transcribe(self):
        r, _ = self.save({"provider": "groq"})
        self.assertFalse(r["ok"])
        self.assertIn("محتاج مفتاح", r["err"])

    def test_partial_save_needs_no_key(self):
        r, ctrl = self.save({"theme": "light"})
        self.assertTrue(r["ok"])
        self.assertEqual(ctrl.started, 0)        # مفيش حاجة تفرّغ — المحرك مايشتغلش

    def test_engine_starts_after_save_once_something_can_transcribe(self):
        self.write_env("GROQ_API_KEY=k\n")
        _, ctrl = self.save({"theme": "light"})
        self.assertEqual(ctrl.started, 1)

    def test_listener_restarts_only_when_hotkeys_or_mode_change(self):
        self.write_env("GROQ_API_KEY=k\n")
        hotkey = mig()
        hotkey["edit"]["hotkey"] = [0x77]
        models_only = mig()
        models_only["prompt"]["ai"] = models_only["prompt"]["ai"][:1]
        for data, restarts in (({"features": hotkey}, 1), ({"mode": "hold"}, 1),
                               ({"features": models_only}, 0)):
            with self.subTest(data=list(data)):
                self.cfg.update(features=mig(), mode="toggle")
                engine = mock.Mock()
                self.save(data, engine)
                self.assertEqual(engine.restart_hotkey.call_count, restarts)
                engine.reset_client.assert_called_once()


class TestBootstrapFeatures(_BridgeCase):
    def test_features_carry_labels_and_catalog_reports_keys_and_local(self):
        self.write_env("GROQ_API_KEY=k\n")
        self.local = "base"
        self.cfg["features"]["normal"]["hotkey"] = [0xA2, 0x76]
        boot = self.app_web.Api(_Ctrl()).bootstrap()
        self.assertIn("F7", boot["features"]["normal"]["label"])
        self.assertEqual(boot["features"]["edit"]["label"], "")
        cat = boot["catalog"]
        self.assertEqual((cat["groq"]["hasKey"], cat["openai"]["hasKey"]), (True, False))
        self.assertTrue(cat["deepgram"]["sttOnly"])
        self.assertEqual(cat["groq"]["chatModels"], core.providers.chat_models("groq"))
        self.assertEqual(cat["local"]["installed"], "base")
        self.assertTrue(boot["canRun"])
        self.assertFalse(any(k.startswith("hotkey_") for k in boot["cfg"]))


if __name__ == "__main__":
    unittest.main()
