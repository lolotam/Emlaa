# -*- coding: utf-8 -*-
"""
اختبارات Deepgram — قرار الـfallback لكعربي في وضع التعرّف التلقائي.
مفيش شبكة: _deepgram_request متزوّد stub بيرجّع خطأ بحالة HTTP معيّنة.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import providers  # noqa: E402
import core       # noqa: E402


def make_client():
    return providers.Client("deepgram", "test-key")


def _err(status, msg="boom"):
    e = RuntimeError(msg)
    e.status = status
    return e


class TestDeepgramTranscribeFallback(unittest.TestCase):
    """الـfallback لكعربي بيحصل بس على 400؛ غير كده بيطلع للمستخدم زي ما هو."""

    def test_400_falls_back_to_arabic(self):
        cl = make_client()
        with mock.patch.object(cl, "_deepgram_request",
                               side_effect=[_err(400), ("النص", "ar")]) as req, \
                mock.patch.object(core, "log_error"):
            text = cl._deepgram_transcribe("wav", None)
        self.assertEqual(text, "النص")
        self.assertEqual(req.call_args_list[0].args, ("wav", None))
        self.assertEqual(req.call_args_list[1].args, ("wav", "ar"))

    def test_401_propagates_called_once(self):
        cl = make_client()
        with mock.patch.object(cl, "_deepgram_request", side_effect=_err(401)) as req, \
                mock.patch.object(core, "log_error"):
            with self.assertRaises(RuntimeError):
                cl._deepgram_transcribe("wav", None)
        self.assertEqual(req.call_count, 1)

    def test_network_error_propagates_called_once(self):
        cl = make_client()
        with mock.patch.object(cl, "_deepgram_request", side_effect=_err(None)) as req, \
                mock.patch.object(core, "log_error"):
            with self.assertRaises(RuntimeError):
                cl._deepgram_transcribe("wav", None)
        self.assertEqual(req.call_count, 1)


if __name__ == "__main__":
    unittest.main()
