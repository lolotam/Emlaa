# -*- coding: utf-8 -*-
"""
اختبارات Tasks 22/23 — تخزين المفاتيح بالمجمّعات والتبديل بينها عند الحد/المفتاح الغلط.
مفيش شبكة: عميل OpenAI مزيّف، ومفاتيح وهمية بس، وملفات .env مؤقتة (مش E:/notk/.env أبدًا).
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import providers  # noqa: E402
import core       # noqa: E402
import smart      # noqa: E402


_ENV_VARS = [providers.PROVIDERS[p]["env"] for p in providers.ORDER]


class _Base(unittest.TestCase):
    """بيصفّر حالة المفاتيح والموديلات ويرجّع os.environ زي ما كان بعد كل اختبار."""

    def setUp(self):
        providers._KEY_STATE.clear()
        providers._UNAVAILABLE_MODELS.clear()
        self._env = {v: os.environ.get(v) for v in _ENV_VARS}

    def tearDown(self):
        providers._KEY_STATE.clear()
        providers._UNAVAILABLE_MODELS.clear()
        for v, val in self._env.items():
            if val is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = val


class _FakeChat:
    """OpenAI client مزيّف للشات: لكل موديل رد أو استثناء، وبيسجّل (الموديل، max_retries)."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []
        self._retries = None
        self.chat = mock.Mock()
        self.chat.completions.create.side_effect = self._create

    def with_options(self, max_retries=None, timeout=None):
        self._retries = max_retries
        return self

    def _create(self, model, temperature, messages):
        self.calls.append((model, self._retries))
        out = self.behaviour[model]
        if isinstance(out, Exception):
            raise out
        msg = mock.Mock(content=out)
        return mock.Mock(choices=[mock.Mock(message=msg)])


