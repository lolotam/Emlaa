# -*- coding: utf-8 -*-
"""
التفريغ من غير إنترنت كعنصر في قايمة التفريغ («محلي») — من خلال App.process و
chains.FeatureClient الحقيقيين. مفيش شبكة ولا مفاتيح ولا BASE الحقيقي: offline.installed/
transcribe والمزوّد الصارم (chains._strict_client) مزيّفين، والحافظة والحقن stubs.
"""
import os
import sys
import threading
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import offline    # noqa: E402
import providers  # noqa: E402
import chains     # noqa: E402
import app_web    # noqa: E402


def make_app():
    """App من غير __init__ عشان مافتحناش ميكروفون حقيقي."""
    app = core.App.__new__(core.App)
    app.rec = None
    app.recording = False
    app.busy = False
    app._op = None
    app._active_key = None
    app._client = None
    app._client_sig = None
    app._listener = None
    app.events = []
    app.on_state = lambda st, msg=None: app.events.append((st, msg))
    app.texts = []
    app.on_text = app.texts.append
    app.unplaced = []
    app.on_unplaced = app.unplaced.append
    return app


def cfg(**over):
    c = dict(core.DEFAULTS)
    c.update(over)
    return c


FEATURES = ("normal", "prompt", "translate", "edit")
LOCAL = {"provider": "local", "model": ""}
GROQ_STT = {"provider": "groq", "model": "w"}
GROQ_AI = {"provider": "groq", "model": "q"}


class FakeProvider:
    """عميل مزوّد صارم وهمي: transcribe ممكن يرمي (stt_err)، و_chat_raw بيرجّع ai_out أو بيرمي."""

    def __init__(self, stt_err=None, ai_out=None, ai_err=None):
        self.vocab, self.vocab_extra, self.last_stt_model = [], [], None
        self.stt_err, self.ai_out, self.ai_err = stt_err, ai_out, ai_err

    def transcribe(self, wav, lang):
        if self.stt_err:
            raise self.stt_err
        self.last_stt_model = "w"
        return "من المزوّد"

    def _chat_raw(self, system, text, temperature=0.2):
        if self.ai_err:
            raise self.ai_err
        return self.ai_out


# معلومات فوكس ثابتة: هدف عادي (مش باسورد) — عشان منعتمدش على النافذة الحقيقية
GUI_FOCUS = {"is_password": False, "class": "Edit", "editable": True}


def _wire(tc, stt, ai=(), installed="base", offline_text="النص المحلي", provider=None):
    """
    App حقيقي بـFeatureClient حقيقي على قايمة التفريغ/المعالجة اللي في الاختبار — الموديل
    المحلي والمزوّد (عن طريق chains._strict_client) والحقن والسجل بس هما المزيّفين.
    بيسجّل p.stop كـcleanup — مش نتيجة start() — عشان الترقيعة تتفك فعلًا بعد الاختبار.
    """
    m = {
        "paste": mock.Mock(return_value="placed"),
        "history": mock.Mock(return_value=111),
        "clip": mock.Mock(return_value=True),
        "transcribe": mock.Mock(return_value=offline_text),
        "installed": mock.Mock(return_value=installed),
        "factory": mock.Mock(return_value=provider or FakeProvider()),
    }
    features = {f: {"hotkey": [], "stt": [dict(i) for i in stt], "ai": [dict(i) for i in ai]}
                for f in FEATURES}

    def start(patcher):
        patcher.start()
        tc.addCleanup(patcher.stop)

    start(mock.patch.object(core, "CFG", cfg(features=features)))
    start(mock.patch.object(providers, "read_key_pools", return_value={"groq": ["k"]}))
    start(mock.patch.object(chains, "_strict_client", m["factory"]))
    start(mock.patch("winput.focused_info", return_value=dict(GUI_FOCUS)))
    start(mock.patch.object(core, "_foreground_app", return_value=""))
    start(mock.patch.object(core, "log_error"))
    start(mock.patch.object(core, "paste_text", m["paste"]))
    start(mock.patch.object(core, "history_add", m["history"]))
    start(mock.patch.object(core, "recording_save"))
    start(mock.patch.object(core, "_copy_to_clipboard", m["clip"]))
    start(mock.patch.object(offline, "installed", m["installed"]))
    start(mock.patch.object(offline, "transcribe", m["transcribe"]))
    return m


