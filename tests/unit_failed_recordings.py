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
            self.assertIsNotNone(self.keep())
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

    def test_failed_sidecar_removal_never_brings_the_entry_back(self):
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
        self.assertEqual(self.files(rid), set())

    def test_delete_whose_history_write_fails_keeps_the_files(self):
        rid = self.keep()
        with mock.patch.object(core, "_write_list", side_effect=OSError("locked")):
            core.history_delete([rid])
        self.assertEqual(self.files(rid), {"wav", "json", "mp3"})


class _Crash(BaseException):
    """قفل مفاجئ للبرنامج: مش Exception، فمفيش except في الكود بيمسكه — زي ما الحالة بتقف في النص."""


def _crash_when(name, predicate):
    """core.os.<name> بيقفل البرنامج لما predicate(path...) يتحقق، والباقي حقيقي."""
    real = getattr(core.os, name)

    def call(*args, **kw):
        if predicate(*args):
            raise _Crash(name)
        return real(*args, **kw)
    return mock.patch.object(core.os, name, side_effect=call)


class TestCrashSafety(_Store):
    """البرنامج بيتقفل في النص بين خطوتين: الاسترجاع عمره ما يضيّع تسجيل ولا يرجّع واحد اتمسح."""

    def test_crash_between_audio_and_sidecar_publish_keeps_the_recording(self):
        with _crash_when("replace", lambda src, dst: dst.endswith(".json")), \
                self.assertRaises(_Crash):
            self.keep()
        core.recordings_prune()
        [entry] = self.items()
        self.assertEqual((entry["status"], entry["error"]), ("failed", core.RECOVERED_ERROR))
        self.assertIn("wav", self.files(entry["id"]))

    def test_crash_after_delete_or_clear_does_not_bring_it_back(self):
        for action in (lambda rid: core.history_delete([rid]), lambda rid: core.history_clear()):
            with self.subTest(action=action):
                rid = self.keep()
                # أول لمسة لملفات التسجيل بعد كتابة السجل — النقطة اللي القفل فيها كان بيرجّعه
                in_recs = lambda path: (os.path.dirname(str(path)) == self.recs
                                        and str(path).endswith((".wav", ".json")))
                with _crash_when("remove", in_recs), self.assertRaises(_Crash):
                    action(rid)
                core.recordings_prune()
                self.assertNotIn(rid, [i["id"] for i in core.history_get()])
                self.assertEqual(self.files(rid), set())

    def test_failed_delete_write_keeps_the_entry_recoverable(self):
        rid = self.keep()
        with mock.patch.object(core, "_write_list", side_effect=OSError("locked")):
            core.history_delete([rid])
        with open(self.hist, "w", encoding="utf-8") as f:
            f.write("[]")                        # السجل باظ بعدها — ملف البيانات لازم يكون سليم
        core.recordings_prune()
        self.assertEqual([i["id"] for i in self.items()], [rid])


