# -*- coding: utf-8 -*-
"""
التسجيلات اللي فشل تفريغها: الصوت بيتحفظ (WAV + MP3 + ملف بياناتها)، بتظهر في السجل كـ«فشل»
برّه حد آخر ١٠، ومابتتمسحش غير بفعل صريح (مسح / مسح الكل / تفريغ يدوي ناجح) — حتى لو
ملف السجل باظ. ملفات مؤقتة بس، من غير صوت حقيقي ولا شبكة.
"""
import json
import os
import sys
import tempfile
import time
import unittest
import wave
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core  # noqa: E402


def _fake_lameenc():
    fake = mock.MagicMock()
    fake.Encoder.return_value.encode.return_value = b"mp3"
    fake.Encoder.return_value.flush.return_value = b""
    return fake


class _Store(unittest.TestCase):
    """سجل ومجلد تسجيلات مؤقتين، وlameenc مزيّف، وحد «آخر 10» شغّال."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.hist = os.path.join(self.d, "history.json")
        self.recs = os.path.join(self.d, "recs")
        for p in (mock.patch.object(core, "HISTORY_PATH", self.hist),
                  mock.patch.object(core, "RECORDINGS_DIR", self.recs),
                  mock.patch.object(core, "CFG", dict(core.DEFAULTS, history_keep_last10=True)),
                  mock.patch.object(core, "log_error"),
                  mock.patch.dict(sys.modules, {"lameenc": _fake_lameenc()})):
            p.start()
            self.addCleanup(p.stop)

    def make_wav(self, name="in.wav"):
        path = os.path.join(self.d, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x01\x00" * 1600)
        return path

    def items(self):
        with open(self.hist, encoding="utf-8") as f:
            return json.load(f)

    def keep(self, mode="normal", error="مفيش اتصال بالنت", **kw):
        return core.keep_failed_recording(mode, self.make_wav(), error, **kw)

    def files(self, rid):
        return {ext for ext in ("wav", "json", "mp3")
                if os.path.exists(os.path.join(self.recs, "%d.%s" % (rid, ext)))}


class TestKeepFailed(_Store):
    def test_failed_recording_is_listed_with_its_audio_and_sidecar(self):
        rid = self.keep("prompt", app="chrome", dur=1.5)
        entry = self.items()[0]
        self.assertEqual(entry["id"], rid)
        self.assertEqual((entry["status"], entry["error"], entry["result"], entry["words"]),
                         ("failed", "مفيش اتصال بالنت", "", 0))
        self.assertEqual((entry["mode"], entry["app"], entry["dur"]), ("prompt", "chrome", 1.5))
        self.assertEqual(self.files(rid), {"wav", "json", "mp3"})

    def test_wav_copy_failure_writes_nothing(self):
        with mock.patch.object(core.shutil, "copyfile", side_effect=OSError("disk full")):
            self.assertIsNone(self.keep())
        self.assertFalse(os.path.exists(self.hist))
        self.assertEqual([n for n in os.listdir(self.recs)] if os.path.exists(self.recs) else [], [])

    def test_history_write_failure_keeps_audio_and_recovery_lists_it_later(self):
        with mock.patch.object(core, "_write_list", side_effect=OSError("locked")):
            self.assertIsNone(self.keep())
        wavs = [n for n in os.listdir(self.recs) if n.endswith(".wav")]
        self.assertEqual(len(wavs), 1)
        core.recordings_prune()
        self.assertEqual([i["status"] for i in self.items()], ["failed"])

    def test_distinct_ids_under_a_fixed_clock(self):
        with mock.patch.object(core, "_now_ms", return_value=1_000_000):
            a = self.keep()
            b = core.history_add("normal", "كلام", "كلام")
            c = self.keep()
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual(self.files(a), {"wav", "json", "mp3"})
        self.assertEqual(self.files(c), {"wav", "json", "mp3"})


class TestRetention(_Store):
    def add_successes(self, n):
        return [core.history_add("normal", "كلام %d" % k, "كلام %d" % k) for k in range(n)]

    def test_failed_entries_stay_beyond_the_cap(self):
        failed = [self.keep(), self.keep()]
        self.add_successes(12)
        items = self.items()
        self.assertEqual(sum(1 for i in items if i.get("status") == "failed"), 2)
        self.assertEqual(sum(1 for i in items if i.get("status") != "failed"), 10)
        self.assertTrue(all(self.files(r) == {"wav", "json", "mp3"} for r in failed))

    def test_corrupt_history_never_costs_a_failed_recording(self):
        rid = self.keep()
        with open(self.hist, "w", encoding="utf-8") as f:
            f.write("{not json")
        core.history_add("normal", "جديد", "جديد")    # بيعمل backup للبايظ ويبدأ قايمة جديدة
        core.recordings_prune()
        self.assertIn(rid, [i["id"] for i in self.items() if i.get("status") == "failed"])
        self.assertEqual(self.files(rid), {"wav", "json", "mp3"})

    def test_success_audio_quota_follows_history_order(self):
        ids = self.add_successes(11)
        os.makedirs(self.recs, exist_ok=True)
        for rid in ids:
            with open(core.recording_path(rid), "wb") as f:
                f.write(b"mp3")
        core.recordings_prune()
        kept = {r for r in ids if os.path.exists(core.recording_path(r))}
        self.assertEqual(kept, {i["id"] for i in self.items()[:10]})

    def test_stats_ignore_failed_entries(self):
        self.keep(raw="تعليمات مش محسوبة")
        core.history_add("normal", "كلمتين بس", "كلمتين بس", dur=1.0)
        stats = core.history_stats()
        self.assertEqual((stats["count"], stats["words"]), (1, 2))

    def test_full_read_returns_more_than_the_old_limit(self):
        failed = [self.keep() for _ in range(3)]
        self.assertEqual(len(core.history_get(limit=None)), 3)
        self.assertEqual(len(core.history_get(limit=2)), 2)
        self.assertEqual(len(failed), 3)


class TestExplicitRemoval(_Store):
    def test_delete_removes_sidecar_audio_and_never_resurrects(self):
        rid = self.keep()
        core.history_delete([rid])
        core.recordings_prune()
        self.assertEqual(self.files(rid), set())
        self.assertEqual(self.items(), [])

    def test_clear_removes_every_failed_recording(self):
        rids = [self.keep(), self.keep()]
        core.history_clear()
        core.recordings_prune()
        self.assertTrue(all(self.files(r) == set() for r in rids))
        self.assertFalse(os.path.exists(self.hist) and self.items())

    def test_failed_sidecar_removal_leaves_a_tombstone_recovery_skips(self):
        rid = self.keep()
        real_remove = os.remove

        def remove(path):
            if path.endswith(".json"):
                raise PermissionError("locked")
            real_remove(path)

        with mock.patch.object(core.os, "remove", side_effect=remove):
            core.history_delete([rid])
        core.recordings_prune()
        self.assertEqual(self.items(), [])
        with open(os.path.join(self.recs, "%d.json" % rid), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"deleted": True})

    def test_delete_whose_history_write_fails_keeps_the_files(self):
        rid = self.keep()
        with mock.patch.object(core, "_write_list", side_effect=OSError("locked")):
            core.history_delete([rid])
        self.assertEqual(self.files(rid), {"wav", "json", "mp3"})


class TestResolve(_Store):
    def test_resolution_moves_entry_to_top_and_removes_failure_files(self):
        rid = self.keep(dur=2.0)
        old_time = self.items()[0]["time"]
        core.history_add("normal", "بعده", "بعده")
        self.assertTrue(core.history_resolve(rid, "الكلام", "الكلام.", {"stt": "Groq"}))
        top = self.items()[0]
        self.assertEqual(top["id"], rid)
        self.assertNotIn("status", top)
        self.assertNotIn("error", top)
        self.assertEqual((top["raw"], top["result"], top["words"], top["dur"], top["recorded"]),
                         ("الكلام", "الكلام.", 1, 2.0, old_time))
        self.assertEqual(self.files(rid), {"mp3"})

    def test_resolution_of_a_deleted_entry_is_refused(self):
        rid = self.keep()
        core.history_delete([rid])
        self.assertFalse(core.history_resolve(rid, "x", "x", None))

    def test_resolved_old_entry_keeps_its_audio_among_newer_successes(self):
        rid = self.keep()
        newer = [core.history_add("normal", "ك", "ك %d" % k) for k in range(10)]
        for r in newer:
            with open(core.recording_path(r), "wb") as f:
                f.write(b"mp3")
        core.history_resolve(rid, "ك", "ك", None)
        core.recordings_prune()
        self.assertIn(rid, [i["id"] for i in self.items()])
        self.assertTrue(os.path.exists(core.recording_path(rid)))

    def test_fail_again_updates_the_error(self):
        rid = self.keep()
        self.assertTrue(core.history_fail_again(rid, "المفتاح مش مقبول"))
        self.assertEqual(self.items()[0]["error"], "المفتاح مش مقبول")


class TestStrayTemp(_Store):
    def test_only_old_temp_files_are_removed(self):
        os.makedirs(self.recs)
        old = os.path.join(self.recs, "1.ab.wav.tmp")
        fresh = os.path.join(self.recs, "2.mp3.tmp")
        for p in (old, fresh):
            with open(p, "wb") as f:
                f.write(b"x")
        ten_min_ago = time.time() - 700
        os.utime(old, (ten_min_ago, ten_min_ago))
        core.recordings_prune()
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))


class _ConvClient:
    """عميل ميزة مزيّف: بيسجّل النداءات، وai_ok زي FeatureClient."""

    def __init__(self, ai_ok=True):
        self.calls, self.ai_ok = [], ai_ok

    def to_prompt(self, t):
        self.calls.append("prompt")
        return "PROMPT:" + t if self.ai_ok else t

    def translate(self, t):
        self.calls.append("translate")
        return "EN:" + t if self.ai_ok else t

    def polish(self, t, profile=None):
        self.calls.append(("polish", profile))
        return "P:" + t


def _cfg_with_ai(mode=None, ai=True, **over):
    cfg = dict(core.DEFAULTS, **over)
    cfg["features"] = json.loads(json.dumps(core.DEFAULTS["features"]))
    if mode and not ai:
        cfg["features"][mode]["ai"] = []
    return cfg


class TestConvertText(unittest.TestCase):
    """المعالجة المشتركة بين التسجيل الحي والتفريغ اليدوي."""

    def convert(self, mode, text, cfg=None, client=None, app=""):
        client = client or _ConvClient()
        with mock.patch.object(core, "CFG", cfg or _cfg_with_ai()):
            return core.convert_text(client, mode, text, app), client

    def test_prompt_and_translate_use_their_operation(self):
        for mode, want in (("prompt", "PROMPT:طلب"), ("translate", "EN:طلب")):
            with self.subTest(mode=mode):
                conv, cl = self.convert(mode, "طلب")
                self.assertEqual((conv.out, conv.ai_failed), (want, False))
                self.assertEqual(cl.calls, [mode])

    def test_failed_conversion_is_flagged(self):
        conv, _ = self.convert("prompt", "طلب", client=_ConvClient(ai_ok=False))
        self.assertEqual((conv.out, conv.ai_failed), ("طلب", True))

    def test_empty_ai_list_calls_no_model(self):
        conv, cl = self.convert("translate", "طلب", cfg=_cfg_with_ai("translate", ai=False))
        self.assertEqual((conv.out, conv.ai_failed, cl.calls), ("طلب", False, []))

    def test_normal_polishes_with_the_app_profile(self):
        conv, cl = self.convert("normal", "الكلام ده جملة طويلة شوية عشان تتنضّف", app="code")
        self.assertEqual(conv.out, "P:الكلام ده جملة طويلة شوية عشان تتنضّف")
        self.assertEqual(cl.calls, [("polish", "dev")])
        self.assertFalse(conv.raw)

    def test_normal_raw_when_polish_is_off(self):
        conv, cl = self.convert("normal", "الكلام زي ما هو", cfg=_cfg_with_ai(polish=False))
        self.assertEqual((conv.out, conv.raw, cl.calls), ("الكلام زي ما هو", True, []))

    def test_snippet_expands_without_a_model(self):
        cfg = _cfg_with_ai(snippets=[{"trigger": "إيميلي", "text": "me@example.com"}])
        conv, cl = self.convert("normal", "إيميلي", cfg=cfg)
        self.assertEqual((conv.out, conv.snippet["trigger"], cl.calls), ("me@example.com", "إيميلي", []))


if __name__ == "__main__":
    unittest.main()