class TestLocalFirst(unittest.TestCase):
    """«محلي» أول قايمة التفريغ: الصوت عمره ما بيروح لمزوّد، وقايمة المعالجة بتشتغل عادي."""

    def test_normal_local_only_never_builds_provider_client(self):
        app = make_app()
        m = _wire(self, [LOCAL], offline_text="كلام محلي")
        app.process("WAV", core.Operation(mode="normal"))
        m["factory"].assert_not_called()
        m["transcribe"].assert_called_once_with("WAV", None)
        m["paste"].assert_called_once_with("كلام محلي", ("gui", "type", "كلام محلي"))
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_snippet_expands_with_local_stt(self):
        app = make_app()
        m = _wire(self, [LOCAL], offline_text="العنوان بتاعي")
        core.CFG["snippets"] = [{"trigger": "العنوان بتاعي", "text": "١٢ شارع النيل"}]
        app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(m["paste"].call_args.args[0], "١٢ شارع النيل")
        self.assertEqual(m["history"].call_args.args[2], "[اختصار] العنوان بتاعي")

    def test_snippet_not_expanded_into_password_field(self):
        app = make_app()
        m = _wire(self, [LOCAL], offline_text="العنوان بتاعي")
        core.CFG["snippets"] = [{"trigger": "العنوان بتاعي", "text": "١٢ شارع النيل"}]
        with mock.patch("winput.focused_info", return_value=dict(GUI_FOCUS, is_password=True)):
            app.process("WAV", core.Operation(mode="normal"))
        for call in m["paste"].call_args_list:
            self.assertNotIn("١٢ شارع النيل", call.args[0])

    def test_translate_after_local_runs_the_ai_list(self):
        app = make_app()
        m = _wire(self, [LOCAL], ai=[GROQ_AI], offline_text="نص عربي",
                  provider=FakeProvider(ai_out="English text"))
        app.process("WAV", core.Operation(mode="translate"))
        # المزوّد اتبنى للمعالجة بس (chat_model) — مش للتفريغ
        self.assertEqual(m["factory"].call_args_list, [mock.call("groq", ["k"], None, "q")])
        self.assertEqual(m["paste"].call_args.args[0], "English text")
        self.assertEqual(app.events[-1], ("done", "translate"))

    def test_prompt_after_local_with_ai_down_types_raw_and_says_so(self):
        app = make_app()
        m = _wire(self, [LOCAL], ai=[GROQ_AI], offline_text="طلب محلي",
                  provider=FakeProvider(ai_err=providers.NetworkError("dns")))
        app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(m["paste"].call_args.args[0], "طلب محلي")
        self.assertEqual(m["history"].call_args.args[2], "طلب محلي")
        self.assertEqual(app.events[-1], ("done", "مقدرتش أحوّله — اتكتب الكلام زي ما اتقال"))

    def test_history_engine_is_offline(self):
        app = make_app()
        m = _wire(self, [LOCAL], installed="small-q5_1", offline_text="نص")
        app.process("WAV", core.Operation(mode="normal"))
        engine = m["history"].call_args.kwargs["engine"]
        self.assertEqual(engine, {"stt": "offline", "stt_model": "whisper.cpp small-q5_1"})

    def test_edit_with_local_stt_and_no_ai_answer_leaves_selection(self):
        app = make_app()
        m = _wire(self, [LOCAL], ai=[GROQ_AI], provider=FakeProvider(ai_out=None))
        app.process("WAV", core.Operation(mode="edit", selection="نص محدد"))
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.events[-1], ("err", "معرفتش أعدّل النص — جرّب تاني"))

    def test_local_only_not_installed_refuses_without_provider(self):
        app = make_app()
        m = _wire(self, [LOCAL], installed=None)
        app.process("WAV", core.Operation(mode="normal"))
        m["factory"].assert_not_called()
        m["transcribe"].assert_not_called()
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.events[-1], ("err", "التفريغ من غير إنترنت مش متثبّت — نزّله من الإعدادات"))


