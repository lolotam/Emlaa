# -*- coding: utf-8 -*-
"""
سلسلة بدائل موديل الشات (Groq): الموديل اللي يرجّع model_not_found بيتشال من السلسلة
لباقي الجلسة — عشان مانضيّعش عليه نداء كل مرة، والمحاولة التانية بعد الانتظار (للموديل
الأخير بس) تروح لآخر موديل شغّال مش لموديل ميت. مفيش شبكة: client مزيّف.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import providers  # noqa: E402


class _FakeOpenAI:
    """client مزيّف: لكل موديل يا رد يا استثناء، وبيسجّل الموديلات وmax_retries."""

    def __init__(self, behaviour):
        self.behaviour = behaviour          # model -> str (رد) أو Exception
        self.calls = []                     # (model, max_retries)
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


RATE = RuntimeError("Error code: 429 - rate_limit_exceeded")
GONE = RuntimeError("Error code: 404 - The model `llama-3.3-70b-versatile` does not exist "
                    "or you do not have access to it. model_not_found")


class TestUnavailableModelsAreSkipped(unittest.TestCase):
    def setUp(self):
        providers._UNAVAILABLE_MODELS.clear()
        self.addCleanup(providers._UNAVAILABLE_MODELS.clear)
        self.cl = providers.Client("groq", "test-key")
        self.chain = providers._model_list(self.cl.m["chat"], self.cl.m["chat_alt"])

    def _run(self, behaviour):
        fake = _FakeOpenAI(behaviour)
        with mock.patch.object(self.cl, "_openai", return_value=fake):
            try:
                out = self.cl._oa_chat("sys", "النص", 0.2)
            except RuntimeError:
                out = None
        return out, fake.calls

    def test_retired_model_is_dropped_for_the_session(self):
        # كله زحمة والأخير ميت: أول مرة بنجرّبه ونعرف إنه ميت…
        everything_busy = {m: RATE for m in self.chain}
        everything_busy[self.chain[-1]] = GONE
        _, calls = self._run(everything_busy)
        self.assertEqual(calls[-1][0], self.chain[-1])
        # …المرة الجاية مبيتنادهش، والمحاولة التانية (max_retries=1) راحت لآخر موديل شغّال
        _, calls = self._run(everything_busy)
        self.assertNotIn(self.chain[-1], [m for m, _ in calls])
        self.assertEqual(calls[-1], (self.chain[-2], 1))

    def test_rate_limit_alone_never_drops_a_model(self):
        busy_then_ok = {m: RATE for m in self.chain}
        busy_then_ok[self.chain[-1]] = "تمام"
        self._run(busy_then_ok)
        self.assertEqual(providers._UNAVAILABLE_MODELS, set())
        _, calls = self._run(busy_then_ok)
        self.assertEqual([m for m, _ in calls], self.chain)

    def test_all_unavailable_falls_back_to_the_full_list(self):
        # لو كل الموديلات اتعلّمت مش متاحة بنجرّب القايمة كاملة تاني (يمكن الحساب اتغيّر)
        for m in self.chain:
            providers._UNAVAILABLE_MODELS.add(("groq", m))
        ok = {m: "تمام" for m in self.chain}
        out, calls = self._run(ok)
        self.assertEqual(out, "تمام")
        self.assertEqual(calls[0][0], self.chain[0])

    def test_unavailable_is_per_provider(self):
        providers._UNAVAILABLE_MODELS.add(("openai", self.chain[0]))
        _, calls = self._run({m: "تمام" for m in self.chain})
        self.assertEqual(calls[0][0], self.chain[0])     # مزوّد تاني — Groq لسه بيجرّبه


if __name__ == "__main__":
    unittest.main()
