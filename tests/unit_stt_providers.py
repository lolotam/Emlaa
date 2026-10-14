# -*- coding: utf-8 -*-
"""
اختبارات مزوّدي التفريغ الجداد (xAI Grok و Z.ai GLM) وموديلات التفريغ الجديدة
(gpt-transcribe و gemini-3.5-transcribe). مفيش شبكة: بنزوّد urlopen أو _post_multipart
أو _post_json بـ stub ونختبر شكل الطلب والقرار بعد كل رد.
"""
import io
import os
import sys
import json
import wave
import tempfile
import unittest
import urllib.error
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart       # noqa: E402
import providers   # noqa: E402


def _http_error(code, body=b"{}"):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


def _wav_bytes(seconds, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return buf.getvalue()


def _duration(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / w.getframerate()


class _TmpWav:
    """ملف WAV حقيقي في مجلد مؤقت — المسارات بتقرا الملف من القرص."""

    def __init__(self, seconds=1):
        self.seconds = seconds

    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        path = os.path.join(self._dir.name, "a.wav")
        with open(path, "wb") as f:
            f.write(_wav_bytes(self.seconds))
        return path

    def __exit__(self, *exc):
        self._dir.cleanup()


class _Response:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _field_names(fields):
    return [name for name, _ in fields]


# ── شكل طلب الـmultipart ─────────────────────────────────────────────────────
class TestPostMultipart(unittest.TestCase):
    def test_fields_in_order_repeated_names_and_file_last(self):
        seen = {}

        def urlopen(req, **kw):
            seen["req"] = req
            return _Response({"text": "تمام"})

        with mock.patch.object(providers.urllib.request, "urlopen", side_effect=urlopen):
            out = providers._post_multipart(
                "https://api.example/stt",
                [("model", "m1"), ("keyterm", "Python"), ("keyterm", "إملاء")],
                "audio.wav", b"WAVDATA", {"Authorization": "Bearer k"})

        self.assertEqual(out, {"text": "تمام"})
        req = seen["req"]
        body = req.data.decode("utf-8")
        boundary = req.get_header("Content-type").split("boundary=")[1]
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        self.assertEqual(body.count('name="keyterm"'), 2)
        self.assertIn("إملاء", body)
        positions = [body.index('name="model"'), body.index("Python"),
                     body.index('name="file"; filename="audio.wav"')]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(body.endswith(f"WAVDATA\r\n--{boundary}--\r\n"))


# ── تقسيم الصوت لـ Z.ai ──────────────────────────────────────────────────────
class TestWavChunks(unittest.TestCase):
    def test_audio_up_to_the_limit_stays_one_untouched_chunk(self):
        for seconds in (10, 28):
            with self.subTest(seconds=seconds):
                audio = _wav_bytes(seconds)
                self.assertEqual(providers._wav_chunks(audio, 28), [audio])

    def test_long_audio_splits_into_valid_wavs_covering_everything(self):
        chunks = providers._wav_chunks(_wav_bytes(60), 28)
        self.assertEqual([_duration(c) for c in chunks], [28, 28, 4])


# ── xAI Grok ─────────────────────────────────────────────────────────────────
class TestXaiTranscribe(unittest.TestCase):
    def setUp(self):
        self.cl = providers.Client("xai", "xai-test")
        self.cl.vocab = ["Python", " ", "x" * 60]

    def test_sends_language_and_keyterms_to_the_stt_endpoint(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart",
                                  return_value={"text": " النص \n"}) as post:
            self.assertEqual(self.cl._xai_transcribe(wav, "ar"), "النص")
        url, fields, _name, _audio, headers = post.call_args.args
        self.assertEqual(url, providers.XAI_STT_URL)
        self.assertEqual(headers, {"Authorization": "Bearer xai-test"})
        # language بيشتغل مع format=true بس (الافتراضي false)
        self.assertEqual(fields, [("model", "grok-voice-transcribe-2.0"), ("format", "true"),
                                  ("language", "ar"), ("keyterm", "Python"), ("keyterm", "x" * 50)])
        self.assertEqual(self.cl.last_stt_model, "grok-voice-transcribe-2.0")

    def test_auto_language_sends_no_language_or_format_field(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart", return_value={"text": "hi"}) as post:
            self.cl._xai_transcribe(wav, None)
        names = _field_names(post.call_args.args[1])
        self.assertNotIn("language", names)
        self.assertNotIn("format", names)

    def test_400_retries_same_model_without_hints(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart",
                                  side_effect=[_http_error(400), {"text": "تمام"}]) as post:
            self.assertEqual(self.cl._xai_transcribe(wav, "ar"), "تمام")
        retry = post.call_args_list[1].args[1]
        self.assertEqual(retry, [("model", "grok-voice-transcribe-2.0")])

    def test_404_falls_back_to_the_next_model(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart",
                                  side_effect=[_http_error(404), {"text": "تمام"}]) as post:
            self.cl._xai_transcribe(wav, "ar")
        self.assertEqual(post.call_args_list[1].args[1][0], ("model", "grok-voice-transcribe-1.0"))
        self.assertEqual(self.cl.last_stt_model, "grok-voice-transcribe-1.0")

    def test_401_is_raised_without_trying_anything_else(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart",
                                  side_effect=_http_error(401, b'{"error":"bad key"}')) as post:
            with self.assertRaises(RuntimeError) as cm:
                self.cl._xai_transcribe(wav, "ar")
        self.assertEqual(post.call_count, 1)
        self.assertIn("HTTP 401", str(cm.exception))

    def test_network_failure_becomes_network_error(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart",
                                  side_effect=urllib.error.URLError("dns fail")):
            with self.assertRaises(providers.NetworkError):
                self.cl._xai_transcribe(wav, "ar")

    def test_client_transcribe_goes_to_the_xai_endpoint(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart", return_value={"text": "تمام"}) as post:
            self.assertEqual(self.cl.transcribe(wav, "ar"), "تمام")
        self.assertEqual(post.call_args.args[0], providers.XAI_STT_URL)


# ── Z.ai GLM ─────────────────────────────────────────────────────────────────
class TestZaiTranscribe(unittest.TestCase):
    def setUp(self):
        self.cl = providers.Client("zai", "zai-test")

    def test_short_audio_is_one_request_with_hotwords(self):
        self.cl.vocab = ["Emlaa"]
        with _TmpWav(5) as wav, \
                mock.patch.object(providers, "_post_multipart", return_value={"text": "تمام"}) as post:
            self.assertEqual(self.cl._zai_transcribe(wav), "تمام")
        url, fields = post.call_args.args[:2]
        self.assertEqual(url, providers.ZAI_STT_URL)
        self.assertEqual(fields, [("model", "glm-asr-2512"), ("hotwords", "Emlaa")])

    def test_long_audio_is_split_and_earlier_text_is_the_prompt(self):
        replies = [{"text": "الأول"}, {"text": "التاني"}, {"text": "التالت"}]
        with _TmpWav(60) as wav, \
                mock.patch.object(providers, "_post_multipart", side_effect=replies) as post:
            self.assertEqual(self.cl._zai_transcribe(wav), "الأول التاني التالت")
        calls = post.call_args_list
        self.assertEqual([_duration(c.args[3]) for c in calls], [28, 28, 4])
        self.assertNotIn("prompt", _field_names(calls[0].args[1]))
        self.assertIn(("prompt", "الأول"), calls[1].args[1])
        self.assertIn(("prompt", "الأول التاني"), calls[2].args[1])

    def test_client_transcribe_goes_to_the_zai_endpoint(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_multipart", return_value={"text": "تمام"}) as post:
            self.assertEqual(self.cl.transcribe(wav, "ar"), "تمام")
        self.assertEqual(post.call_args.args[0], providers.ZAI_STT_URL)


# ── OpenRouter ───────────────────────────────────────────────────────────────
class TestOpenRouterTranscribe(unittest.TestCase):
    def setUp(self):
        self.cl = providers.Client("openrouter", "sk-or-test", model="openai/gpt-4o-transcribe",
                                   strict=True)

    def test_sends_base64_wav_with_language_and_keyterms(self):
        self.cl.vocab = ["Emlaa"]
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_json", return_value={"text": " تمام "}) as post:
            self.assertEqual(self.cl.transcribe(wav, "ar"), "تمام")
            with open(wav, "rb") as f:
                expected_audio = providers.base64.b64encode(f.read()).decode("ascii")
        url, body, headers = post.call_args.args
        self.assertEqual(url, providers.OPENROUTER_STT_URL)
        self.assertEqual(headers, {"Authorization": "Bearer sk-or-test"})
        self.assertEqual(body, {"model": "openai/gpt-4o-transcribe",
                                "input_audio": {"data": expected_audio, "format": "wav"},
                                "keyterms": ["Emlaa"], "language": "ar"})
        self.assertEqual(self.cl.last_stt_model, "openai/gpt-4o-transcribe")

    def test_400_retries_without_language_and_keyterms(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_json",
                                  side_effect=[_http_error(400), {"text": "تمام"}]) as post:
            self.assertEqual(self.cl.transcribe(wav, "ar"), "تمام")
        self.assertEqual(set(post.call_args_list[1].args[1]), {"model", "input_audio"})


# ── OpenAI gpt-transcribe ────────────────────────────────────────────────────
class TestOpenAiLanguageArgs(unittest.TestCase):
    def test_language_fields_sent_to_the_sdk_per_model(self):
        cases = [
            # gpt-transcribe: languages بدل language، وكلمات القاموس في keywords
            ("gpt-transcribe", "ar", ["Emlaa"],
             {"extra_body": {"languages": ["ar"], "keywords": ["Emlaa"]}}),
            # لغة تلقائي: من غير languages خالص عشان الموديل يتعرّف على أي لغة
            ("gpt-transcribe", None, [], {}),
            ("gpt-transcribe", None, ["Emlaa"], {"extra_body": {"keywords": ["Emlaa"]}}),
            # OpenAI بيرفض الطلب كله لو keyword فيها < > أو سطر جديد — بنسيبها والباقي يتبعت
            ("gpt-transcribe", "ar", ["vector<T>", "a\nb", "x\ry", "Emlaa"],
             {"extra_body": {"languages": ["ar"], "keywords": ["Emlaa"]}}),
            ("gpt-transcribe", "ar", ["a>b"], {"extra_body": {"languages": ["ar"]}}),
            ("gpt-4o-transcribe", "ar", ["Emlaa"], {"language": "ar"}),
            ("whisper-1", None, [], {}),
        ]
        for model, language, vocab, expected in cases:
            with self.subTest(model=model, language=language):
                cl = providers.Client("openai", "sk-test", model=model, strict=True)
                cl.vocab = vocab
                sdk = mock.Mock()
                sdk.timeout = None
                sdk.audio.transcriptions.create.return_value = mock.Mock(text=" تمام ")
                with _TmpWav() as wav, mock.patch.object(cl, "_openai", return_value=sdk):
                    self.assertEqual(cl._oa_transcribe(wav, language), "تمام")
                kw = sdk.audio.transcriptions.create.call_args.kwargs
                sent = {k: kw[k] for k in ("language", "extra_body") if k in kw}
                self.assertEqual(sent, expected)


# ── Gemini 3.5 Transcribe ────────────────────────────────────────────────────
def _interaction(text):
    return {"status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


class TestGeminiTranscribeModel(unittest.TestCase):
    def setUp(self):
        self.cl = providers.Client("gemini", "g-key", model="gemini-3.5-transcribe", strict=True)

    def test_uses_interactions_with_transcription_config(self):
        self.cl.vocab = ["Emlaa"]
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_json", return_value=_interaction(" تمام ")) as post:
            self.assertEqual(self.cl._gemini_transcribe(wav, "ar"), "تمام")
        url, payload, headers = post.call_args.args
        self.assertEqual(url, providers.GEMINI_API + "/interactions")
        self.assertEqual(headers, {"x-goog-api-key": "g-key"})
        self.assertEqual(payload["model"], "gemini-3.5-transcribe")
        self.assertEqual(payload["input"][0]["type"], "audio")
        self.assertEqual(payload["input"][0]["mime_type"], "audio/wav")
        self.assertEqual(payload["generation_config"]["transcription_config"],
                         {"language_codes": ["ar"], "custom_vocabulary": ["Emlaa"]})
        self.assertEqual(self.cl.last_stt_model, "gemini-3.5-transcribe")

    def test_auto_language_sends_an_empty_language_list(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_json", return_value=_interaction("hi")) as post:
            self.cl._gemini_transcribe(wav, None)
        self.assertEqual(post.call_args.args[1]["generation_config"]["transcription_config"],
                         {"language_codes": []})

    def test_400_retries_without_the_transcription_config(self):
        with _TmpWav() as wav, \
                mock.patch.object(providers, "_post_json",
                                  side_effect=[_http_error(400), _interaction("تمام")]) as post:
            self.assertEqual(self.cl._gemini_transcribe(wav, "ar"), "تمام")
        self.assertEqual(post.call_args_list[1].args[1]["generation_config"],
                         {"transcription_config": {}})

    def test_flash_models_still_use_generate_content(self):
        cl = providers.Client("gemini", "g-key", model="gemini-3.8-flash", strict=True)
        body = {"candidates": [{"content": {"parts": [{"text": "تمام"}]}}]}
        with _TmpWav() as wav, mock.patch.object(providers, "_post_json", return_value=body) as post:
            self.assertEqual(cl._gemini_transcribe(wav, "ar"), "تمام")
        self.assertTrue(post.call_args.args[0].endswith("/models/gemini-3.8-flash:generateContent"))

    def test_interaction_text_ignores_non_output_steps(self):
        resp = {"steps": [{"type": "thought", "content": [{"type": "text", "text": "x"}]},
                          {"type": "model_output", "content": [{"type": "text", "text": "a"},
                                                               {"type": "text", "text": "b"}]}]}
        self.assertEqual(providers._interaction_text(resp), "ab")
        self.assertEqual(providers._interaction_text({}), "")


# ── التأكد من المفتاح ────────────────────────────────────────────────────────
class TestVerifySttOnlyProviders(unittest.TestCase):
    def test_xai_key_prefix_is_checked_before_any_request(self):
        with mock.patch.object(providers, "_post_multipart") as post:
            ok, msg = providers.verify("xai", "wrong-key")
        self.assertFalse(ok)
        self.assertIn("xai", msg)
        post.assert_not_called()

    def test_400_on_silent_audio_means_the_key_works(self):
        with mock.patch.object(providers, "_post_multipart", side_effect=_http_error(400)) as post:
            self.assertEqual(providers.verify("zai", "zai-key"), (True, ""))
        url, fields, _name, _audio, headers = post.call_args.args
        self.assertEqual(url, providers.ZAI_STT_URL)
        self.assertEqual(fields, [("model", "glm-asr-2512")])
        self.assertEqual(headers, {"Authorization": "Bearer zai-key"})

    def test_key_is_checked_on_a_free_endpoint_without_any_paid_request(self):
        cases = [("xai", "xai-key", "https://api.x.ai/v1/api-key"),
                 ("openrouter", "sk-or-key", "https://openrouter.ai/api/v1/key"),
                 ("vercel", "v-key", "https://ai-gateway.vercel.sh/v1/credits")]
        for pid, key, url in cases:
            with self.subTest(pid=pid),                     mock.patch.object(providers, "_get_json", return_value={}) as get,                     mock.patch.object(providers, "_post_json") as post_json,                     mock.patch.object(providers, "_post_multipart") as post_multi:
                self.assertEqual(providers.verify(pid, key), (True, ""))
                self.assertEqual(get.call_args.args[:2], (url, {"Authorization": "Bearer " + key}))
                post_json.assert_not_called()
                post_multi.assert_not_called()

    def test_rejected_or_blocked_key_fails_verification(self):
        cases = [(dict(side_effect=_http_error(401)), "المفتاح مش مقبول — اتأكد إنك نسخته كامل"),
                 # xAI بيرجّع 200 لمفتاح متوقف — الحالة في الرد
                 (dict(return_value={"api_key_blocked": False, "api_key_disabled": True}),
                  "المفتاح مرفوض أو الصلاحية محظورة — اتأكد من صلاحيات الحساب")]
        for stub, msg in cases:
            with self.subTest(msg=msg), mock.patch.object(providers, "_get_json", **stub):
                self.assertEqual(providers.verify("xai", "xai-bad"), (False, msg))


# ── التسجيل في الإعدادات ─────────────────────────────────────────────────────
class TestRegistry(unittest.TestCase):
    def test_features_accept_them_for_stt_but_not_for_ai(self):
        def features(stt, ai):
            return {m: {"hotkey": [0x70 + i], "stt": stt, "ai": ai}
                    for i, m in enumerate(smart.FEATURES)}
        stt = [{"provider": "xai", "model": "grok-voice-transcribe-2.0"},
               {"provider": "zai", "model": "glm-asr-2512"},
               {"provider": "openrouter", "model": "openai/whisper-large-v3-turbo"}]
        self.assertIsNone(smart.validate_features(features(stt, [])))
        self.assertEqual(smart.validate_features(features(stt, [{"provider": "zai", "model": "x"}])),
                         "المعالجة محتاجة مزوّد بيعرف يكتب (مش مزوّد تفريغ بس ولا الموديل المحلي)")

    def test_keys_are_read_from_their_env_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, ".env")
            with open(env, "w", encoding="utf-8") as f:
                f.write("XAI_API_KEY=xai-1,xai-2\nZAI_API_KEY=z1\n")
            self.assertEqual(providers.read_key_pools(env),
                             {"xai": ["xai-1", "xai-2"], "zai": ["z1"]})


if __name__ == "__main__":
    unittest.main()