class TestFallbackToLocal(unittest.TestCase):
    """مزوّد ← محلي: أي فشل للمزوّد (نت، 401، كوتا) بينقل للعنصر اللي بعده."""

    def test_normal_falls_back_to_local_after_network_error(self):
        app = make_app()
        m = _wire(self, [GROQ_STT, LOCAL], offline_text="اتفرّغ محليًا",
                  provider=FakeProvider(stt_err=providers.NetworkError("انقطاع")))
        app.process("WAV", core.Operation(mode="normal"))
        m["transcribe"].assert_called_once_with("WAV", None)
        m["paste"].assert_called_once_with("اتفرّغ محليًا", ("gui", "type", "اتفرّغ محليًا"))
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_http_401_also_falls_back_to_local(self):
        app = make_app()
        m = _wire(self, [GROQ_STT, LOCAL], offline_text="محلي",
                  provider=FakeProvider(stt_err=RuntimeError("401 invalid api key")))
        app.process("WAV", core.Operation(mode="normal"))
        m["transcribe"].assert_called_once_with("WAV", None)
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_network_error_with_no_other_item_is_reported(self):
        app = make_app()
        m = _wire(self, [GROQ_STT], provider=FakeProvider(stt_err=providers.NetworkError("انقطاع")))
        app.process("WAV", core.Operation(mode="edit", selection="نص"))
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.events[-1][0], "err")
        self.assertIn("مفيش اتصال بالنت", app.events[-1][1])


class TestFriendlyErrorOffline(unittest.TestCase):
    def test_network_error_without_pack_appends_hint(self):
        with mock.patch.object(offline, "installed", return_value=None):
            msg = core.friendly_error(providers.NetworkError("dns فشل"))
        self.assertIn("مفيش اتصال بالنت", msg)
        self.assertIn("تقدر تنزّل التفريغ من غير إنترنت من الإعدادات", msg)

    def test_network_error_with_pack_keeps_plain_message(self):
        with mock.patch.object(offline, "installed", return_value="base"):
            msg = core.friendly_error(providers.NetworkError("dns فشل"))
        self.assertIn("مفيش اتصال بالنت", msg)
        self.assertNotIn("تقدر تنزّل", msg)

    def test_offline_corrupt_message_passes_through(self):
        # T20: رسالة الموديل البايظ لازم توصل للمستخدم زي ما هي — مش «مشكلة مش متوقّعة»
        msg = "الموديل المحلي بايظ — شيله ونزّله تاني من الإعدادات"
        self.assertEqual(core.friendly_error(RuntimeError(msg)), msg)


class _Ctrl:
    """وحدة تحكم مزيّفة لـApi — الحقول اللي bootstrap/save_settings محتاجاها."""

    version = "0"
    brand = {"name": "x", "url": "y"}
    state = "ready"
    last_text = ""
    update_info = None
    hotkeys = []
    engine = None

    def apply_lang(self): pass
    def start_engine(self): pass
    def start_open_hotkey(self): pass
    def tk_call(self, fn): pass
    def push(self, fn, payload): pass


class TestApiOffline(unittest.TestCase):
    def test_welcome_without_key_ok_when_local_model_transcribes(self):
        api = app_web.Api(_Ctrl())
        cfg = dict(core.DEFAULTS, features={m: {"hotkey": [], "stt": [{"provider": "local", "model": ""}],
                                                "ai": []} for m in ("normal", "prompt", "translate", "edit")},
                   features_custom=True)
        with mock.patch.object(providers, "read_key_pools", return_value={}), \
                mock.patch.object(offline, "installed", return_value="base"), \
                mock.patch.object(core, "save_config"), \
                mock.patch.object(core, "history_prune"), \
                mock.patch.object(core, "history_stats",
                                  return_value={"words": 0, "count": 0, "wpm": None, "saved_min": 0.0}), \
                mock.patch.object(core, "_is_packaged", return_value=False), \
                mock.patch.object(core, "CFG", cfg):
            r = api.save_settings({"provider": "groq"})
        self.assertTrue(r["ok"])

    def test_save_settings_no_key_no_offline_requires_key(self):
        api = app_web.Api(_Ctrl())
        with mock.patch.object(providers, "read_key_pools", return_value={}), \
                mock.patch.object(offline, "installed", return_value=None), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)):
            r = api.save_settings({"provider": "groq"})
        self.assertFalse(r["ok"])
        self.assertIn("محتاج مفتاح", r["err"])

    def test_offline_download_refuses_concurrent(self):
        api = app_web.Api(_Ctrl())
        started = threading.Event()
        release = threading.Event()

        def fake_download(model, progress=None):
            started.set()
            release.wait(5)

        with mock.patch.object(offline, "download", fake_download), \
                mock.patch.object(core, "log_error"):
            r1 = api.offline_download("base")
            self.assertTrue(r1["ok"])
            r2 = api.offline_download("base")
            self.assertFalse(r2["ok"])
            self.assertIn("شغّال", r2["err"])
            release.set()
            self.assertTrue(started.wait(5))

    def test_offline_status_exposes_verified(self):
        # T20: verified بييجي من cached_verification (من غير هاش جوه offline_status)
        api = app_web.Api(_Ctrl())
        with mock.patch.object(offline, "installed", return_value="base"), \
                mock.patch.object(offline, "residual", return_value=False), \
                mock.patch.object(offline, "cached_verification", return_value=True), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)):
            r = api.offline_status()
        self.assertIs(r["verified"], True)