class TestOrphanAudio(_Store):
    """صوت تسجيل فاشل صفه مش في السجل: بيرجع ما لم يكون عليه علامة «اتمسح»."""

    def orphan(self, rid, sidecar):
        os.makedirs(self.recs, exist_ok=True)
        with open(os.path.join(self.recs, "%d.wav" % rid), "wb") as f:
            f.write(b"RIFF")
        if sidecar is not None:
            with open(os.path.join(self.recs, "%d.json" % rid), "w", encoding="utf-8") as f:
                f.write(sidecar)

    def test_tombstoned_wav_is_removed(self):
        self.orphan(12, json.dumps({"deleted": True}))
        core.recordings_prune()
        self.assertEqual(self.files(12), set())

    def test_sidecar_without_audio_is_removed(self):
        os.makedirs(self.recs, exist_ok=True)
        with open(os.path.join(self.recs, "14.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"deleted": True}))
        core.recordings_prune()
        self.assertEqual(self.files(14), set())

    def test_unreadable_sidecar_keeps_the_audio(self):
        self.orphan(13, "{not json")
        core.recordings_prune()
        self.assertIn("wav", self.files(13))


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

    def test_fail_again_updates_the_error_even_after_recovery(self):
        rid = self.keep()
        self.assertTrue(core.history_fail_again(rid, "المفتاح مش مقبول"))
        self.assertEqual(self.items()[0]["error"], "المفتاح مش مقبول")
        with open(self.hist, "w", encoding="utf-8") as f:
            f.write("[]")
        core.recordings_prune()
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


class _ProcClient:
    """عميل ميزة مزيّف للتسجيل الحي: التفريغ ممكن يرمي أو يرجّع نص/فاضي."""

    def __init__(self, text="الكلام ده جملة طويلة شوية", stt_error=None, edit_result="معدّل"):
        self.text, self.stt_error, self.edit_result = text, stt_error, edit_result
        self.vocab, self.vocab_extra, self.ai_ok = [], [], True

    def transcribe(self, wav, lang):
        if self.stt_error:
            raise self.stt_error
        return self.text

    def polish(self, t, profile=None):
        return t

    def to_prompt(self, t):
        return t

    def translate(self, t):
        return t

    def edit(self, selection, instruction):
        return self.edit_result

    def engine(self):
        return {"stt": "fake"}


GUI = {"is_password": False, "class": "Edit", "editable": True}
PASSWORD = {"is_password": True, "class": "Edit", "editable": True}


def _first_history_write_fails():
    """أول كتابة لملف السجل بتفشل (قفل/قرص) والباقي حقيقي — فشل history_add من غير ما نزيّفه."""
    real, calls = core._write_list, []

    def write(path, items):
        calls.append(path)
        if len(calls) == 1:
            raise OSError("history.json locked")
        return real(path, items)
    return mock.patch.object(core, "_write_list", side_effect=write)


class _ProcBase(_Store):
    """تشغيل process حقيقي بعميل مزيّف — الفوكس واللصق مزيّفين."""

    def run_process(self, client, mode="normal", focus=(GUI,), paste="placed", on_text=None,
                    on_failed=None, selection=None, on_state=None):
        # الهوك اللي بيرمي بيطلع برّه process زي ما بيحصل في ثريد التسجيل — مهمّنا اللي اتساب وراه
        app = core.App.__new__(core.App)
        app.recording, app.busy, app._op, app._active_key = False, True, None, None
        app.events, app.failed = [], []

        def record_state(st, msg=None):
            app.events.append((st, msg))
            if on_state:
                on_state(st, msg)

        app.on_state = record_state
        app.on_text = on_text or (lambda t: None)
        app.on_unplaced = lambda t: None
        app.on_failed = on_failed or (lambda rid, msg: app.failed.append((rid, msg)))
        app.client = lambda m="normal": client
        wav = self.make_wav("live.wav")
        focus_seq = [dict(f) if isinstance(f, dict) else f for f in focus]

        def focused_info():
            item = focus_seq.pop(0) if len(focus_seq) > 1 else focus_seq[0]
            if isinstance(item, Exception):
                raise item
            return dict(item)

        import winput
        with mock.patch.object(winput, "focused_info", side_effect=focused_info), \
                mock.patch.object(winput, "same_target", return_value=True), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "paste_text",
                                  side_effect=paste if callable(paste) else (lambda *a, **k: paste)):
            op = core.Operation(mode=mode, selection=selection)
            app.process(wav, op)
        return app, wav

    def failed_entries(self):
        return [i for i in self.items() if i.get("status") == "failed"] if os.path.exists(self.hist) else []


class TestProcessKeepsFailures(_ProcBase):
    def test_transcription_error_keeps_the_recording_and_notifies(self):
        app, wav = self.run_process(_ProcClient(stt_error=RuntimeError("no internet: timed out")))
        [entry] = self.failed_entries()
        self.assertEqual(self.files(entry["id"]), {"wav", "json", "mp3"})
        self.assertEqual(app.failed, [(entry["id"], entry["error"])])
        self.assertEqual(app.events[-1], ("err", entry["error"]))
        self.assertFalse(os.path.exists(wav))
        self.assertFalse(app.busy)

    def test_empty_transcript_is_kept_as_failed(self):
        app, _ = self.run_process(_ProcClient(text=""))
        [entry] = self.failed_entries()
        self.assertEqual(entry["error"], "مطلعش نص — قرّب من الميك وجرّب تاني")
        self.assertEqual(app.events[-1], ("err", "مطلعش نص — قرّب من الميك وجرّب تاني"))

    def test_error_after_the_entry_was_written_saves_its_audio_without_a_duplicate(self):
        def boom(text):
            raise RuntimeError("ui gone")

        self.run_process(_ProcClient(), on_text=boom)
        items = self.items()
        self.assertEqual(len(items), 1)
        self.assertNotIn("status", items[0])
        self.assertTrue(os.path.exists(core.recording_path(items[0]["id"])))

    def test_password_field_transcription_failure_is_kept(self):
        self.run_process(_ProcClient(stt_error=RuntimeError("HTTP 500")), focus=(PASSWORD,))
        self.assertEqual(len(self.failed_entries()), 1)

    def test_password_transcript_is_not_kept_when_a_later_step_fails(self):
        def paste(*a, **k):
            raise RuntimeError("paste broke")

        self.run_process(_ProcClient(), focus=(PASSWORD,), paste=paste)
        self.assertFalse(os.path.exists(self.hist) and self.items())
        self.assertFalse(os.path.exists(self.recs) and os.listdir(self.recs))

    def test_error_after_transcription_outside_password_fields_keeps_the_words(self):
        self.run_process(_ProcClient(text="كلام مهم"), focus=(GUI, RuntimeError("uia")))
        [entry] = self.failed_entries()
        self.assertEqual(entry["raw"], "كلام مهم")

    def test_temp_audio_survives_when_it_could_not_be_kept(self):
        with mock.patch.object(core.shutil, "copyfile", side_effect=OSError("disk full")):
            _, wav = self.run_process(_ProcClient(stt_error=RuntimeError("HTTP 500")))
        self.assertTrue(os.path.exists(wav))

    def test_failing_notification_hook_loses_nothing(self):
        def hook(rid, msg):
            raise RuntimeError("toast broke")

        app, _ = self.run_process(_ProcClient(stt_error=RuntimeError("HTTP 500")), on_failed=hook)
        self.assertEqual(len(self.failed_entries()), 1)
        self.assertFalse(app.busy)

    def test_raising_error_hook_after_empty_transcript_keeps_one_entry(self):
        def on_state(st, msg=None):
            if st == "err":
                raise RuntimeError("ui gone")

        app, wav = self.run_process(_ProcClient(text=""), on_state=on_state)
        self.assertEqual(len(self.failed_entries()), 1)
        self.assertFalse(os.path.exists(wav))
        self.assertFalse(app.busy)

    def test_history_write_failure_then_typing_error_keeps_one_entry(self):
        def boom(text):
            raise RuntimeError("ui gone")

        with _first_history_write_fails():
            self.run_process(_ProcClient(text="كلام اتكتب"), on_text=boom)
        self.assertEqual([e["raw"] for e in self.failed_entries()], ["كلام اتكتب"])

    def test_history_write_failure_keeps_the_recording(self):
        with _first_history_write_fails():
            self.run_process(_ProcClient(text="كلام اتكتب"))
        [entry] = self.failed_entries() or [None]
        self.assertIsNotNone(entry)
        self.assertEqual(entry["raw"], "كلام اتكتب")


class TestEditKeepsFailures(_ProcBase):
    def run_edit(self, client, **kw):
        with mock.patch.object(core, "_probe_password_seen", return_value=False):
            return self.run_process(client, mode="edit", selection="النص المحدد", **kw)

    def test_instruction_transcription_error_is_kept(self):
        self.run_edit(_ProcClient(stt_error=RuntimeError("HTTP 500")))
        [entry] = self.failed_entries()
        self.assertEqual(entry["mode"], "edit")

    def test_failing_work_state_in_edit_still_keeps_the_audio(self):
        def on_state(st, msg=None):
            if st == "work":
                raise RuntimeError("ui gone")

        self.run_edit(_ProcClient(text="خليه رسمي"), on_state=on_state)
        [entry] = self.failed_entries()
        self.assertEqual(entry["mode"], "edit")

    def test_raising_error_hook_after_an_edit_failure_keeps_one_entry(self):
        def on_state(st, msg=None):
            if st == "err":
                raise RuntimeError("ui gone")

        app, wav = self.run_edit(_ProcClient(text=""), on_state=on_state)
        self.assertEqual(len(self.failed_entries()), 1)
        self.assertFalse(os.path.exists(wav))

    def test_edit_model_failure_keeps_the_instruction(self):
        self.run_edit(_ProcClient(text="خليه رسمي", edit_result=None))
        [entry] = self.failed_entries()
        self.assertEqual(entry["raw"], "خليه رسمي")

    def test_clipboard_failure_keeps_entry_and_audio(self):
        app, _ = self.run_edit(_ProcClient(text="خليه رسمي"), paste="clip_failed")
        [entry] = self.items()
        self.assertNotIn("status", entry)
        self.assertTrue(os.path.exists(core.recording_path(entry["id"])))
        self.assertNotIn("النص المحدد", json.dumps(entry, ensure_ascii=False))

    def test_done_hook_failure_after_save_creates_no_duplicate(self):
        def on_state(st, msg=None):
            if st == "done":
                raise RuntimeError("ui gone")

        self.run_edit(_ProcClient(text="خليه رسمي"), on_state=on_state)
        self.assertEqual(len(self.items()), 1)
        self.assertEqual(self.failed_entries(), [])

    def test_history_write_failure_keeps_the_instruction_and_still_delivers(self):
        pasted = []
        with _first_history_write_fails():
            self.run_edit(_ProcClient(text="خليه رسمي"),
                          paste=lambda text, *a, **k: pasted.append(text) or "placed")
        [entry] = self.failed_entries()
        self.assertEqual(entry["raw"], "خليه رسمي")
        self.assertEqual(pasted, ["معدّل"])


LONG = "الكلام ده جملة طويلة شوية عشان تتنضف, صح?"


class _RetryClient(_ProcClient):
    """عميل التفريغ اليدوي: during(wav) بيتنده وهو بيقرا الصوت — عشان نمسح/نعيد في النص."""

    def __init__(self, text=LONG, stt_error=None, ai_ok=True, during=None):
        super().__init__(text=text, stt_error=stt_error)
        self.ai_ok, self.during, self.read = ai_ok, during, []

    def transcribe(self, wav, lang):
        self.read.append((os.path.exists(wav), lang))
        if self.during:
            self.during(wav)
        return super().transcribe(wav, lang)

    def edit(self, selection, instruction):
        raise AssertionError("التعديل مايتعادش — التحديد عمره ما اتحفظ")


class TestRetranscribe(_Store):
    def retry(self, rid, client):
        return core.retranscribe(rid, client_factory=lambda mode: client)

    def entry(self, rid):
        return next(i for i in self.items() if i["id"] == rid)

    def test_success_resolves_the_entry_and_never_types(self):
        rid = self.keep()
        with mock.patch.object(core, "paste_text") as paste:
            res = self.retry(rid, _RetryClient())
        self.assertEqual(res, {"ok": True, "result": "الكلام ده جملة طويلة شوية عشان تتنضف، صح؟"})
        entry = self.entry(rid)
        self.assertNotIn("status", entry)
        self.assertEqual((entry["raw"], entry["result"]), (LONG, res["result"]))
        self.assertEqual(self.files(rid), {"mp3"})
        paste.assert_not_called()

    def test_raw_mode_skips_the_mixed_text_fix(self):
        rid = self.keep()
        with mock.patch.dict(core.CFG, polish=False):
            res = self.retry(rid, _RetryClient())
        self.assertEqual(res["result"], LONG)

    def test_empty_transcript_stays_failed(self):
        rid = self.keep()
        res = self.retry(rid, _RetryClient(text=""))
        self.assertFalse(res["ok"])
        self.assertEqual((self.entry(rid)["status"], self.entry(rid)["error"]), ("failed", res["err"]))
        self.assertEqual(self.files(rid), {"wav", "json", "mp3"})

    def test_transcription_error_stays_failed_with_the_new_reason(self):
        rid = self.keep(error="قديم")
        res = self.retry(rid, _RetryClient(stt_error=RuntimeError("HTTP 500")))
        self.assertFalse(res["ok"])
        self.assertNotEqual(res["err"], "قديم")
        self.assertEqual(self.entry(rid)["error"], res["err"])

    def test_missing_or_successful_entries_are_refused(self):
        ok_id = core.history_add("normal", "كلام", "كلام")
        for rid in (ok_id, 42):
            with self.subTest(rid=rid):
                client = _RetryClient()
                self.assertFalse(self.retry(rid, client)["ok"])
                self.assertEqual(client.read, [])

    def test_second_retry_of_the_same_recording_is_refused(self):
        rid = self.keep()
        nested = []
        self.retry(rid, _RetryClient(during=lambda wav: nested.append(self.retry(rid, _RetryClient()))))
        self.assertFalse(nested[0]["ok"])
        self.assertNotIn("status", self.entry(rid))

    def test_delete_while_transcribing_wins(self):
        rid = self.keep()
        client = _RetryClient(during=lambda wav: core.history_delete([rid]))
        res = self.retry(rid, client)
        self.assertEqual(res, {"ok": False, "err": "التسجيل اتمسح"})
        self.assertEqual(client.read, [(True, None)])
        self.assertEqual(self.items(), [])
        self.assertEqual(self.files(rid), set())

    def test_clear_while_transcribing_wins(self):
        rid = self.keep()
        res = self.retry(rid, _RetryClient(during=lambda wav: core.history_clear()))
        self.assertEqual(res, {"ok": False, "err": "التسجيل اتمسح"})
        self.assertEqual(core.history_get(), [])
        self.assertEqual(self.files(rid), set())

    def test_save_failure_still_returns_the_text_and_keeps_it_failed(self):
        rid = self.keep()
        with _first_history_write_fails():
            res = self.retry(rid, _RetryClient())
        self.assertTrue(res["ok"])
        self.assertEqual(res["note"], core.RETRY_NOT_SAVED)
        self.assertEqual(self.entry(rid)["status"], "failed")
        self.assertIn("wav", self.files(rid))

    def test_failed_processing_keeps_the_transcript_with_a_note(self):
        rid = self.keep(mode="prompt")
        res = self.retry(rid, _RetryClient(text="اكتب برومبت", ai_ok=False))
        self.assertEqual(res, {"ok": True, "result": "اكتب برومبت",
                               "note": "مقدرتش أحوّله — ده الكلام زي ما اتقال"})
        self.assertNotIn("status", self.entry(rid))

    def test_edit_retry_returns_the_instruction(self):
        rid = self.keep(mode="edit")
        res = self.retry(rid, _RetryClient(text="خليه رسمي"))
        self.assertEqual(res, {"ok": True, "result": "خليه رسمي"})
        self.assertEqual(self.entry(rid)["result"], "خليه رسمي")

    def test_snippet_is_expanded_and_labelled_in_history(self):
        rid = self.keep()
        with mock.patch.dict(core.CFG, snippets=[{"trigger": "إيميلي", "text": "me@example.com"}]):
            res = self.retry(rid, _RetryClient(text="إيميلي"))
        self.assertEqual(res["result"], "me@example.com")
        self.assertEqual(self.entry(rid)["result"], "[اختصار] إيميلي")

    def test_an_exception_does_not_leave_the_recording_locked(self):
        rid = self.keep()
        with mock.patch.object(core, "convert_text", side_effect=RuntimeError("boom")):
            self.assertFalse(self.retry(rid, _RetryClient())["ok"])
        self.assertTrue(self.retry(rid, _RetryClient())["ok"])

    def test_default_client_is_a_fresh_feature_client(self):
        rid = self.keep(mode="translate")
        client = _RetryClient(text="اترجم ده")
        with mock.patch.object(core.chains, "FeatureClient", return_value=client) as make,                 mock.patch.object(core.providers, "read_key_pools", return_value={"groq": ["k"]}),                 mock.patch.dict(core.CFG, dictionary=["إملاء"]):
            self.assertTrue(core.retranscribe(rid)["ok"])
        make.assert_called_once_with(core.feature("translate"), {"groq": ["k"]})
        self.assertEqual(client.vocab, ["إملاء"])


class TestBridge(_Store):
    """الواجهة: السجل كامل، والتفريغ اليدوي، ورسالة الفشل بزرار «افتح السجل»."""

    def setUp(self):
        super().setUp()
        import app_web
        self.app_web = app_web

    def test_history_lists_failed_entries_beyond_the_cap(self):
        ok = [dict(id=k + 1, mode="normal", raw="ك", result="ك", words=1) for k in range(1000)]
        failed = [dict(id=5000 + k, mode="normal", raw="", result="", words=0,
                       status="failed", error="x") for k in range(2)]
        with open(self.hist, "w", encoding="utf-8") as f:
            json.dump(failed + ok, f)
        self.assertEqual(len(self.app_web.Api(None).history()["items"]), 1002)

    def test_history_lists_a_recording_published_before_a_crash(self):
        rid = self.keep()
        with open(self.hist, "w", encoding="utf-8") as f:
            f.write("[]")                        # القفل حصل قبل ما صفه يتكتب
        items = self.app_web.Api(None).history()["items"]
        self.assertEqual([i["id"] for i in items], [rid])

    def test_retry_resolves_through_the_bridge(self):
        rid = self.keep()
        with mock.patch.object(core.chains, "FeatureClient", return_value=_RetryClient()),                 mock.patch.object(core.providers, "read_key_pools", return_value={}):
            res = self.app_web.Api(None).history_retry(rid)
        self.assertTrue(res["ok"])
        self.assertNotIn("status", self.items()[0])

    def test_engine_failure_shows_a_toast_that_opens_history(self):
        ctrl = self.app_web.Controller.__new__(self.app_web.Controller)
        ctrl.root, ctrl.tk_call = "root", lambda fn: fn()
        ctrl.emlaa = mock.MagicMock()
        ctrl.show_window = mock.MagicMock()
        app = core.App.__new__(core.App)
        ctrl._wire(app)
        app.on_failed(7, "مفيش اتصال بالنت")
        master, message, on_open = ctrl.emlaa.FailedToast.show_for.call_args.args
        self.assertEqual((master, message), ("root", "مفيش اتصال بالنت"))
        on_open()
        ctrl.show_window.assert_called_once_with("history")


if __name__ == "__main__":
    unittest.main()
