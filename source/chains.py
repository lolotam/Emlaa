# -*- coding: utf-8 -*-
"""
قوايم الميزات: كل ميزة (عادي/برومبت/ترجمة/تعديل) ليها قايمة تفريغ وقايمة معالجة، والعنصر
الأول بيشتغل ولو فشل بأي سبب (كوتا، زحمة، نت، موديل مش متاح، مفيش مفتاح) بننقل للي بعده.
قايمة المستخدم هي ترتيب البدائل الوحيد: كل عنصر بيتنادى بـClient صارم (موديل واحد بالظبط)،
فمفيش بدائل مخبّية جوّه المزوّد تلخبط الترتيب اللي المستخدم شايفه.
"""
import offline
import providers
import smart

LOCAL_MISSING = "التفريغ من غير إنترنت مش متثبّت — نزّله من الإعدادات"


class FeatureClient(providers.TextOps):
    """
    نفس واجهة Client اللي App.process بيستخدمها (transcribe / polish / to_prompt /
    translate / edit / engine / vocab)، بس على قوايم ميزة.
    كل عملية بتبدأ بـtranscribe — هي اللي بتصفّر حالة العملية: مين فرّغ، مين عالج،
    و ai_ok («فيه عنصر معالجة رد فعلًا في العملية دي»).
    """

    def __init__(self, feature, pools, client_factory=None, log=None):
        self._stt = [dict(i) for i in feature.get("stt") or []]
        self._ai = [dict(i) for i in feature.get("ai") or []]
        self._pools = {pid: list(keys or []) for pid, keys in (pools or {}).items()}
        self._factory = client_factory or _strict_client
        self._log = log or _log_error
        self._clients = {}
        self.vocab = []
        self.vocab_extra = []
        self._reset_operation()

    def _reset_operation(self):
        self.last_stt_model = None
        self.last_stt_name = None
        self.stt_local = False
        self.last_chat = None
        self.ai_ok = False

    def _client(self, pid, model=None, chat_model=None):
        keys = self._pools.get(pid) or []
        if not keys:
            raise RuntimeError("مفيش مفتاح لـ " + providers.meta(pid)["name"])
        sig = (pid, model, chat_model, tuple(keys))
        if sig not in self._clients:
            self._clients[sig] = self._factory(pid, keys, model, chat_model)
        return self._clients[sig]

    # ── التفريغ ──
    def transcribe(self, wav_path, language="ar"):
        self._reset_operation()
        errors = []
        for item in self._stt:
            pid, model = item.get("provider"), item.get("model") or None
            try:
                if pid == smart.LOCAL:
                    pack = offline.installed()
                    if not pack:
                        raise RuntimeError(LOCAL_MISSING)
                    text = offline.transcribe(wav_path, language)
                    self.stt_local, self.last_stt_name = True, "offline"
                    self.last_stt_model = "whisper.cpp " + pack
                    return text
                cl = self._client(pid, model=model)
                # القاموس ومفاتيح الاختصارات بيتغيّروا بين التسجيلات — والعميل مخزّن
                cl.vocab, cl.vocab_extra = list(self.vocab), list(self.vocab_extra)
                text = cl.transcribe(wav_path, language)
                self.last_stt_name = providers.meta(pid)["name"]
                self.last_stt_model = cl.last_stt_model or model
                return text
            except Exception as e:
                errors.append(e)
                self._log(e, "stt/%s %s (بننقل للي بعده)" % (pid, model or ""))
        if not errors:
            raise RuntimeError("مفيش مزوّد تفريغ في الميزة دي")
        # النت بيتقدّم: friendly_error بيقول للمستخدم إن المشكلة في الاتصال مش في المفتاح
        net = next((e for e in errors if smart.is_network_error(e)), None)
        raise net or errors[-1]

    # ── المعالجة ──
    def _chat(self, system, text, temperature=0.2):
        out = self._chat_raw(system, text, temperature)
        return text if out is None else out

    def _chat_raw(self, system, text, temperature=0.2):
        self.last_chat = None
        if not text:
            return None
        for item in self._ai:
            pid, model = item.get("provider"), item.get("model")
            try:
                out = self._client(pid, chat_model=model)._chat_raw(system, text, temperature)
            except Exception as e:
                self._log(e, "chat/%s %s (بننقل للي بعده)" % (pid, model))
                continue
            if out is not None:
                self.last_chat = (providers.meta(pid)["name"], model)
                self.ai_ok = True
                return out
        return None

    def _prompt_lang(self, text):
        """نداء التصنيف (TECH/OTHER) مساعد بس — نجاحه مش معناه إن الكلام اتحوّل لبرومبت."""
        ok = self.ai_ok
        lang = super()._prompt_lang(text)
        self.ai_ok = ok
        return lang

    def engine(self):
        e = {"stt": self.last_stt_name, "stt_model": self.last_stt_model}
        if self.last_chat:
            e["chat"], e["chat_model"] = self.last_chat
        return e

    # ── للاختبارات ──
    def _clients_for_test(self):
        return list(self._clients.values())

    def _ai_items_for_test(self):
        return self._ai


def _strict_client(pid, keys, model, chat_model):
    return providers.Client(pid, keys[0], model=model, keys=keys, strict=True, chat_model=chat_model)


def _log_error(e, where):
    try:
        import core
        core.log_error(e, where)
    except Exception:
        pass
