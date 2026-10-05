# -*- coding: utf-8 -*-
"""
اختبارات Task 24 — واجهة إعدادات مجمّعة المفاتيح (Api: key_pool / key_reveal / key_add / key_remove)
مفيش شبكة ولا مفاتيح حقيقية: providers.verify مزيّف، وملف .env مؤقت (من غير E:/notk/.env أبدًا)،
وحالة المفاتيح _KEY_STATE بتتصفّر. بنتأكد إن البوتستريب والـpayload عمرهم ما يرجّعوا مفتاح كامل.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import offline    # noqa: E402
import providers  # noqa: E402
import app_web    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Ctrl:
    """وحدة تحكم مزيّفة لـApi — الحقول اللي bootstrap محتاجاها بس."""
    version = "0"
    brand = {"name": "x", "url": "y"}
    state = "ready"
    last_text = ""
    update_info = None
    hotkeys = []


def _cfg(**over):
    c = dict(core.DEFAULTS)
    c.update(over)
    return c


class TestKeyPoolApi(unittest.TestCase):
    """key_pool / key_reveal / key_add / key_remove ضد .env مؤقت وverify مزيّف."""

    def setUp(self):
        providers._KEY_STATE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_path = os.path.join(self.tmp.name, ".env")
        self._env_patch = mock.patch.object(core, "ENV_PATH", self.env_path)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        # الكتابة في .env بتحدّث os.environ كمان — نرجّعه زي ما كان عشان الاختبارات التانية
        env_patch = mock.patch.dict(os.environ, {})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def tearDown(self):
        providers._KEY_STATE.clear()

    def _write(self, text):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(text)

    def _api(self):
        return app_web.Api(_Ctrl())

    def test_bootstrap_and_key_pool_never_leak_full_keys(self):
        self._write("GROQ_API_KEY=gsk_secretkey1,gsk_secretkey2\nOPENAI_API_KEY=sk-secret-3\n")
        api = self._api()
        with mock.patch.object(core, "CFG", _cfg()), \
                mock.patch.object(core, "history_stats",
                                  return_value={"words": 0, "count": 0, "wpm": None, "saved_min": 0.0}), \
                mock.patch.object(core, "STORE", False), \
                mock.patch.object(core, "_is_packaged", return_value=False), \
                mock.patch.object(offline, "installed", return_value=None):
            boot = api.bootstrap()
            pool = api.key_pool("groq")
        for payload in (boot, pool):
            blob = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("secretkey", blob)
            self.assertNotIn("secret-3", blob)
        # مفيش مفتاح كامل ولا مقنّع في البوتستريب، بس عدد المفاتيح صح
        groq = next(p for p in boot["providers"] if p["id"] == "groq")
        self.assertEqual(groq["keyCount"], 2)
        self.assertNotIn("masked", groq)
        self.assertNotIn("key", groq)
        # key_pool بيرجّع مفاتيح مقنّعة بس
        self.assertEqual([k["masked"] for k in pool["keys"]], ["gsk_…key1", "gsk_…key2"])

    def test_key_pool_masks_and_reports_status(self):
        self._write("GROQ_API_KEY=gsk_aaaa1111,gsk_bbbb2222\n")
        api = self._api()
        fp1 = providers._key_fingerprint("gsk_aaaa1111")
        fp2 = providers._key_fingerprint("gsk_bbbb2222")
        providers._KEY_STATE[("groq", fp1)] = {"status": "rate_limited", "until": time.monotonic() + 120}
        providers._KEY_STATE[("groq", fp2)] = {"status": "invalid", "until": None}
        r = api.key_pool("groq")
        self.assertTrue(r["ok"])
        self.assertEqual(r["keys"][0]["status"], "rate_limited")
        self.assertGreater(r["keys"][0]["retryIn"], 0)
        self.assertEqual(r["keys"][1]["status"], "invalid")
        self.assertIsNone(r["keys"][1]["retryIn"])
        # ولا مفتاح كامل خرج
        self.assertNotIn("gsk_aaaa1111", json.dumps(r, ensure_ascii=False))

    def test_key_pool_unknown_provider(self):
        r = self._api().key_pool("nope")
        self.assertFalse(r["ok"])
        self.assertIn("مزوّد", r["err"])

    def test_key_reveal_exact_key_and_bounds(self):
        self._write("GROQ_API_KEY=gsk_aaaa1111,gsk_bbbb2222\n")
        api = self._api()
        self.assertEqual(api.key_reveal("groq", 0), {"ok": True, "key": "gsk_aaaa1111"})
        self.assertEqual(api.key_reveal("groq", 1)["key"], "gsk_bbbb2222")
        self.assertFalse(api.key_reveal("groq", 2)["ok"])
        self.assertFalse(api.key_reveal("groq", -1)["ok"])
        self.assertFalse(api.key_reveal("groq", True)["ok"])

    def test_key_add_verify_failure_writes_nothing(self):
        self._write("GROQ_API_KEY=k1\n")
        api = self._api()
        with mock.patch.object(providers, "verify", return_value=(False, "المفتاح مش مقبول — اتأكد إنك نسخته كامل")):
            r = api.key_add("groq", "k2")
        self.assertFalse(r["ok"])
        self.assertIn("المفتاح", r["err"])
        self.assertEqual(providers.read_key_pools(self.env_path).get("groq"), ["k1"])

    def test_key_add_duplicate_rejected_without_verify(self):
        self._write("GROQ_API_KEY=k1,k2\n")
        api = self._api()
        v = mock.Mock(return_value=(True, ""))
        with mock.patch.object(providers, "verify", v):
            r = api.key_add("groq", "k1")
        self.assertFalse(r["ok"])
        self.assertIn("موجود بالفعل", r["err"])
        v.assert_not_called()

    def test_key_add_success_appends_in_order(self):
        self._write("GROQ_API_KEY=k1\n")
        api = self._api()
        with mock.patch.object(providers, "verify", return_value=(True, "")):
            r = api.key_add("groq", "k2")
        self.assertTrue(r["ok"])
        self.assertEqual(providers.read_key_pools(self.env_path).get("groq"), ["k1", "k2"])
        self.assertEqual([k["index"] for k in r["keys"]], [0, 1])

    def test_key_add_empty_key(self):
        api = self._api()
        r = api.key_add("groq", "   ")
        self.assertFalse(r["ok"])
        self.assertIn("الصق", r["err"])

    def test_key_remove_by_index(self):
        self._write("GROQ_API_KEY=k1,k2\n")
        api = self._api()
        with mock.patch.object(core, "CFG", _cfg()):
            r = api.key_remove("groq", 0)
        self.assertTrue(r["ok"])
        self.assertEqual(providers.read_key_pools(self.env_path).get("groq"), ["k2"])

    def test_key_remove_refuses_when_the_list_changed_behind_the_ui(self):
        # الواجهة شايفة k1 في الفهرس 0، بس .env اتغيّر — منمسحش المفتاح الغلط
        self._write("GROQ_API_KEY=gsk_other_key_9999,gsk_first_key_1111\n")
        api = self._api()
        with mock.patch.object(core, "CFG", _cfg()):
            r = api.key_remove("groq", 0, providers.mask_key("gsk_first_key_1111"))
        self.assertFalse(r["ok"])
        self.assertEqual(len(providers.read_key_pools(self.env_path)["groq"]), 2)
        with mock.patch.object(core, "CFG", _cfg()):
            r = api.key_remove("groq", 1, providers.mask_key("gsk_first_key_1111"))
        self.assertTrue(r["ok"])
        self.assertEqual(providers.read_key_pools(self.env_path)["groq"], ["gsk_other_key_9999"])

    def test_key_remove_refuses_last_key_of_selected_provider(self):
        self._write("GROQ_API_KEY=k1\n")
        api = self._api()
        with mock.patch.object(core, "CFG", _cfg(provider="groq", offline_mode="fallback")), \
                mock.patch.object(offline, "installed", return_value=None):
            r = api.key_remove("groq", 0)
        self.assertFalse(r["ok"])
        self.assertIn("آخر مفتاح", r["err"])
        self.assertEqual(providers.read_key_pools(self.env_path).get("groq"), ["k1"])

    def test_key_remove_last_key_allowed_when_offline_always_installed(self):
        self._write("GROQ_API_KEY=k1\n")
        api = self._api()
        with mock.patch.object(core, "CFG", _cfg(provider="groq", offline_mode="always")), \
                mock.patch.object(offline, "installed", return_value="base"):
            r = api.key_remove("groq", 0)
        self.assertTrue(r["ok"])
        self.assertNotIn("groq", providers.read_key_pools(self.env_path))

    def test_key_remove_last_key_allowed_for_non_selected_provider(self):
        self._write("GROQ_API_KEY=k1\nOPENAI_API_KEY=sk-1\n")
        api = self._api()
        with mock.patch.object(core, "CFG", _cfg(provider="groq")):
            r = api.key_remove("openai", 0)
        self.assertTrue(r["ok"])
        self.assertNotIn("openai", providers.read_key_pools(self.env_path))
        self.assertEqual(providers.read_key_pools(self.env_path).get("groq"), ["k1"])


class TestStaticUiChecks(unittest.TestCase):
    """قراية الملفات كنص — النصوص والترجمة وعدم استخدام نوافذ المتصفح."""

    @classmethod
    def setUpClass(cls):
        def _read(rel):
            with open(os.path.join(ROOT, "source", "ui", rel), encoding="utf-8") as f:
                return f.read()
        cls.html = _read("index.html")
        cls.js = _read("app.js")
        cls.i18n = _read("i18n.js")

    def test_add_key_button_and_badges_present(self):
        ui = self.html + "\n" + self.js
        self.assertIn("+ إضافة مفتاح إضافي", ui)
        for badge in ("🟢 نشط", "🔴 نفدت الكوتا مؤقتاً", "⚠️ غير صالح"):
            self.assertIn(badge, ui)

    def test_i18n_has_en_entry_for_each_new_string(self):
        for ar, en in [
            ("+ إضافة مفتاح إضافي", "+ Add Key"),
            ("تحقق وأضف", "Verify & add"),
            ("بيتأكد…", "Verifying…"),
            ("متأكد؟", "Sure?"),
            ("🟢 نشط", "🟢 Active"),
            ("🔴 نفدت الكوتا مؤقتاً", "🔴 Rate Limited"),
            ("⚠️ غير صالح", "⚠️ Invalid"),
            ("مفيش مفاتيح محفوظة للمزوّد ده", "No saved keys for this provider"),
            ("اتضاف المفتاح ✓", "Key added ✓"),
        ]:
            self.assertIn('"%s": "%s"' % (ar, en), self.i18n, ar)

    def test_app_js_never_uses_browser_dialogs(self):
        import re
        for fn in ("alert", "confirm", "prompt"):
            self.assertIsNone(re.search(r"\b%s\s*\(" % fn, self.js), fn)


if __name__ == "__main__":
    unittest.main()