class TestKeyStorage(_Base):
    """قراية/كتابة .env بالمجمّعات (مفصولة بفواصل)."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, ".env")
        self.addCleanup(self.tmp.cleanup)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_parses_commas_whitespace_empty_and_duplicates(self):
        self._write("GROQ_API_KEY= k1 , k2 ,, k1 , k3 \n"
                    "OPENAI_API_KEY=sk-a\n"
                    "# تعليق\n"
                    "SOMETHING_ELSE=xyz\n")
        pools = providers.read_key_pools(self.path)
        self.assertEqual(pools["groq"], ["k1", "k2", "k3"])
        self.assertEqual(pools["openai"], ["sk-a"])
        self.assertNotIn("deepgram", pools)

    def test_read_keys_returns_first_key_backward_compatible(self):
        self._write("GROQ_API_KEY=k1,k2\nGEMINI_API_KEY=ai-1\n")
        self.assertEqual(providers.read_keys(self.path),
                         {"groq": "k1", "gemini": "ai-1"})

    def test_single_key_env_still_works(self):
        self._write("GROQ_API_KEY=onlykey\n")
        self.assertEqual(providers.read_keys(self.path), {"groq": "onlykey"})
        self.assertEqual(providers.read_key_pools(self.path), {"groq": ["onlykey"]})

    def test_missing_env_returns_empty(self):
        self.assertEqual(providers.read_key_pools(self.path), {})
        self.assertEqual(providers.read_keys(self.path), {})

    def test_write_key_puts_first_and_keeps_others_and_lines(self):
        self._write("GROQ_API_KEY=k1,k2\nGEMINI_API_KEY=ai-1\n")
        providers.write_key(self.path, "groq", "k0")
        self.assertEqual(providers.read_key_pools(self.path)["groq"], ["k0", "k1", "k2"])
        self.assertEqual(providers.read_keys(self.path).get("gemini"), "ai-1")

    def test_write_key_existing_moves_to_front_without_duplicate(self):
        self._write("GROQ_API_KEY=k1,k2,k3\n")
        providers.write_key(self.path, "groq", "k2")
        self.assertEqual(providers.read_key_pools(self.path)["groq"], ["k2", "k1", "k3"])

    def test_add_provider_key_appends_without_duplicate(self):
        self._write("GROQ_API_KEY=k1\n")
        providers.add_provider_key(self.path, "groq", "k2")
        self.assertEqual(providers.read_key_pools(self.path)["groq"], ["k1", "k2"])
        providers.add_provider_key(self.path, "groq", "k1")   # مفيش تكرار
        self.assertEqual(providers.read_key_pools(self.path)["groq"], ["k1", "k2"])
        providers.add_provider_key(self.path, "openai", "sk-new")
        self.assertEqual(providers.read_keys(self.path).get("openai"), "sk-new")

    def test_remove_provider_key_by_index_and_key_then_drop_line(self):
        self._write("GROQ_API_KEY=k1,k2,k3\nGEMINI_API_KEY=ai-1\n")
        providers.remove_provider_key(self.path, "groq", 1)
        self.assertEqual(providers.read_key_pools(self.path)["groq"], ["k1", "k3"])
        providers.remove_provider_key(self.path, "groq", "k3")
        self.assertEqual(providers.read_key_pools(self.path)["groq"], ["k1"])
        providers.remove_provider_key(self.path, "groq", "k1")   # المجمّعة فاضت → السطر اتشال
        self.assertNotIn("groq", providers.read_key_pools(self.path))
        self.assertEqual(providers.read_key_pools(self.path)["gemini"], ["ai-1"])

    def test_write_updates_os_environ(self):
        self._write("GROQ_API_KEY=k1,k2\n")
        providers.add_provider_key(self.path, "groq", "k3")
        self.assertEqual(os.environ.get("GROQ_API_KEY"), "k1,k2,k3")

    def test_set_pool_pops_env_var_when_pool_empty(self):
        self._write("GROQ_API_KEY=k1\n")
        os.environ["GROQ_API_KEY"] = "k1"
        providers._set_pool(self.path, "GROQ_API_KEY", [])
        self.assertNotIn("GROQ_API_KEY", os.environ)

    def test_empty_pool_writes_no_empty_line(self):
        self._write("GROQ_API_KEY=k1\nGEMINI_API_KEY=ai-1\n")
        providers.remove_provider_key(self.path, "groq", "k1")
        with open(self.path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("GROQ_API_KEY=", content)
        self.assertIn("GEMINI_API_KEY=ai-1", content)

    def _env_text(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def test_failed_replace_keeps_old_env_and_leaves_no_temp(self):
        # الكتابة ذرّية: لو الاستبدال فشل الملف القديم بيفضل زي ما هو بكل مفاتيحه
        self._write("GROQ_API_KEY=k1\nGEMINI_API_KEY=ai-1\n")
        with mock.patch.object(providers.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                providers.add_provider_key(self.path, "groq", "k2")
        self.assertEqual(self._env_text(), "GROQ_API_KEY=k1\nGEMINI_API_KEY=ai-1\n")
        self.assertEqual(os.listdir(self.tmp.name), [".env"])
        self.assertNotEqual(os.environ.get("GROQ_API_KEY"), "k1,k2")

    def test_failed_read_writes_nothing(self):
        # قراية .env فشلت → منكتبش ملف فاضي يمسح مفاتيح باقي المزوّدين
        self._write("GROQ_API_KEY=k1\nGEMINI_API_KEY=ai-1\n")
        real_open = open

        def flaky_open(path, mode="r", *a, **kw):
            if path == self.path and "r" in mode:
                raise OSError("locked")
            return real_open(path, mode, *a, **kw)

        with mock.patch("builtins.open", side_effect=flaky_open):
            with self.assertRaises(OSError):
                providers._set_pool(self.path, "GROQ_API_KEY", ["k1", "k2"])
        self.assertEqual(self._env_text(), "GROQ_API_KEY=k1\nGEMINI_API_KEY=ai-1\n")

    def test_append_after_last_line_without_newline(self):
        # آخر سطر من غير \n: المفتاح الجديد ميلزقش فيه
        self._write("GEMINI_API_KEY=ai-1")
        providers.add_provider_key(self.path, "groq", "k1")
        self.assertEqual(providers.read_key_pools(self.path),
                         {"gemini": ["ai-1"], "groq": ["k1"]})

    def test_key_id_is_stable_and_distinguishes_same_mask(self):
        a, b = "gsk_aaaa_one_1234", "gsk_bbbb_two_1234"
        self.assertEqual(providers.mask_key(a), providers.mask_key(b))
        self.assertNotEqual(providers.key_id(a), providers.key_id(b))
        self.assertEqual(providers.key_id(a), providers.key_id(a))


class TestKeyErrorKind(_Base):
    """تصنيف خطأ المفتاح: الحالة الـHTTP الأول، والحد بيتفحص قبل الباطل."""

    def test_status_code_429_is_rate(self):
        self.assertEqual(providers._key_error_kind(SimpleNamespace(status_code=429)), "rate")

    def test_status_code_401_is_invalid(self):
        self.assertEqual(providers._key_error_kind(SimpleNamespace(status_code=401)), "invalid")

    def test_status_attr_403_with_invalid_phrase_is_invalid(self):
        e = RuntimeError("403 invalid x-api-key")
        e.status = 403
        self.assertEqual(providers._key_error_kind(e), "invalid")

    def test_status_attr_403_without_invalid_phrase_is_none(self):
        e = RuntimeError("403 forbidden")
        e.status = 403
        self.assertIsNone(providers._key_error_kind(e))

    def test_leading_status_regex_429(self):
        self.assertEqual(providers._key_error_kind(RuntimeError("Error code: 429 - rate_limit_exceeded")), "rate")

    def test_gemini_429_body_with_api_key_is_rate_not_invalid(self):
        e = RuntimeError("HTTP 429 RESOURCE_EXHAUSTED: api_key: abcd quota exceeded")
        self.assertEqual(providers._key_error_kind(e), "rate")

    def test_request_id_with_401_substring_is_not_invalid(self):
        self.assertIsNone(providers._key_error_kind(RuntimeError("request id 401-abc failed")))

    def test_rate_phrase_without_status(self):
        self.assertEqual(providers._key_error_kind(RuntimeError("rate limit exceeded")), "rate")

    def test_invalid_phrase_without_status(self):
        self.assertEqual(providers._key_error_kind(RuntimeError("invalid api key")), "invalid")

    def test_rate_checked_before_invalid(self):
        self.assertEqual(providers._key_error_kind(RuntimeError("resource_exhausted invalid api key")), "rate")

    def test_network_error_is_never_key_error(self):
        self.assertIsNone(providers._key_error_kind(providers.NetworkError("انقطاع")))


class TestFailover(_Base):
    """التبديل بين المفاتيح: 429 → المفتاح التاني، 401 → invalid، وكلهم خلصوا → رسالة."""

    def _client(self, keys):
        return providers.Client("groq", keys[0], keys=keys)

    def _side(self, cl, behaviour, calls):
        """عميل تفريغ مزيّف: السلوك حسب المفتاح الشغّال دلوقتي (cl.key)."""
        def side(wav, language):
            calls.append(cl.key)
            out = behaviour[cl.key]
            if isinstance(out, Exception):
                raise out
            return out
        return side

    def test_key1_429_then_key2_succeeds_and_key1_skipped(self):
        cl = self._client(["k1", "k2"])
        calls = []
        side = self._side(cl, {"k1": RuntimeError("429 rate_limit_exceeded"), "k2": "النص"}, calls)
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            self.assertEqual(cl.transcribe("wav"), "النص")
        self.assertEqual(calls, ["k1", "k2"])
        self.assertEqual(providers.key_status("groq", "k1")["status"], "rate_limited")
        # المرة الجاية: k1 لسه بيبرد → بيتخطى وبيتنادي k2 بس
        calls.clear()
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            self.assertEqual(cl.transcribe("wav"), "النص")
        self.assertEqual(calls, ["k2"])

    def test_rate_limited_active_again_after_cooldown(self):
        cl = self._client(["k1", "k2"])
        now = [0.0]
        calls = []
        side = self._side(cl, {"k1": RuntimeError("429 rate_limit_exceeded"), "k2": "النص"}, calls)
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side), \
                mock.patch.object(providers.time, "monotonic", side_effect=lambda: now[0]):
            self.assertEqual(cl.transcribe("wav"), "النص")
            self.assertEqual(calls, ["k1", "k2"])
            self.assertEqual(providers.key_status("groq", "k1")["status"], "rate_limited")
            # نعدّي مدة التبريد (٦٠ ثانية الافتراضية)
            now[0] = 61.0
            self.assertEqual(providers.key_status("groq", "k1")["status"], "active")
            calls.clear()
            self.assertEqual(cl.transcribe("wav"), "النص")
            self.assertEqual(calls, ["k1", "k2"])   # k1 اتنادي تاني الأول

    def test_cooling_key_not_retried_while_another_key_was_active(self):
        # k1 لسه بيبرد، وk2 (الشغّال) وقع في الحد: منرجعش نضرب k1 في نفس النداء —
        # كلهم خلصوا = رسالة «كل المفاتيح» على طول
        cl = self._client(["k1", "k2"])
        calls = []
        rate = RuntimeError("429 rate_limit_exceeded")
        side = self._side(cl, {"k1": rate, "k2": "النص"}, calls)
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            cl.transcribe("wav")                       # k1 اتعلّم rate_limited
            calls.clear()
            side_all = self._side(cl, {"k1": rate, "k2": rate}, calls)
            with mock.patch.object(cl, "_oa_transcribe", side_effect=side_all):
                with self.assertRaises(RuntimeError) as ctx:
                    cl.transcribe("wav")
        self.assertEqual(calls, ["k2"])
        self.assertEqual(str(ctx.exception), providers.KEYS_EXHAUSTED_MSG)

    def test_401_marks_invalid_and_skips_forever(self):
        cl = self._client(["k1", "k2"])
        calls = []
        side = self._side(cl, {"k1": RuntimeError("401 invalid api key"), "k2": "النص"}, calls)
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            self.assertEqual(cl.transcribe("wav"), "النص")
        self.assertEqual(calls, ["k1", "k2"])
        self.assertEqual(providers.key_status("groq", "k1")["status"], "invalid")
        calls.clear()
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            self.assertEqual(cl.transcribe("wav"), "النص")
        self.assertEqual(calls, ["k2"])

    def test_cooldown_parses_try_again_in_1m30s(self):
        self.assertEqual(providers._cooldown_for("Please try again in 1m30s"), 90.0)

    def test_cooldown_parses_retry_after(self):
        self.assertEqual(providers._cooldown_for("Retry-After: 3.5"), 3.5)

    def test_daily_quota_without_hint_gets_one_hour(self):
        self.assertEqual(providers._cooldown_for("You exceeded your daily quota"), 3600.0)

    def test_default_cooldown_is_sixty(self):
        self.assertEqual(providers._cooldown_for("429 rate limit"), 60.0)

    def test_cooldown_340ms_is_one_second_not_minutes(self):
        self.assertEqual(providers._cooldown_for("Please try again in 340ms"), 1.0)

    def test_cooldown_decimal_seconds(self):
        self.assertEqual(providers._cooldown_for("Please try again in 7.66s"), 7.66)

    def test_cooldown_minutes_and_decimal_seconds(self):
        self.assertEqual(providers._cooldown_for("Please try again in 2m59.56s"), 179.56)

    def test_cooldown_hours_minutes_decimal_seconds(self):
        self.assertEqual(providers._cooldown_for("Please try again in 1h2m3.5s"), 3723.5)

    def test_cooldown_clamped_to_24_hours(self):
        self.assertEqual(providers._cooldown_for("Please try again in 25h"), 86400.0)

    def test_chat_all_keys_exhausted_returns_raw_text(self):
        cl = self._client(["k1", "k2"])
        with mock.patch.object(cl, "_oa_chat", side_effect=RuntimeError("429 rate_limit_exceeded")), \
                mock.patch("core.log_error"):
            out = cl._chat("sys", "النص الأصلي", 0.2)
        self.assertEqual(out, "النص الأصلي")

    def test_chat_raw_all_keys_exhausted_returns_none(self):
        cl = self._client(["k1", "k2"])
        with mock.patch.object(cl, "_oa_chat", side_effect=RuntimeError("429 rate_limit_exceeded")), \
                mock.patch("core.log_error"):
            self.assertIsNone(cl._chat_raw("sys", "النص", 0.2))

    def test_transcribe_all_keys_exhausted_raises_friendly(self):
        cl = self._client(["k1", "k2"])
        with mock.patch.object(cl, "_oa_transcribe", side_effect=RuntimeError("429 rate_limit_exceeded")):
            with self.assertRaises(RuntimeError) as ctx:
                cl.transcribe("wav")
        self.assertIn("كل المفاتيح", str(ctx.exception))
        # مش خطأ شبكة — مينفعش يشغّل الـoffline fallback
        self.assertFalse(smart.is_network_error(ctx.exception))

    def test_friendly_error_turns_exhausted_into_the_message(self):
        self.assertEqual(core.friendly_error(RuntimeError(providers.KEYS_EXHAUSTED_MSG)),
                         providers.KEYS_EXHAUSTED_MSG)

    def test_switching_key_resets_cached_client(self):
        cl = self._client(["k1", "k2"])
        cl._oa = mock.sentinel.old
        cl._set_key("k2")
        self.assertIsNone(cl._oa)
        self.assertEqual(cl.key, "k2")

    def test_non_key_error_propagates_as_is(self):
        cl = self._client(["k1", "k2"])
        calls = []
        boom = providers.NetworkError("انقطاع في النت")
        side = self._side(cl, {"k1": boom, "k2": "النص"}, calls)
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            with self.assertRaises(providers.NetworkError):
                cl.transcribe("wav")
        # مفيش تبديل للمفتاح التاني — خطأ الشبكة بيطلع زي ما هو
        self.assertEqual(calls, ["k1"])

    def test_single_key_401_re_raises_original_not_exhausted(self):
        cl = self._client(["k1"])
        err = RuntimeError("401 invalid api key")
        with mock.patch.object(cl, "_oa_transcribe", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                cl.transcribe("wav")
        self.assertIs(ctx.exception, err)
        self.assertNotIn("كل المفاتيح", str(ctx.exception))

    def test_invalid_key_is_final_resort_still_attempted(self):
        cl = self._client(["k1"])
        calls = []
        side = self._side(cl, {"k1": RuntimeError("401 invalid api key")}, calls)
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            with self.assertRaises(RuntimeError):
                cl.transcribe("wav")
        self.assertEqual(calls, ["k1"])
        # تاني نداء: الباطل بيتجرب تاني كمحاولة أخيرة — مش بيتسكب للأبد
        calls.clear()
        with mock.patch.object(cl, "_oa_transcribe", side_effect=side):
            with self.assertRaises(RuntimeError):
                cl.transcribe("wav")
        self.assertEqual(calls, ["k1"])

    def test_clear_key_state_resets_status(self):
        providers._KEY_STATE[("groq", providers._key_fingerprint("k1"))] = \
            {"status": "invalid", "until": None}
        self.assertEqual(providers.key_status("groq", "k1")["status"], "invalid")
        providers.clear_key_state("groq", "k1")
        self.assertEqual(providers.key_status("groq", "k1")["status"], "active")

    def test_verify_success_clears_key_state(self):
        providers._KEY_STATE[("openai", providers._key_fingerprint("sk-test"))] = \
            {"status": "invalid", "until": None}
        fake = mock.Mock()
        fake.models.list.return_value = None
        with mock.patch("openai.OpenAI", return_value=fake):
            ok, msg = providers.verify("openai", "sk-test")
        self.assertTrue(ok)
        self.assertEqual(providers.key_status("openai", "sk-test")["status"], "active")

    def test_final_key_attempt_false_gives_last_model_zero_retries(self):
        cl = self._client(["k1"])
        cl._final_key_attempt = False
        chain = providers._model_list(cl.m["chat"], cl.m["chat_alt"])
        behaviour = {m: RuntimeError("Error code: 429 - rate_limit_exceeded") for m in chain}
        behaviour[chain[-1]] = "تمام"
        fake = _FakeChat(behaviour)
        with mock.patch.object(cl, "_openai", return_value=fake):
            self.assertEqual(cl._oa_chat("sys", "النص", 0.2), "تمام")
        self.assertEqual(fake.calls[-1], (chain[-1], 0))
        self.assertEqual(fake.calls[0][1], 0)

    def test_default_final_key_attempt_keeps_last_model_retry(self):
        cl = self._client(["k1"])
        chain = providers._model_list(cl.m["chat"], cl.m["chat_alt"])
        behaviour = {m: RuntimeError("Error code: 429 - rate_limit_exceeded") for m in chain}
        behaviour[chain[-1]] = "تمام"
        fake = _FakeChat(behaviour)
        with mock.patch.object(cl, "_openai", return_value=fake):
            self.assertEqual(cl._oa_chat("sys", "النص", 0.2), "تمام")
        self.assertEqual(fake.calls[-1], (chain[-1], 1))

    def test_run_sets_final_key_attempt_per_key(self):
        cl = self._client(["k1", "k2"])
        seen = []

        def fn(*args):
            seen.append(cl._final_key_attempt)
            raise RuntimeError("429 rate_limit_exceeded")

        with mock.patch.object(cl, "_oa_transcribe", side_effect=fn):
            with self.assertRaises(RuntimeError):
                cl.transcribe("wav")
        self.assertEqual(seen, [False, True])

    def test_oa_chat_rate_not_masked_by_last_model_unavailable(self):
        cl = self._client(["k1"])
        chain = providers._model_list(cl.m["chat"], cl.m["chat_alt"])
        behaviour = {m: RuntimeError("Error code: 429 - rate_limit_exceeded") for m in chain}
        behaviour[chain[-1]] = RuntimeError("Error code: 404 - model_not_found does not exist")
        fake = _FakeChat(behaviour)
        with mock.patch.object(cl, "_openai", return_value=fake):
            with self.assertRaises(RuntimeError) as ctx:
                cl._oa_chat("sys", "النص", 0.2)
        self.assertIn("429", str(ctx.exception))
        self.assertIn((cl.id, providers._key_fingerprint("k1"), chain[-1]),
                      providers._UNAVAILABLE_MODELS)


class TestNoKeyLeaked(_Base):
    """المفتاح عمره ما يظهر في اللوج أو في رسالة خطأ."""

    def test_no_key_in_logged_message(self):
        cl = providers.Client("groq", "k1", keys=["k1", "k2"])
        logged = []

        def fake_log(e, where=""):
            logged.append(str(e))

        with mock.patch.object(cl, "_oa_chat", side_effect=RuntimeError("429 rate_limit_exceeded")), \
                mock.patch("core.log_error", side_effect=fake_log):
            cl._chat("sys", "النص", 0.2)
        self.assertTrue(logged)
        for msg in logged:
            self.assertNotIn("k1", msg)
            self.assertNotIn("k2", msg)


class TestReviewFixes(_Base):
    """مراجعة: Gemini 400 مفتاح غلط، المدة بس بعد «try again in»، وإعادات التفريغ."""

    def test_gemini_400_api_key_not_valid_is_invalid(self):
        e = RuntimeError("HTTP 400: API key not valid. Please pass a valid API key.")
        self.assertEqual(providers._key_error_kind(e), "invalid")
        self.assertIsNone(providers._key_error_kind(RuntimeError("HTTP 400: bad request")))

    def test_try_again_ignores_numbers_after_the_duration(self):
        msg = "Rate limit reached. Please try again in 7.66s. Need more tokens? Limit 6000 TPM, 30 m"
        self.assertAlmostEqual(providers._cooldown_for(msg), 7.66)

    def _stt(self, final):
        cl = providers.Client("groq", "k-aaaa-1111")
        cl._final_key_attempt = final
        fake = mock.Mock()
        fake.timeout = None
        fake.with_options.return_value = fake
        fake.audio.transcriptions.create.return_value = SimpleNamespace(text="تمام")
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "a.wav")
            open(wav, "wb").close()
            with mock.patch.object(cl, "_openai", return_value=fake):
                self.assertEqual(cl._oa_transcribe(wav, "ar"), "تمام")
        return fake

    def test_stt_last_key_keeps_sdk_default_retries(self):
        # مفتاح واحد (أو آخر مفتاح): زي قبل المرحلة — خطأ 5xx عابر لسه بيتعاد
        self.assertFalse(self._stt(True).with_options.called)

    def test_stt_with_another_key_left_switches_without_waiting(self):
        fake = self._stt(False)
        fake.with_options.assert_called_with(max_retries=0)


if __name__ == "__main__":
    unittest.main()