class TestLocalPasswordFields(unittest.TestCase):
    def test_prompt_in_password_field_skips_ai_history_and_clipboard(self):
        # برومبت والتسجيل كان في خانة باسورد: النص بيتكتب زي ما اتفرّغ — مفيش موديل ولا سجل ولا حافظة
        app = make_app()
        m = _wire(self, [LOCAL], ai=[GROQ_AI], offline_text="كلمة السر")
        with mock.patch("winput.focused_info",
                        return_value={"is_password": True, "class": "", "editable": True}):
            app.process("WAV", core.Operation(mode="prompt"))
        m["factory"].assert_not_called()
        m["clip"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.unplaced, [])
        self.assertEqual(m["paste"].call_args.args[0], "كلمة السر")


class TestClassicKeylessSave(unittest.TestCase):
    """الواجهة الكلاسيك: الإعدادات بتتحفظ من غير مفتاح لو لسه فيه حاجة تفرّغ (الموديل المحلي)."""

    def _ui(self, stt, installed):
        import emlaa
        ui = emlaa.EmlaaClassic.__new__(emlaa.EmlaaClassic)
        feats = {m: {"hotkey": [], "stt": [dict(stt)], "ai": [] if m == "normal" else
                     [{"provider": "groq", "model": "m"}]} for m in ("normal", "prompt", "translate", "edit")}
        ui.cfg = cfg(provider="groq", features=feats, features_custom=True)
        ui._key_drafts = {}
        ui.skey_var = mock.Mock(get=mock.Mock(return_value=""))
        ui._settings_pid = mock.Mock(return_value="groq")
        ui._hk_opts = emlaa.classic_hotkey_options(feats)
        ui._hk_vars = {m: mock.Mock(get=mock.Mock(return_value="مفيش")) for m in emlaa.CLASSIC_MODES}
        ui._apply = mock.Mock()
        ui._set_smsg = mock.Mock()
        for p in (mock.patch.object(offline, "installed", return_value=installed),
                  mock.patch.object(providers, "read_key_pools", return_value={}),
                  mock.patch.object(providers, "read_keys", return_value={})):
            p.start()
            self.addCleanup(p.stop)
        return ui

    def test_saves_without_key_when_local_model_transcribes(self):
        ui = self._ui({"provider": "local", "model": ""}, "base")
        ui._save()
        ui._apply.assert_called_once_with("groq", "", False, mock.ANY)

    def test_still_requires_key_when_nothing_can_transcribe(self):
        for stt, inst in (({"provider": "groq", "model": "m"}, "base"), ({"provider": "local", "model": ""}, None)):
            ui = self._ui(stt, inst)
            ui._save()
            ui._apply.assert_not_called()

    def test_apply_never_writes_an_empty_key(self):
        import emlaa
        ui = emlaa.EmlaaClassic.__new__(emlaa.EmlaaClassic)
        with mock.patch.object(providers, "write_key") as wk, \
                mock.patch.object(core, "save_config", side_effect=RuntimeError("stop")):
            ui.cfg = cfg()
            for name in ("polish_var", "prompt_var", "paste_var", "tray_var", "upd_var", "float_var"):
                setattr(ui, name, mock.Mock(get=mock.Mock(return_value=False)))
            with self.assertRaises(RuntimeError):
                ui._apply("groq", "", False, (core.DEFAULTS["features"], False))
        wk.assert_not_called()


class TestOfflineSilenceMarkers(unittest.TestCase):
    """F1: المحلي بيرجّع "" لما whisper يسمع سكوت/علامات بس — process يعرض «مطلعش نص»
    من غير سجل ولا حافظة ولا كتابة."""

    def test_marker_only_shows_no_text_in_every_mode(self):
        for mode in ("normal", "translate"):
            app = make_app()
            m = _wire(self, [LOCAL], ai=[GROQ_AI], offline_text="")
            app.process("WAV", core.Operation(mode=mode))
            m["paste"].assert_not_called()
            m["history"].assert_not_called()
            m["clip"].assert_not_called()
            self.assertEqual(app.unplaced, [])
            self.assertEqual(app.events[-1], ("ready", "مطلعش نص — قرّب من الميك وجرّب تاني"))


if __name__ == "__main__":
    unittest.main()
